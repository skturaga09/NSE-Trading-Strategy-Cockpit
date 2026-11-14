"""Phase 3 acceptance: live and replay of the same recorded session give identical snapshots (golden file).

One scripted session goes through the real Recorder (tier executor, frames, connection events, a
disconnect, a watchdog stall, an out-of-order and a late tick). It runs live in two delivery patterns:
drained after every message with idle clock ticks, and drained once at the end (every connection event
then arrives before every frame, the worst case for ordering). It is then replayed from the buffer and
from the compacted Parquet. All four must match each other and tests/engine_tests/golden/phase3_session.jsonl.
Regenerate the golden file only on purpose: PHASE3_UPDATE_GOLDEN=1.
"""

import json
import os
import struct
import tempfile
import unittest
from pathlib import Path

from engine.candles import Aggregator, Candle, CombinedOI, DepthSnapshot, LateTick, QualityChange, aggregate
from engine.compact import compact
from engine.recorder import Recorder, TierExecutor
from engine.replay import day_events
from engine.snapshots import Pipeline, Publisher, jsonable
from engine.store import DayStore
from engine.tiers import Request, TierBook

from .fixtures import frame, full_packet, index_packet, make_config
from .test_candles import DAY, at

GOLDEN = Path(__file__).parent / "golden" / "phase3_session.jsonl"
FUT, FUT2, EQ, IDX = 12345602, 12345603, 738561, 256265


