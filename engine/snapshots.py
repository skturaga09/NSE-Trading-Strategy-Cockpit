"""Phase 3 snapshot publishing. Live store (owner decision, no Redis): the event stream
(downstream consumers), an in-process `latest` map, and <date>/snapshots.sqlite. The file is derived data:
compaction does not touch it and retention never deletes it. Rows are INSERT OR IGNORE on
(kind, key, ts_ns), so a warm restart that re-publishes the same snapshots changes nothing.
"""

import json
import sqlite3
import time
from dataclasses import fields, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable

from .candles import Aggregator, Candle, CombinedOI, DepthSnapshot, LateTick, QualityChange, Unavailable


def jsonable(x):
    if isinstance(x, Unavailable):
        return {"UNAVAILABLE": x.reason}
    if is_dataclass(x):
        return {"type": type(x).__name__, **{f.name: jsonable(getattr(x, f.name)) for f in fields(x)}}
    if isinstance(x, (tuple, list)):
        return [jsonable(v) for v in x]
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, Decimal):
        return str(x)
    return x


def key_of(x) -> tuple[str, str, int]:
    if isinstance(x, Candle):
        return "candle", f"{x.token}:{x.interval}", x.start_ns
    if isinstance(x, CombinedOI):
        return "combined_oi", f"{x.underlying}:{x.interval}", x.end_ns
    if isinstance(x, DepthSnapshot):
        return "depth", str(x.token), x.receive_ns
    if isinstance(x, QualityChange):
        return "quality", str(x.token), x.at_ns
    if isinstance(x, LateTick):
        return "late_tick", f"{x.token}:{x.conn}:{x.seq}", x.receive_ns
    raise TypeError(type(x))


