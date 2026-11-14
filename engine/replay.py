"""Deterministic replay of recorded days with no look-ahead.

Events come out strictly in (exchange_ts, receive_ns, connection, sequence, kind) order and are
handed to the same `consumer(event)` callables the live recorder feeds. A ReplayClock advances to the
largest receive time emitted so far; the AsOfStore only holds what has been emitted and refuses to
answer for a time past the clock, so a consumer can never see an observation with receive_ts > as_of.

Sources per day: 'buffer' (intraday SQLite), 'parquet' (end-of-day compaction), 'frames' (raw
frames log, decoded on replay, every packet as received). 'auto' = buffer if present, else parquet.
"""

import bisect
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from .packets import decode, split_frame
from .store import (DEPTH_FIELDS, EVENT_COLS, GAP_COLS, TICK_FIELDS, Event, buffer_events, conn_event,
                    gap_event, read_frames, sort_key)


def read_zst(path: Path) -> bytes:
    """frames.bin.zst = <u64 little-endian raw size><zstd bytes>."""
    import pyarrow as pa
    raw = Path(path).read_bytes()
    return pa.decompress(raw[8:], decompressed_size=int.from_bytes(raw[:8], "little"), codec="zstd").to_pybytes()


def frames_bytes(day_dir: Path) -> bytes:
    """Raw frames log bytes: frames.bin, or after compaction frames.bin.zst."""
    p = Path(day_dir) / "frames.bin"
    return p.read_bytes() if p.exists() else read_zst(Path(day_dir) / "frames.bin.zst")


def iter_frames_events(data: bytes) -> Iterator[Event]:
    """Every packet of a raw frames log as events, in log order (streamed: nothing is accumulated)."""
    for rns, conn, seq0, payload in read_frames(data):
        for i, pkt in enumerate(split_frame(payload)):
            tok, ex, f, depth = decode(pkt)
            yield Event(ex, rns, conn, seq0 + i, "tick", tok, tuple(f.items()))
            if depth is not None:
                yield Event(ex, rns, conn, seq0 + i, "depth", tok, tuple(zip(DEPTH_FIELDS, depth)))


def frames_events(day_dir: Path) -> list[Event]:
    return list(iter_frames_events(frames_bytes(day_dir)))


PARQUET_EVENT_TABLES = (("ticks", TICK_FIELDS, "tick"), ("depth", DEPTH_FIELDS, "depth"))


def iter_parquet_file_events(f: Path, fields, kind: str, batch_rows: int = 50_000) -> Iterator[Event]:
    """One Parquet file's rows as events, in file order, one record batch at a time (bounded memory)."""
    import pyarrow.parquet as pq
    sec = lambda v: None if v is None else v // 1_000_000_000  # noqa: E731  (stored as ns, sent as s)
    for batch in pq.ParquetFile(f).iter_batches(batch_size=batch_rows):
        t = batch.to_pydict()
        if "last_trade_ts_ns" in t:
            t["last_trade_ts"] = [sec(v) for v in t.pop("last_trade_ts_ns")]
        ex = [sec(v) for v in t["exchange_ts_ns"]]
        vals = [t[c] for c in fields]
        for i in range(len(ex)):
            yield Event(ex[i], t["receive_ns"][i], t["conn"][i], t["seq"][i], kind, t["token"][i],
                        tuple((fields[k], vals[k][i]) for k in range(len(fields))))


def parquet_events(day_dir: Path, control: bool = False, data: bool = True) -> list[Event]:
    """data=False skips the tick/depth tables (control events only)."""
    import pyarrow.parquet as pq
    out = []
    for table, fields, kind in PARQUET_EVENT_TABLES if data else ():
        d = Path(day_dir) / "parquet" / table
        for f in sorted(d.rglob("*.parquet")) if d.exists() else []:
            out.extend(iter_parquet_file_events(f, fields, kind))
    for table, cols, make in (("events", EVENT_COLS, conn_event), ("gaps", GAP_COLS, gap_event)) if control else ():
        for f in sorted((Path(day_dir) / "parquet" / table).rglob("*.parquet")):
            t = pq.read_table(f).to_pydict()
            out += [make(r) for r in zip(*(t[c] for c in cols))]
    return out


def day_events(day_dir: Path, source: str = "auto", control: bool = False) -> list[Event]:
    """control=True adds the 'conn'/'gap' events (buffer/parquet only; the frames log has none)."""
    day_dir = Path(day_dir)
    if source == "auto":
        source = "buffer" if (day_dir / "buffer.sqlite").exists() else "parquet"
    load = {"buffer": buffer_events, "parquet": parquet_events, "frames": frames_events}[source]
    ev = load(day_dir, control) if control else load(day_dir)
    ev.sort(key=sort_key)
    return ev


def load_events(root: Path, start: date, end: date, source: str = "auto") -> list[Event]:
    out, d = [], start
    while d <= end:
        if (Path(root) / d.isoformat()).is_dir():
            out += day_events(Path(root) / d.isoformat(), source)
        d += timedelta(days=1)
    return out


def encode(events: Iterable[Event]) -> bytes:
    """Canonical byte form of an event stream (used for the byte-identical replay check)."""
    return b"".join(repr(tuple(e)).encode() + b"\n" for e in events)


class ReplayClock:
    def __init__(self):
        self.now_ns: int | None = None

    def advance(self, receive_ns: int) -> None:
        if self.now_ns is None or receive_ns > self.now_ns:
            self.now_ns = receive_ns


class AsOfStore:
    """Point-in-time lookups over observations emitted so far."""

    def __init__(self, clock: ReplayClock):
        self.clock = clock
        self._s: dict[tuple[int, str], tuple[list[int], list]] = {}

    def observe(self, e: Event) -> None:
        for field, value in e.data:
            ts, vs = self._s.setdefault((e.token, field), ([], []))
            i = bisect.bisect_right(ts, e.receive_ns)
            ts.insert(i, e.receive_ns)
            vs.insert(i, value)

    def get_latest(self, token: int, field: str, as_of: int):
        """-> (receive_ns, value) of the latest observation with receive_ns <= as_of, or None."""
        if self.clock.now_ns is None or as_of > self.clock.now_ns:
            raise ValueError(f"as_of {as_of} is after replay time {self.clock.now_ns}: that would be look-ahead")
        ts, vs = self._s.get((token, field), ([], []))
        i = bisect.bisect_right(ts, as_of)
        return (ts[i - 1], vs[i - 1]) if i else None


def replay(events: Sequence[Event], consumers: Iterable[Callable[[Event], None]] = (),
           speed: float | None = None, clock: ReplayClock | None = None, store: AsOfStore | None = None,
           sleep: Callable[[float], None] = time.sleep) -> int:
    """Emit events (already in sort_key order). speed=None: as fast as possible; k: k x real time."""
    clock = clock or ReplayClock()
    consumers = list(consumers)
    for e in events:
        prev = clock.now_ns
        clock.advance(e.receive_ns)
        if speed and prev is not None and clock.now_ns > prev:
            sleep((clock.now_ns - prev) / 1e9 / speed)
        if store is not None:
            store.observe(e)
        for c in consumers:
            c(e)
    return len(events)
