import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

from engine.packets import decode, split_frame
from engine.recorder import Recorder
from engine.replay import AsOfStore, ReplayClock, day_events, encode, replay
from engine.store import DayStore, Event, read_frames

from .fixtures import EQ, FUT, IDX, Clock, frame, full_packet, index_packet, make_config

S = 1_000_000_000


def rows(day, sql):
    c = sqlite3.connect(Path(day) / "buffer.sqlite")
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.day = self.root / "2026-11-06"
        self.clock = Clock()
        self.free = [100 * 10**9]

    def tearDown(self):
        if getattr(self, "store", None) and not self.store.frames.closed:
            self.store.close()
        self.tmp.cleanup()

    def recorder(self, consumers=(), **cfg):
        self.store = DayStore(self.day)
        return Recorder(make_config(self.root, **cfg), self.store, consumers, clock_ns=self.clock,
                        disk_free=lambda: self.free[0], alert=lambda m: self.alerts.append(m))

    alerts: list


class TestPackets(unittest.TestCase):
    def test_full_and_index_decode_raw_ints(self):
        pk = split_frame(frame(full_packet(oi=777, ex_ts=1_790_000_123), index_packet(ex_ts=1_790_000_124)))
        tok, ex, f, depth = decode(pk[0])
        self.assertEqual((tok, ex, f["mode"], f["ltp"], f["oi"]), (FUT, 1_790_000_123, "full", 2450000, 777))
        self.assertEqual(len(depth), 30)
        self.assertEqual(depth[:3], (10, 100000, 1))
        tok, ex, f, depth = decode(pk[1])
        self.assertEqual((tok, ex, f["mode"], f["oi"], depth), (IDX, 1_790_000_124, "full", None, None))

    def test_unknown_length_is_flagged_not_guessed(self):
        tok, ex, f, depth = decode(b"\x00\x00\x00\x01" + b"\x00" * 6)
        self.assertEqual(f["mode"], "unknown:10")
        self.assertIsNone(f["ltp"])

    def test_heartbeat_has_no_packets(self):
        self.assertEqual(split_frame(b"\x00"), [])


