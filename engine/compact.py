"""End-of-day compaction + storage measurement (steps 7-8).

  python3 -m engine.compact YYYY-MM-DD [--keep-buffer]

1. Measures bytes per table in the intraday buffer (each table copied to its own SQLite file),
   plus the raw frames log and the instrument master.
2. Format A: typed Parquet (zstd) per table, partitioned <date>/parquet/<table>/family=<segment>/.
   Prices stay the exchange integers (paise); receive/exchange/last-trade times int64 ns; token uint32
   (Kite tokens are unsigned on the wire and can exceed int32).
3. Format B: the raw frames log zstd-compressed (frames.bin.zst = <u64 raw size><zstd bytes>).
4. Verifies: replay(parquet) is byte-identical to replay(buffer); frames.bin.zst decompresses to the
   exact original bytes; derived-table row counts match. Times replay for A and B.
   Everything is streamed with bounded memory (Q-6-5: holding a full day's events in memory got the EOD job
   SIGKILLed on the 8 GB host). The verification compares every event, not a sample.
5. Only if every check passes are buffer.sqlite and frames.bin deleted. Writes storage_report.json.
"""

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from itertools import zip_longest
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from .config import load_config
from .provider import parse_master
from .replay import PARQUET_EVENT_TABLES, iter_frames_events, iter_parquet_file_events, read_zst
from .store import DEPTH_COLS, EVENT_COLS, GAP_COLS, OI_COLS, TICK_COLS, depth_event, tick_event

U32 = {"token", "ltp", "ltq", "atp", "volume", "tbq", "tsq", "open", "high", "low", "close",
       "oi", "oi_day_high", "oi_day_low", "index_change", "prev_oi"}
NS = {"exchange_ts", "last_trade_ts"}  # epoch seconds on the wire -> stored as int64 ns
FAMILY_TABLES = ("ticks", "depth", "oi_changes")
TABLES = {"ticks": TICK_COLS, "depth": DEPTH_COLS, "oi_changes": OI_COLS, "events": EVENT_COLS,
          "gaps": GAP_COLS, "meta": ("key", "value")}


def _type(col: str):
    if col in ("mode", "kind", "detail", "reason", "key", "value"):
        return pa.string()
    if col in U32 or col.endswith(("_qty", "_price", "_orders")):
        return pa.uint32()
    if col == "conn":
        return pa.int16()  # -1 = not connection-specific
    return pa.int64()


def table_sizes(db_path: Path) -> dict[str, int]:
    out = {}
    with tempfile.TemporaryDirectory() as td:
        for t in TABLES:
            p = Path(td) / f"{t}.sqlite"
            c = sqlite3.connect(p)
            c.execute("ATTACH ? AS src", (str(db_path),))
            c.execute(f"CREATE TABLE {t} AS SELECT * FROM src.{t}")
            c.commit()
            c.close()
            out[t] = p.stat().st_size
    return out


def _families(day_dir: Path) -> dict[int, str]:
    p = day_dir / "instruments.csv.gz"
    if not p.exists():
        return {}
    return {int(r["instrument_token"]): r["segment"] for r in parse_master(gzip.decompress(p.read_bytes()))}


BATCH_ROWS = 100_000   # engineering choice: rows held in memory per table and family while compacting (Q-6-5)


def _family_key(t: str, token, fam: dict[int, str]) -> str:
    return fam.get(token, "UNKNOWN") if t in FAMILY_TABLES else "_all"