class Publisher:
    def __init__(self, day_dir: Path | None = None, consumers: Iterable[Callable] = (), commit_every_s: float = 1.0):
        self.latest: dict[tuple[str, str], object] = {}
        self.consumers = list(consumers)
        self.db = None
        self._commit_every, self._t = commit_every_s, time.monotonic()
        if day_dir is not None:
            Path(day_dir).mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(Path(day_dir) / "snapshots.sqlite", check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS snapshots (kind TEXT, key TEXT, ts_ns INTEGER, payload TEXT, "
                            "PRIMARY KEY (kind, key, ts_ns))")

    def publish(self, items: list) -> None:
        rows = []
        for x in items:
            k = key_of(x)
            self.latest[k[:2]] = x
            rows.append((*k, json.dumps(jsonable(x), separators=(",", ":"))))
            for c in self.consumers:
                c(x)
        if self.db is not None and rows:
            self.db.executemany("INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?)", rows)
            if time.monotonic() - self._t >= self._commit_every:
                self.commit()

    def commit(self) -> None:
        if self.db is not None:
            self.db.commit()
            self._t = time.monotonic()

    def close(self) -> None:
        if self.db is not None:
            self.db.commit()
            self.db.close()
            self.db = None


class Pipeline:
    """Recorder consumer: Event -> Aggregator -> Publisher. `idle` is the recorder's on_idle hook: it moves
    the stream clock to wall - candles.idle_clock_margin_s, never backwards, so minutes close and
    STALE shows during a silent feed (e.g. a disconnect)."""

    def __init__(self, agg: Aggregator, pub: Publisher, margin_s: float):
        self.agg, self.pub, self.margin = agg, pub, int(margin_s * 1e9)

    def __call__(self, e) -> None:
        self.pub.publish(self.agg.on_event(e))

    def idle(self, now_ns: int) -> None:
        t = now_ns - self.margin
        if self.agg.clock is not None and t > self.agg.clock:
            self.pub.publish(self.agg.advance(t))
        self.pub.commit()


SNAP_COLS = ("kind", "key", "ts_ns", "payload")


def read_snapshots(day_dir: Path, kind: str | None = None) -> list[tuple]:
    """All snapshot rows of a day (or only one kind), sorted, from snapshots.sqlite or (after EOD) parquet/snapshots/."""
    day_dir = Path(day_dir)
    p = day_dir / "snapshots.sqlite"
    if p.exists():
        db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            where, args = (" WHERE kind=?", (kind,)) if kind else ("", ())
            return sorted(db.execute(f"SELECT {','.join(SNAP_COLS)} FROM snapshots{where}", args).fetchall())
        finally:
            db.close()
    import pyarrow.parquet as pq
    d = day_dir / "parquet" / "snapshots"
    if not d.exists():
        return []
    t = pq.read_table(d, filters=[("kind", "=", kind)] if kind else None).to_pydict()
    return sorted(zip(*(t[c] for c in SNAP_COLS)))


def _compact_streamed(day_dir: Path, src: Path, batch: int = 100_000) -> dict:
    """The live store -> Parquet in sorted batches; verified by a hash of every row read back (bounded memory, D-75).
    Same file content and row order as the in-memory path (SQLite BINARY order = Python str order for UTF-8)."""
    import hashlib
    import pyarrow as pa
    import pyarrow.parquet as pq
    out = day_dir / "parquet" / "snapshots" / "part-0.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([("kind", pa.string()), ("key", pa.string()), ("ts_ns", pa.int64()), ("payload", pa.string())])
    before = sum(f.stat().st_size for f in day_dir.glob("snapshots.sqlite*"))
    h_in, h_out, n = hashlib.sha256(), hashlib.sha256(), 0
    db = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        cur = db.execute(f"SELECT {','.join(SNAP_COLS)} FROM snapshots ORDER BY {','.join(SNAP_COLS)}")
        with pq.ParquetWriter(out, schema, compression="zstd") as w:
            for rows in iter(lambda: cur.fetchmany(batch), []):
                w.write_table(pa.Table.from_arrays([pa.array([r[i] for r in rows], type=schema.field(i).type)
                                                    for i in range(4)], schema=schema))
                for r in rows:
                    h_in.update(repr(r).encode())
                n += len(rows)
    finally:
        db.close()
    for b in pq.ParquetFile(out).iter_batches(batch_size=batch):
        t = b.to_pydict()
        for r in zip(*(t[c] for c in SNAP_COLS)):
            h_out.update(repr(r).encode())
    ok = h_in.digest() == h_out.digest()
    if ok:
        for f in day_dir.glob("snapshots.sqlite*"):
            f.unlink()
    return {"rows": n, "source": "live", "sqlite_bytes": before, "parquet_bytes": out.stat().st_size,
            "verified": ok, "sqlite_deleted": ok}


def compact_snapshots(day_dir: Path, replayed: list | None = None) -> dict:
    """EOD (owner decision): the day's snapshots -> parquet/snapshots/part-0.parquet (zstd).
    With `replayed` (a full replay of the day: engine.candles.aggregate over day_events(control=True)),
    the archive is the replay, and every row where the live store differs is counted and listed in
    snapshots_diff.json. That is the live == replay check on real data. Live rows can differ when the
    live process learned of a gap only after publishing (e.g. a stall before the watchdog existed).
    snapshots.sqlite is deleted only after the Parquet file reads back identical."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    day_dir = Path(day_dir)
    src = day_dir / "snapshots.sqlite"
    if not src.exists():
        return {"skipped": "no snapshots.sqlite"}
    if replayed is None:
        return _compact_streamed(day_dir, src)
    live = read_snapshots(day_dir)
    rows = live
    rep = {}
    if replayed is not None:
        rows = sorted({key_of(x): (*key_of(x), json.dumps(jsonable(x), separators=(",", ":"))) for x in replayed}.values())
        lv, rp = {r[:3]: r[3] for r in live}, {r[:3]: r[3] for r in rows}
        changed = sorted(k for k in lv.keys() & rp.keys() if lv[k] != rp[k])
        only_live, only_replay = sorted(lv.keys() - rp.keys()), sorted(rp.keys() - lv.keys())
        rep["live_vs_replay"] = {"identical": not (changed or only_live or only_replay), "changed": len(changed),
                                 "only_live": len(only_live), "only_replay": len(only_replay)}
        (day_dir / "snapshots_diff.json").write_text(json.dumps(
            {**rep["live_vs_replay"], "changed_sample": [[*k, lv[k], rp[k]] for k in changed[:50]],
             "only_live_sample": [[*k, lv[k]] for k in only_live[:50]],
             "only_replay_sample": [[*k, rp[k]] for k in only_replay[:50]]}, indent=1))
    before = sum(f.stat().st_size for f in day_dir.glob("snapshots.sqlite*"))
    out = day_dir / "parquet" / "snapshots" / "part-0.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([("kind", pa.string()), ("key", pa.string()), ("ts_ns", pa.int64()), ("payload", pa.string())])
    pq.write_table(pa.Table.from_arrays([pa.array([r[i] for r in rows], type=schema.field(i).type) for i in range(4)],
                                        schema=schema), out, compression="zstd")
    t = pq.read_table(out).to_pydict()
    ok = sorted(zip(*(t[c] for c in SNAP_COLS))) == rows
    if ok:
        for f in day_dir.glob("snapshots.sqlite*"):
            f.unlink()
    return {**rep, "rows": len(rows), "source": "replay" if replayed is not None else "live",
            "sqlite_bytes": before, "parquet_bytes": out.stat().st_size, "verified": ok, "sqlite_deleted": ok}