class TestRecorder(Base):
    def setUp(self):
        super().setUp()
        self.alerts = []

    def test_out_of_order_and_duplicates_stored_as_received_and_replay_deterministic(self):
        rec = self.recorder()
        frames = [frame(full_packet(ex_ts=1_790_000_010, ltp=2450100)),
                  frame(full_packet(ex_ts=1_790_000_005, ltp=2450200)),   # older exchange ts arrives later
                  frame(full_packet(ex_ts=1_790_000_005, ltp=2450200)),   # exact duplicate
                  frame(index_packet(ex_ts=1_790_000_007), full_packet(token=EQ, oi=0, ex_ts=1_790_000_006))]
        for f in frames:
            rec.on_message(0, f, True)
        rec.drain()
        self.store.close()
        stored = [p for _, _, _, p in read_frames((self.day / "frames.bin").read_bytes())]
        self.assertEqual(stored, frames)  # every frame, byte-exact, in arrival order (duplicate included)
        for src in ("frames", "buffer"):
            a, b = encode(day_events(self.day, src)), encode(day_events(self.day, src))
            self.assertEqual(a, b, src)  # two replays: byte-identical
            ev = day_events(self.day, src)
            keys = [(e.exchange_ts, e.receive_ns, e.conn, e.seq, e.kind) for e in ev]
            self.assertEqual(keys, sorted(keys), src)
        fr = [e for e in day_events(self.day, "frames") if e.kind == "tick" and e.token == FUT]
        self.assertEqual([e.exchange_ts for e in fr], [1_790_000_005, 1_790_000_005, 1_790_000_010])
        self.assertEqual(len({e.seq for e in fr}), 3)  # duplicate kept, with its own sequence number

    def test_change_only_ticks_and_rate_limited_depth(self):
        rec = self.recorder()
        rec.on_message(0, frame(full_packet(ex_ts=1, last_trade_ts=1)), True)
        rec.on_message(0, frame(full_packet(ex_ts=2, last_trade_ts=2)), True)            # timestamps only: skipped
        rec.on_message(0, frame(full_packet(ex_ts=3, ltp=2450500)), True)                 # price changed: kept
        d2 = [(99, 1, 1)] * 10
        rec.on_message(0, frame(full_packet(ex_ts=4, ltp=2450600, depth=d2)), True)      # depth changed <1s: skipped
        self.clock.t += 2 * S
        rec.on_message(0, frame(full_packet(ex_ts=5, ltp=2450700, depth=d2)), True)      # >=1s later: written
        rec.drain()
        self.assertEqual(rows(self.day, "SELECT exchange_ts FROM ticks"), [(1,), (3,), (4,), (5,)])
        self.assertEqual(rows(self.day, "SELECT exchange_ts FROM depth"), [(1,), (5,)])
        self.assertEqual(rec.counts["ticks_unchanged_skipped"], 1)

    def test_oi_change_log_only_on_change(self):
        rec = self.recorder()
        for i, oi in enumerate([100, 100, 105, 105, 103]):
            rec.on_message(0, frame(full_packet(oi=oi, ex_ts=1_790_000_000 + i, ltp=2450000 + i)), True)
        rec.drain()
        self.assertEqual(rows(self.day, "SELECT exchange_ts, oi, prev_oi FROM oi_changes"),
                         [(1_790_000_000, 100, None), (1_790_000_002, 105, 100), (1_790_000_004, 103, 105)])

    def test_disconnect_produces_gap_and_no_synthetic_ticks(self):
        rec = self.recorder()
        rec.on_conn_event(0, "connect", {})
        rec.on_message(0, frame(full_packet(ex_ts=1, ltp=1)), True)
        rec.on_conn_event(0, "close", {"code": 1006})
        close_ns = self.clock.t
        self.clock.t += 30 * S
        rec.on_conn_event(0, "reconnect_attempt", {"attempt": 1})
        rec.on_conn_event(0, "connect", {})
        open_ns = self.clock.t
        rec.on_message(0, frame(full_packet(ex_ts=40, ltp=2)), True)
        rec.drain()
        gaps = rows(self.day, "SELECT start_ns, end_ns, conn, kind FROM gaps")
        self.assertEqual(gaps, [(close_ns, open_ns, 0, "disconnect")])
        self.assertEqual(rows(self.day, f"SELECT COUNT(*) FROM ticks WHERE receive_ns BETWEEN {close_ns} AND {open_ns}"),
                         [(0,)])
        self.assertEqual(rows(self.day, "SELECT COUNT(*) FROM ticks"), [(2,)])
        kinds = [k for k, in rows(self.day, "SELECT kind FROM events ORDER BY receive_ns")]
        self.assertEqual(kinds, ["connect", "close", "reconnect_attempt", "connect"])

    def test_disconnect_open_at_session_end_is_closed_as_gap(self):
        rec = self.recorder()
        rec.on_conn_event(0, "connect", {})
        rec.on_conn_event(0, "error", {"code": 403})
        rec.drain()
        rec.stop()
        self.assertEqual([k for k, in rows(self.day, "SELECT kind FROM gaps")], ["disconnect"])

    def test_own_shutdown_close_is_not_a_gap(self):
        rec = self.recorder()
        rec.on_conn_event(0, "connect", {})
        rec.on_conn_event(0, "shutdown", {})
        rec.on_conn_event(0, "close", {"code": 1000})
        rec.drain()
        rec.stop()
        self.assertEqual(rows(self.day, "SELECT COUNT(*) FROM gaps"), [(0,)])

    def test_queue_overflow_logs_gap_not_crash(self):
        rec = self.recorder(**{"writer.queue_max": 2})
        for i in range(5):
            rec.on_message(0, frame(full_packet(ex_ts=i, ltp=i)), True)  # writer not draining: 3 dropped
        rec.drain()
        self.assertEqual(rows(self.day, "SELECT kind, count FROM gaps"), [("queue_drop", 3)])
        self.assertEqual(rows(self.day, "SELECT COUNT(*) FROM ticks"), [(2,)])
        self.assertEqual(rec.dropped_total, 3)
        self.assertEqual(rec.status(self.clock.t)["gaps_today"], 1)

    def test_disk_guard_degrades_depth_then_ticks_with_gap_records(self):
        rec = self.recorder()
        n = [0]

        def tick():
            n[0] += 1
            rec.on_message(0, frame(full_packet(ex_ts=n[0], ltp=n[0], depth=[(n[0], 1, 1)] * 10)), True)
            self.clock.t += 2 * S
            rec.drain()

        for free_gb in (100, 4, 2.5, 2.5, 1, 1, 10):
            self.free[0] = int(free_gb * 10**9)
            rec._disk_check()
            tick()
        rec.stop()
        self.assertEqual(sorted(rows(self.day, "SELECT kind, count FROM gaps")), [("disk_depth", 4), ("disk_ticks", 2)])
        kinds = {k for k, in rows(self.day, "SELECT kind FROM events")}
        self.assertTrue({"disk_alert", "disk_stop_depth", "disk_stop_ticks"} <= kinds)
        self.assertEqual(rows(self.day, "SELECT COUNT(*) FROM ticks"), [(5,)])   # 7 sent, 2 while ticks stopped
        self.assertEqual(rows(self.day, "SELECT COUNT(*) FROM depth"), [(3,)])   # 7 sent, 4 while depth stopped
        self.assertTrue(self.alerts)

    def test_live_consumers_get_same_events_as_replay(self):
        live = []
        rec = self.recorder(consumers=[live.append])
        for i in range(5):
            self.clock.t += 2 * S
            rec.on_message(0, frame(full_packet(ex_ts=10 - i, ltp=i, depth=[(i, 1, 1)] * 10), index_packet(ltp=i)), True)
        rec.drain()
        replayed = []
        replay(day_events(self.day, "buffer"), [replayed.append])
        self.assertEqual(sorted(live, key=lambda e: (e.exchange_ts, e.receive_ns, e.conn, e.seq, e.kind)), replayed)