def write_parquet(day_dir: Path) -> dict[str, int]:
    """Streamed (Q-6-5): rows are read in rowid order BATCH_ROWS at a time and appended, per family, to one Parquet file
    each, so memory stays bounded whatever the day's size. Same files, schema and row order as before."""
    db = sqlite3.connect(day_dir / "buffer.sqlite")
    fam = _families(day_dir)
    sizes = {}
    try:
        for t, cols in TABLES.items():
            names = [f"{c}_ns" if c in NS else c for c in cols]
            schema = pa.schema([(n, _type(c)) for n, c in zip(names, cols)])
            ns_idx = [i for i, c in enumerate(cols) if c in NS]
            tok_idx = cols.index("token") if "token" in cols else None
            writers, pending = {}, {}

            def flush(key):
                rows = pending.pop(key, [])
                if key not in writers:
                    out = day_dir / "parquet" / t / f"family={key}" / "part-0.parquet"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    writers[key] = pq.ParquetWriter(out, schema, compression="zstd")
                if rows:
                    arrays = [pa.array([r[i] for r in rows], type=schema.field(n).type) for i, n in enumerate(names)]
                    writers[key].write_table(pa.Table.from_arrays(arrays, schema=schema))

            cur = db.execute(f"SELECT {','.join(cols)} FROM {t} ORDER BY rowid")
            while batch := cur.fetchmany(BATCH_ROWS):
                for r in batch:
                    if ns_idx:
                        r = list(r)
                        for i in ns_idx:
                            r[i] = None if r[i] is None else r[i] * 1_000_000_000
                    key = _family_key(t, r[tok_idx] if tok_idx is not None else None, fam)
                    pending.setdefault(key, []).append(r)
                for key in [k for k, v in pending.items() if len(v) >= BATCH_ROWS]:
                    flush(key)
            for key in list(pending):
                flush(key)
            if not writers:                       # empty table: one empty file, as before
                flush("_all")
            sizes[t] = 0
            for key, w in writers.items():
                w.close()
                sizes[t] += (day_dir / "parquet" / t / f"family={key}" / "part-0.parquet").stat().st_size
    finally:
        db.close()
    return sizes


def write_frames_zst(day_dir: Path) -> int:
    raw = (day_dir / "frames.bin").read_bytes()
    out = day_dir / "frames.bin.zst"
    out.write_bytes(len(raw).to_bytes(8, "little") + pa.compress(raw, codec="zstd", asbytes=True))
    del raw
    return out.stat().st_size


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def _buffer_events(db, table: str, tokens: list[int] | None) -> Iterator:
    """One table's buffer rows as events (same constructors as store.buffer_events), rowid order, optionally one family."""
    cols, make = (TICK_COLS, tick_event) if table == "ticks" else (DEPTH_COLS, depth_event)
    where = f" WHERE token IN ({','.join('?' * len(tokens))})" if tokens is not None else ""
    cur = db.execute(f"SELECT {','.join(cols)} FROM {table}{where} ORDER BY rowid", tokens or ())
    while batch := cur.fetchmany(BATCH_ROWS):
        yield from map(make, batch)


def verify_parquet(day_dir: Path, fam: dict[int, str]) -> tuple[bool, dict]:
    """Streamed equivalent of `encode(day_events(buffer)) == encode(day_events(parquet))`: every Parquet file of ticks and
    depth is compared event by event, as repr bytes, with the buffer rows of the same table and family in the same
    (rowid) order. Equal per-file streams => equal event multisets => equal sorted replays (sort_key is unique per event).
    Also streams each source once on its own to count events and time a replay pass (no event list is ever built)."""
    db = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
    ok, n = True, 0
    try:
        for table, fields, kind in PARQUET_EVENT_TABLES:
            toks: dict[str, list[int]] = {}
            for (tok,) in db.execute(f"SELECT DISTINCT token FROM {table}"):
                toks.setdefault(_family_key(table, tok, fam), []).append(tok)
            files = sorted((day_dir / "parquet" / table).rglob("*.parquet"))
            if sorted(f.parent.name.removeprefix("family=") for f in files if pq.ParquetFile(f).metadata.num_rows) != sorted(toks):
                return False, {"reason": f"{table}: family files differ from the buffer's families"}
            for f in files:
                key = f.parent.name.removeprefix("family=")
                pairs = zip_longest(_buffer_events(db, table, toks.get(key, [])), iter_parquet_file_events(f, fields, kind))
                for a, b in pairs:
                    n += 1
                    if a is None or b is None or repr(tuple(a)) != repr(tuple(b)):
                        return False, {"reason": f"{table}/{f.parent.name}: first difference at event {n}"}
        timing = {}
        for name, gen in (("buffer", lambda: (e for t in ("ticks", "depth") for e in _buffer_events(db, t, None))),
                          ("parquet", lambda: (e for t, fl, k in PARQUET_EVENT_TABLES
                                               for f in sorted((day_dir / "parquet" / t).rglob("*.parquet"))
                                               for e in iter_parquet_file_events(f, fl, k)))):
            t0 = time.perf_counter()
            timing[f"events_{name}"] = sum(1 for _ in gen())
            timing[f"seconds_{name}"] = round(time.perf_counter() - t0, 4)
        return ok, timing
    finally:
        db.close()


