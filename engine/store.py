"""Per-trading-date storage: append-only SQLite buffer + append-only raw frames log.

Layout (one directory per IST trading date, under config storage.root):
  <date>/buffer.sqlite      ticks, depth, oi_changes, events, gaps, meta   (INSERT only)
  <date>/frames.bin         every binary WebSocket frame as received: <q receive_ns><B conn><q seq_first><I len><payload>
  <date>/instruments.csv.gz the full instrument master dump of that date
  <date>/status.json        recorder health (overwritten every status interval)
Timestamps: receive_ns = int64 ns since epoch (UTC, i.e. tz-aware); exchange_ts/last_trade_ts = epoch seconds as sent.
"""

import sqlite3
import struct
from pathlib import Path
from typing import Iterator, NamedTuple

from .packets import DEPTH_FIELDS, TICK_FIELDS

FRAME_HDR = struct.Struct("<qBqI")
KEY_COLS = ("receive_ns", "conn", "seq", "token", "exchange_ts")
TICK_COLS = KEY_COLS + TICK_FIELDS
DEPTH_COLS = KEY_COLS + DEPTH_FIELDS
OI_COLS = ("token", "exchange_ts", "receive_ns", "conn", "seq", "oi", "prev_oi")
EVENT_COLS = ("receive_ns", "conn", "kind", "detail")
GAP_COLS = ("start_ns", "end_ns", "conn", "kind", "reason", "count")


class Event(NamedTuple):
    """One replayable observation. Ordered by sort_key(); `data` is ((field, value), ...).
    Phase 3 (owner-approved) adds kind 'conn' (a row of `events`: data (('event', kind), ('detail', ..)))
    and 'gap' (a row of `gaps`, at its end_ns). Both have token -1, seq 0, exchange_ts None. They reach live
    consumers as they are written, and replay loads them only with control=True."""
    exchange_ts: int | None
    receive_ns: int
    conn: int
    seq: int
    kind: str  # 'depth' | 'tick' | 'conn' | 'gap'
    token: int
    data: tuple


def sort_key(e: Event):
    return (-1 if e.exchange_ts is None else e.exchange_ts, e.receive_ns, e.conn, e.seq, e.kind)


ARRIVAL_RANK = {"conn": 0, "gap": 1, "tick": 2, "depth": 3}


def arrival_key(e: Event):
    """The order the recorder delivers to live consumers: by receive time and connection; inside one frame
    all its tick rows, then all its depth rows; a connection event before the gap it closes. Phase 3
    aggregators are fed in this order."""
    return (e.receive_ns, e.conn, ARRIVAL_RANK[e.kind], e.seq)


def _ddl(name, cols, text=("mode", "kind", "detail", "reason", "key", "value")):
    return f"CREATE TABLE IF NOT EXISTS {name} (" + ", ".join(
        f"{c} {'TEXT' if c in text else 'INTEGER'}" for c in cols) + ")"


class DayStore:
    def __init__(self, day_dir: Path):
        self.dir = Path(day_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "buffer.sqlite", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        for name, cols in (("ticks", TICK_COLS), ("depth", DEPTH_COLS), ("oi_changes", OI_COLS),
                           ("events", EVENT_COLS), ("gaps", GAP_COLS), ("meta", ("key", "value"))):
            self.db.execute(_ddl(name, cols))
        self.frames = open(self.dir / "frames.bin", "ab")

    def insert(self, table: str, rows: list[tuple]) -> None:
        if rows:
            self.db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)

    def write_frame(self, receive_ns: int, conn: int, seq_first: int, payload: bytes) -> None:
        self.frames.write(FRAME_HDR.pack(receive_ns, conn, seq_first, len(payload)) + payload)

    def commit(self) -> None:
        self.frames.flush()
        self.db.commit()

    def close(self) -> None:
        self.commit()
        self.frames.close()
        self.db.close()


def read_frames(data: bytes) -> Iterator[tuple[int, int, int, bytes]]:
    j = 0
    while j + FRAME_HDR.size <= len(data):
        rns, conn, seq, ln = FRAME_HDR.unpack_from(data, j)
        j += FRAME_HDR.size
        if j + ln > len(data):
            break  # torn tail write (crash mid-append): ignored, never padded
        yield rns, conn, seq, data[j:j + ln]
        j += ln


def tick_event(row: tuple) -> Event:
    rns, conn, seq, tok, ex = row[:5]
    return Event(ex, rns, conn, seq, "tick", tok, tuple(zip(TICK_FIELDS, row[5:])))


def depth_event(row: tuple) -> Event:
    rns, conn, seq, tok, ex = row[:5]
    return Event(ex, rns, conn, seq, "depth", tok, tuple(zip(DEPTH_FIELDS, row[5:])))


def conn_event(row: tuple) -> Event:
    rns, conn, kind, detail = row
    return Event(None, rns, conn, 0, "conn", -1, (("event", kind), ("detail", detail)))


def gap_event(row: tuple) -> Event:
    return Event(None, row[1], row[2], 0, "gap", -1, tuple(zip(GAP_COLS, row)))


def buffer_events(day_dir: Path, control: bool = False) -> list[Event]:
    db = sqlite3.connect(Path(day_dir) / "buffer.sqlite")
    try:
        ev = [tick_event(r) for r in db.execute(f"SELECT {','.join(TICK_COLS)} FROM ticks")]
        ev += [depth_event(r) for r in db.execute(f"SELECT {','.join(DEPTH_COLS)} FROM depth")]
        if control:
            ev += [conn_event(r) for r in db.execute(f"SELECT {','.join(EVENT_COLS)} FROM events ORDER BY rowid")]
            ev += [gap_event(r) for r in db.execute(f"SELECT {','.join(GAP_COLS)} FROM gaps ORDER BY rowid")]
    finally:
        db.close()
    return ev