class TestAsOf(unittest.TestCase):
    def test_get_latest_never_returns_future_data_property(self):
        rng = random.Random(20261105)
        for trial in range(200):
            events = [Event(rng.randint(0, 50), rng.randint(0, 10**6), 0, i, "tick", rng.choice([1, 2]),
                            (("ltp", rng.randint(1, 9)),)) for i in range(rng.randint(1, 60))]
            events.sort(key=lambda e: (e.exchange_ts, e.receive_ns, e.conn, e.seq, e.kind))
            clock = ReplayClock()
            store = AsOfStore(clock)
            seen = []

            def check(e):
                seen.append(e)
                for _ in range(5):
                    as_of = rng.randint(0, clock.now_ns)
                    tok = rng.choice([1, 2])
                    got = store.get_latest(tok, "ltp", as_of)
                    cands = [x for x in seen if x.token == tok and x.receive_ns <= as_of]
                    if got is None:
                        self.assertEqual(cands, [])
                    else:
                        self.assertLessEqual(got[0], as_of)
                        self.assertEqual(got[0], max(x.receive_ns for x in cands))
                with self.assertRaises(ValueError):
                    store.get_latest(1, "ltp", clock.now_ns + rng.randint(1, 10**6))

            replay(events, [check], clock=clock, store=store)

    def test_real_time_speed_sleeps_by_clock_delta(self):
        sleeps = []
        ev = [Event(1, 0, 0, 0, "tick", 1, ()), Event(2, 2 * S, 0, 1, "tick", 1, ()), Event(3, S, 0, 2, "tick", 1, ())]
        replay(ev, speed=2.0, sleep=sleeps.append)
        self.assertEqual(sleeps, [1.0])  # clock never moves backwards, so no sleep for the third event



class TestMasterSnapshot(unittest.TestCase):                   # Phase 1 3f (Phase 15 G-8)
    def test_master_is_fetched_once_per_date_and_stored_gzipped_under_that_date(self):
        import gzip
        from engine.recorder import _master

        class Session:
            calls = 0

            def instruments_csv(self):
                Session.calls += 1
                return b"instrument_token,tradingsymbol\n1,NIFTY26NOVFUT\n"
        with tempfile.TemporaryDirectory() as td:
            day = Path(td) / "2026-11-06"
            self.assertEqual(_master(Session(), day), b"instrument_token,tradingsymbol\n1,NIFTY26NOVFUT\n")
            self.assertEqual(gzip.decompress((day / "instruments.csv.gz").read_bytes()), _master(Session(), day))
            self.assertEqual(Session.calls, 1)                 # the second call reads the stored snapshot
            self.assertFalse((day / "instruments.csv.tmp").exists())


if __name__ == "__main__":
    unittest.main()