def _timed(fn, *a):
    t = time.perf_counter()
    r = fn(*a)
    return r, time.perf_counter() - t


def compact(day_dir: Path, keep_buffer: bool = False) -> dict:
    day_dir = Path(day_dir)
    buf = day_dir / "buffer.sqlite"
    if not buf.exists():
        raise FileNotFoundError(f"{buf}: nothing to compact")
    rep = {"date": day_dir.name, "before_bytes": table_sizes(buf)}
    rep["before_bytes"]["frames.bin"] = (day_dir / "frames.bin").stat().st_size
    rep["before_bytes"]["buffer.sqlite(file)"] = buf.stat().st_size
    if (day_dir / "instruments.csv.gz").exists():
        rep["before_bytes"]["instrument_master(csv.gz)"] = (day_dir / "instruments.csv.gz").stat().st_size

    rep["A_parquet_bytes"] = write_parquet(day_dir)
    rep["B_frames_zst_bytes"] = write_frames_zst(day_dir)

    same, timing = verify_parquet(day_dir, _families(day_dir))
    unz = read_zst(day_dir / "frames.bin.zst")       # one copy of the raw log (~0.5 GB on a full day)
    zst_ok = hashlib.sha256(unz).hexdigest() == _sha256_file(day_dir / "frames.bin")
    t0 = time.perf_counter()
    n_frames = sum(1 for _ in iter_frames_events(unz))
    t_fr = time.perf_counter() - t0
    del unz
    db = sqlite3.connect(f"file:{buf}?mode=ro", uri=True)
    counts_ok = all(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    == sum(pq.ParquetFile(f).metadata.num_rows for f in (day_dir / "parquet" / t).rglob("*.parquet"))
                    for t in TABLES)
    db.close()
    rep["replay"] = {"events_buffer": timing.get("events_buffer"), "events_parquet": timing.get("events_parquet"),
                     "events_frames": n_frames, "seconds_buffer": timing.get("seconds_buffer"),
                     "seconds_parquet_A": timing.get("seconds_parquet"), "seconds_frames_B": round(t_fr, 4),
                     "method": "streamed passes (Q-6-5); no event list is built"}
    if not same:
        rep["replay"]["mismatch"] = timing.get("reason")
    rep["verified"] = {"parquet_replay_identical": same, "frames_zst_roundtrip": zst_ok, "row_counts_match": counts_ok}
    ok = all(rep["verified"].values())
    if ok and not keep_buffer:
        for p in (buf, day_dir / "buffer.sqlite-wal", day_dir / "buffer.sqlite-shm", day_dir / "frames.bin"):
            p.unlink(missing_ok=True)
    rep["buffer_deleted"] = ok and not keep_buffer
    (day_dir / "storage_report.json").write_text(json.dumps(rep, indent=2))
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.compact")
    ap.add_argument("date")
    ap.add_argument("--keep-buffer", action="store_true")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config) if a.config else load_config()
    rep = compact(cfg.root / a.date, a.keep_buffer)
    print(json.dumps(rep, indent=2))
    return 0 if all(rep["verified"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