def quote_packet(token, ltp, volume):
    return struct.pack(">11I", token, ltp, 1, ltp, volume, 5, 6, ltp, ltp, ltp, ltp)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def session(root: Path, drain_each: bool) -> list:
    cfg = make_config(root)
    clock = Clock(at("09:14:00"))
    out = []
    pipe = Pipeline(Aggregator(cfg, DAY), Publisher(None, [out.append]), cfg.get("candles.idle_clock_margin_s"))
    store = DayStore(root / DAY.isoformat())
    rec = Recorder(cfg, store, consumers=[pipe], clock_ns=clock, disk_free=lambda: 10**12)
    book = TierBook(cfg, clock, describe=lambda t: ("FUT", "NIFTY"))
    book.set_tier_a([Request(IDX, "A", "quote", "INDEX", "NIFTY", "spot", 0),
                     Request(FUT, "A", "full", "FUT", "NIFTY", "fut", 1),
                     Request(FUT2, "A", "full", "FUT", "NIFTY", "fut", 2),
                     Request(EQ, "A", "quote", "EQ", "RELIANCE", "spot", 3)])
    book.promote(FUT, "watch", ttl=3600)
    TierExecutor(rec, book, cfg, lambda s: None, lambda *a: None, lambda s: True).step()
    rec.on_conn_event(0, "connect", {})

    def pump(t_str, *packets):
        clock.t = at(t_str)
        rec.on_message(0, frame(*packets), True)
        if drain_each:
            rec.drain()
            pipe.idle(clock.t)

    def conn(t_str, kind):
        clock.t = at(t_str)
        rec.on_conn_event(0, kind, {})
        if drain_each:
            rec.drain()
            pipe.idle(clock.t)

    secs = [h * 60 + s for h in range(14, 22) for s in range(0, 60, 5)]
    for i, x in enumerate(s for s in secs if 14 * 60 + 50 <= s <= 21 * 60 + 30):
        hms = f"09:{x // 60:02d}:{x % 60:02d}"
        if "09:18:01" <= hms < "09:18:40" or "09:20:00" < hms < "09:20:20":
            continue                                  # disconnected / stalled: nothing arrives
        if hms == "09:18:40":
            conn("09:18:40.1", "connect")
        ex = at(hms) // 10**9
        pump(hms + ".3", full_packet(FUT, ltp=2450000 + 50 * i, volume=1000 + 7 * i, oi=100000 + 25 * (i // 6),
                                     ex_ts=ex, last_trade_ts=ex),
             full_packet(FUT2, ltp=2460000 + 40 * i, volume=500 + 3 * i, oi=80000 - 25 * (i // 6), ex_ts=ex, last_trade_ts=ex),
             quote_packet(EQ, 150000 + 5 * i, 20000 + 11 * i), index_packet(IDX, ltp=2440000 + 45 * i)[:28])
        if hms == "09:16:30":
            pump("09:16:31.0", full_packet(FUT, ltp=2449000, volume=1000 + 7 * i - 2, oi=100000 + 25 * (i // 6),
                                           ex_ts=ex - 2, last_trade_ts=ex - 2))            # out of order, in window
        if hms == "09:17:00":
            pump("09:17:03.5", full_packet(FUT2, ltp=2455555, volume=500 + 3 * i - 1, oi=80000, ex_ts=ex - 1,
                                           last_trade_ts=ex - 1))                          # late (minute 09:16)
        if hms == "09:18:00":
            conn("09:18:01", "close")
        if hms == "09:20:00":
            clock.t = at("09:20:12")
            rec._control()  # the writer thread keeps conn_state current; drain-once mode must catch up first
            assert rec.check_stall([0], clock.t) == [0]  # watchdog: 12 s without a frame
            conn("09:20:12.5", "close")
            conn("09:20:19", "connect")
    rec.drain()
    rec.stop()
    store.close()
    return out


def lines(items) -> list[str]:
    return [json.dumps(jsonable(x), sort_keys=True) for x in items]


class TestLiveReplayGolden(unittest.TestCase):
    def test_live_and_replay_identical_golden(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            live_each, live_once = session(Path(a), True), session(Path(b), False)
            cfg, day = make_config(Path(a)), Path(a) / DAY.isoformat()
            replay_buf = aggregate(day_events(day, "buffer", control=True), cfg, DAY)
            self.assertTrue(all(compact(day, keep_buffer=True)["verified"].values()))
            replay_pq = aggregate(day_events(day, "parquet", control=True), cfg, DAY)
        got = lines(live_each)
        self.assertEqual(got, lines(live_once))
        self.assertEqual(got, lines(replay_buf))
        self.assertEqual(got, lines(replay_pq))
        if os.environ.get("PHASE3_UPDATE_GOLDEN") == "1" or not GOLDEN.exists():
            GOLDEN.parent.mkdir(exist_ok=True)
            GOLDEN.write_text("\n".join(got) + "\n")
        self.assertEqual(got, GOLDEN.read_text().splitlines())

        # what the session must contain (so the golden file can't silently be empty or trivial)
        one = {(c.token, c.start_ns): c for c in live_each if isinstance(c, Candle) and c.interval == "1m"}
        self.assertEqual(one[(FUT, at("09:15:00"))].completeness, "COMPLETE")
        for t in ("09:18:00", "09:20:00"):                          # disconnect, then stall
            self.assertEqual(one[(FUT, at(t))].completeness, "PARTIAL", t)
        self.assertEqual(one[(FUT, at("09:19:00"))].completeness, "COMPLETE")
        m16 = one[(FUT, at("09:16:00"))]                            # out-of-order tick accepted, slotted by exchange time:
        self.assertEqual(m16.low, 2449000)                           # its price is in the candle
        self.assertIsInstance(m16.volume, int)                       # and its volume did not look like a reset
        self.assertEqual([(x.token, x.bucket_ns) for x in live_each if isinstance(x, LateTick)], [(FUT2, at("09:16:00"))])
        self.assertTrue(any(isinstance(x, DepthSnapshot) and x.token == FUT for x in live_each))
        self.assertFalse(any(isinstance(x, DepthSnapshot) and x.token == FUT2 for x in live_each))  # tier A only
        self.assertTrue(any(isinstance(x, QualityChange) and x.quality.status == "STALE" for x in live_each))
        comb = [x for x in live_each if isinstance(x, CombinedOI) and x.interval == "1m"]
        self.assertTrue(comb and all(x.underlying == "NIFTY" for x in comb))
        self.assertIsInstance(one[(IDX, at("09:15:00"))].open, int)
        self.assertEqual(one[(IDX, at("09:15:00"))].time_basis, "receive")   # index quote packet: no exchange ts


if __name__ == "__main__":
    unittest.main()


class TestStallWatchdog(unittest.TestCase):
    def test_half_open_socket_becomes_a_stall_gap_once_and_clears_on_reconnect(self):
        with tempfile.TemporaryDirectory() as d:
            clock = Clock(at("09:15:00"))
            store = DayStore(Path(d) / DAY.isoformat())
            rec = Recorder(make_config(Path(d)), store, clock_ns=clock, disk_free=lambda: 10**12)
            rec.on_conn_event(0, "connect", {})
            rec.drain()
            clock.t = at("09:15:01")
            rec.on_message(0, b"\x00", True)                     # a 1-byte heartbeat counts as life
            self.assertEqual(rec.check_stall([0], at("09:15:10.9")), [])
            self.assertEqual(rec.check_stall([0], at("09:15:11")), [0])   # 10 s (ws.stall_after_s) since the heartbeat
            self.assertEqual(rec.check_stall([0], at("09:15:30")), [])    # logged once
            rec.drain()
            rows = store.db.execute("SELECT start_ns, end_ns, kind FROM gaps").fetchall()
            self.assertEqual(rows, [(at("09:15:01"), at("09:15:11"), "stall")])
            clock.t = at("09:15:40")
            rec.on_conn_event(0, "connect", {})
            rec.drain()
            self.assertEqual(rec.check_stall([0], at("09:15:49")), [])
            self.assertEqual(rec.check_stall([0], at("09:15:50")), [0])   # armed again after the reconnect
            store.close()


class TestFeedReportAndSnapshotCompaction(unittest.TestCase):
    def test_streamed_compaction_without_replay_is_lossless_and_sorted(self):
        """D-75: big days skip the in-memory replay; the live store is copied in batches and hash-verified."""
        import pyarrow.parquet as pq
        from engine.snapshots import SNAP_COLS, compact_snapshots, read_snapshots
        with tempfile.TemporaryDirectory() as d:
            items = session(Path(d), True)
            day = Path(d) / DAY.isoformat()
            pub = Publisher(day)
            pub.publish(items)
            pub.close()
            rows = read_snapshots(day)
            c = compact_snapshots(day)
            self.assertEqual((c["source"], c["rows"], c["verified"], c["sqlite_deleted"]), ("live", len(rows), True, True))
            self.assertFalse((day / "snapshots.sqlite").exists())
            t = pq.read_table(day / "parquet" / "snapshots" / "part-0.parquet").to_pydict()
            self.assertEqual(list(zip(*(t[k] for k in SNAP_COLS))), rows)       # stored already in sorted order
            self.assertEqual(read_snapshots(day, kind="quality"), [r for r in rows if r[0] == "quality"])

    def test_report_then_compact_snapshots_losslessly(self):
        from engine.feed_report import report
        from engine.snapshots import compact_snapshots, read_snapshots
        with tempfile.TemporaryDirectory() as d:
            items = session(Path(d), True)
            day = Path(d) / DAY.isoformat()
            pub = Publisher(day)
            pub.publish(items)
            pub.publish(items)                              # a warm restart re-publishes: no duplicates
            pub.close()
            rows = read_snapshots(day)
            self.assertEqual(len(rows), len(items))
            r = report(day)
            self.assertGreater(r["latency_s"]["packets"], 0)
            self.assertEqual(r["allocator"]["last_usage"]["A"], 4)
            self.assertEqual(r["allocator"]["last_usage"]["B"], 1)
            self.assertEqual({g["kind"] for g in r["gaps"]}, {"disconnect", "stall"})
            self.assertGreaterEqual(r["staleness"]["incidents_recovered"], 1)
            import sqlite3
            db = sqlite3.connect(day / "snapshots.sqlite")   # a wrong live row (e.g. published during an undetected stall)
            db.execute("UPDATE snapshots SET payload = replace(payload, 'COMPLETE', 'EMPTY') "
                       "WHERE rowid = (SELECT MIN(rowid) FROM snapshots WHERE payload LIKE '%\"COMPLETE\"%')")
            db.commit()
            db.close()
            replayed = aggregate(day_events(day, "buffer", control=True), make_config(Path(d)), DAY)
            c = compact_snapshots(day, replayed)
            self.assertTrue(c["verified"] and c["sqlite_deleted"])
            self.assertEqual(c["live_vs_replay"], {"identical": False, "changed": 1, "only_live": 0, "only_replay": 0})
            self.assertEqual(json.loads((day / "snapshots_diff.json").read_text())["changed"], 1)
            self.assertFalse((day / "snapshots.sqlite").exists())
            self.assertEqual(read_snapshots(day), rows)
            self.assertEqual(report(day)["staleness"], r["staleness"])
