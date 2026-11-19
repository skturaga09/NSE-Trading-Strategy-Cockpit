import gzip
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import tempfile
import unittest
from pathlib import Path

from engine.compact import compact
from engine.oi_cadence import cadence
from engine.recorder import Recorder
from engine.replay import day_events, encode
from engine.retention import LocalTarget, S3Target, archive_day, run, sha256_file
from engine.store import DayStore

from .fixtures import EQ, FUT, IDX, Clock, frame, full_packet, index_packet, make_config

S = 1_000_000_000
MASTER = ("instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,"
          "instrument_type,segment,exchange\n"
          f"{FUT},48225,NIFTY26NOVFUT,NIFTY,0,2026-11-24,0,0.1,65,FUT,NFO-FUT,NFO\n"
          f"{IDX},1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
          f"{EQ},2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.1,1,EQ,NSE,NSE\n")


def record_day(root: Path, day: str, n=50, gap_after=None):
    """Writes a small synthetic session (fixture data, not market data)."""
    d = root / day
    store = DayStore(d)
    (d / "instruments.csv.gz").write_bytes(gzip.compress(MASTER.encode()))
    base = int(datetime.fromisoformat(f"{day}T09:15:00+05:30").timestamp())
    clock = Clock(t=base * S)
    shift = 0
    rec = Recorder(make_config(root), store, clock_ns=clock, disk_free=lambda: 10**12)
    rec.on_conn_event(0, "connect", {})
    for i in range(n):
        ex = base + 10 * i + shift  # from 09:15 IST, every 10 s; receive time tracks exchange time
        clock.t = ex * S + 50_000_000
        oi = 1000 + (i // 3)          # changes every 3rd packet -> every 30 s
        rec.on_message(0, frame(full_packet(token=FUT, ex_ts=ex, ltp=2450000 + i % 7, oi=oi, depth=[(i % 4, 1, 1)] * 10),
                                index_packet(ex_ts=ex, ltp=2440000 + i % 5),
                                full_packet(token=EQ, ex_ts=ex, ltp=130000 + i % 3, oi=0)), True)
        if i == 4:
            rec.on_message(0, frame(full_packet(token=FUT, ex_ts=ex - 20, ltp=1, oi=oi)), True)  # out-of-order
        if gap_after is not None and i == gap_after:
            rec.on_conn_event(0, "close", {})
            clock.t += 120 * S
            shift += 120
            rec.on_conn_event(0, "connect", {})
        rec.drain()
    rec.stop()
    store.close()
    return d


class TestCompaction(unittest.TestCase):
    def test_compacted_replay_identical_to_raw_buffer_and_sizes_reported(self):
        with tempfile.TemporaryDirectory() as td:
            d = record_day(Path(td), "2026-11-06")
            before = encode(day_events(d, "buffer"))
            rep = compact(d)
            self.assertTrue(all(rep["verified"].values()), rep["verified"])
            self.assertTrue(rep["buffer_deleted"])
            self.assertFalse((d / "buffer.sqlite").exists())
            self.assertFalse((d / "frames.bin").exists())
            self.assertEqual(encode(day_events(d, "auto")), before)  # auto -> parquet now
            for k in ("ticks", "depth", "oi_changes", "events", "gaps", "meta", "frames.bin"):
                self.assertIn(k, rep["before_bytes"])
            self.assertTrue((d / "parquet" / "ticks" / "family=NFO-FUT").is_dir())
            self.assertTrue((d / "parquet" / "ticks" / "family=INDICES").is_dir())
            print("\nfixture storage report:", json.dumps({k: rep[k] for k in
                  ("before_bytes", "A_parquet_bytes", "B_frames_zst_bytes", "replay")}))


class TestRetention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "data"
        self.arch = Path(self.tmp.name) / "archive"

    def tearDown(self):
        self.tmp.cleanup()

    def _days(self, n):
        for i in range(n):
            compact(record_day(self.root, f"2026-11-{i + 2:02d}", n=5))

    def test_archive_then_delete_only_with_verified_checksum(self):
        self._days(3)
        for day in ("2026-11-02", "2026-11-03"):
            (self.root / day / "options.sqlite").write_bytes(b"iv history")
        cfg = make_config(self.root, **{"retention.raw_sessions_local": 1})
        res = run(cfg, target=LocalTarget(self.arch))
        self.assertEqual(sorted(res), ["2026-11-02", "2026-11-03"])  # newest day stays local
        for day, files in res.items():
            for rel, outcome in files.items():
                self.assertEqual(outcome, "archived+verified+deleted")
                self.assertFalse((self.root / rel).exists())
                manifest = json.loads((self.root / day / "archived.json").read_text())
                self.assertEqual(sha256_file(self.arch / rel), manifest[rel]["sha256"])
            left = sorted(p.relative_to(self.root / day).as_posix() for p in (self.root / day).rglob("*"))
            self.assertEqual(left, ["archived.json", "options.sqlite"])    # D-74: only what past-day readers need
            self.assertTrue((self.arch / day / "instruments.csv.gz").exists())
        self.assertTrue((self.root / "2026-11-04" / "frames.bin.zst").exists())

    def test_archived_file_is_read_back_from_the_archive_verified(self):
        from engine.retention import CACHE, fetch
        self._days(2)
        run(make_config(self.root, **{"retention.raw_sessions_local": 1}), target=LocalTarget(self.arch))
        gone = self.root / "2026-11-02" / "instruments.csv.gz"
        self.assertFalse(gone.exists())
        got = fetch(gone, target=LocalTarget(self.arch))
        self.assertEqual(got, self.root / CACHE / "2026-11-02" / "instruments.csv.gz")
        self.assertEqual(got.read_bytes(), (self.arch / "2026-11-02" / "instruments.csv.gz").read_bytes())
        self.assertIsNone(fetch(self.root / "2026-11-02" / "never.sqlite", target=LocalTarget(self.arch)))
        (self.arch / "2026-11-02" / "frames.bin.zst").write_bytes(b"corrupted")   # archive copy no longer matches
        self.assertIsNone(fetch(self.root / "2026-11-02" / "frames.bin.zst", target=LocalTarget(self.arch)))
        self.assertFalse((self.root / CACHE / "2026-11-02" / "frames.bin.zst").exists())

    def test_gs_target_uses_the_gcs_endpoint_and_an_hmac_key(self):
        from unittest import mock
        from engine import retention as RT
        with mock.patch.dict("os.environ", {"GCS_HMAC_ACCESS_ID": "id", "GCS_HMAC_SECRET": "sec"}):
            t = RT.make_target("gs://engine-archive/nse")
        self.assertEqual((t.bucket, t.prefix, t.s3.meta.endpoint_url), ("engine-archive", "nse", RT.GCS_ENDPOINT))
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(RT.subprocess, "run") as run:
            run.return_value.returncode = 44                                 # no Keychain item
            with self.assertRaises(RuntimeError):
                RT.make_target("gs://engine-archive/nse")

    def test_mismatch_or_failure_never_deletes(self):
        self._days(1)
        d = self.root / "2026-11-02"
        before = sorted(p for p in d.rglob("*") if p.is_file())

        class Corrupting(LocalTarget):
            def put(self, src, rel):
                super().put(src, rel)
                with open(self.root / rel, "ab") as f:
                    f.write(b"x")

        class Failing(LocalTarget):
            def put(self, src, rel):
                raise OSError("drive unplugged")

        class FakeS3:  # returns a different object than was uploaded
            def upload_file(self, *a):
                pass

            def get_object(self, **k):
                import io
                return {"Body": io.BytesIO(b"not the file")}

        for tgt in (Corrupting(self.arch), Failing(self.arch), S3Target("s3://b/p", client=FakeS3())):
            out = archive_day(d, tgt)
            self.assertTrue(out and all(v.startswith("KEPT") for v in out.values()), out)
        self.assertEqual(sorted(p for p in d.rglob("*") if p.is_file()), before)

    def test_uncompacted_day_is_skipped(self):
        d = record_day(self.root, "2026-11-02", n=3)
        self.assertIn("_skipped", archive_day(d, LocalTarget(self.arch)))
        self.assertTrue((d / "buffer.sqlite").exists())


class TestOiCadence(unittest.TestCase):
    def test_intervals_from_change_log_excluding_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = make_config(root)
            d = record_day(root, "2026-11-06", n=30)
            c = cadence(d, cfg)
            self.assertEqual(set(c), {FUT})  # EQ has OI 0 throughout: baseline only, no change
            self.assertEqual((c[FUT]["median_s"], c[FUT]["p90_s"], c[FUT]["max_s"]), (30, 30, 30))
            d2 = record_day(root, "2026-11-07", n=30, gap_after=10)
            c2 = cadence(d2, cfg)
            self.assertEqual(c[FUT]["intervals"], 8)
            self.assertEqual(c2[FUT]["intervals"], 7)  # the interval spanning the 120 s disconnect is excluded
            self.assertEqual(c2[FUT]["max_s"], 30)
            # Phase 4: COMBINED:<underlying> = the union of its futures' change times (one future here)
            self.assertEqual(cadence(d, cfg, {FUT: "X"})["COMBINED:X"], c[FUT])
            compact(d)
            self.assertEqual(cadence(d, cfg), c)  # same answer from parquet


if __name__ == "__main__":
    unittest.main()


class FakeSend:
    """Stands in for ntfy: tests must never push to the owner's phone."""

    def __init__(self, log):
        self.log = log

    def __call__(self, title, message):
        self.log.append(title)
        return {"success": True}


class TestAlerts(unittest.TestCase):
    def test_alert_once_per_day_and_failed_send_is_retried(self):
        from engine.alerts import alert_once
        with tempfile.TemporaryDirectory() as td:
            sent = []
            self.assertTrue(alert_once(Path(td), "k", "T", "m", send=FakeSend(sent)))
            self.assertFalse(alert_once(Path(td), "k", "T", "m", send=FakeSend(sent)))
            self.assertEqual(sent, ["T"])
            boom = lambda *a: (_ for _ in ()).throw(OSError("offline"))  # noqa: E731
            self.assertFalse(alert_once(Path(td), "k2", "T2", "m", send=boom))   # never raises
            self.assertTrue(alert_once(Path(td), "k2", "T2", "m", send=FakeSend(sent)))  # not marked sent

    def test_unclean_stop_detected_only_without_shutdown(self):
        import sqlite3
        from engine.recorder import last_run_end
        with tempfile.TemporaryDirectory() as td:
            d = record_day(Path(td), "2026-11-06", n=3)       # fixture run logs connect, no shutdown
            c = sqlite3.connect(d / "buffer.sqlite")
            last, unclean = last_run_end(c)
            self.assertEqual(unclean, last)
            c.execute("INSERT INTO events VALUES (?, 0, 'shutdown', '{}')", (last + 1,))
            self.assertEqual(last_run_end(c)[1], None)
            c.close()

    def test_eod_day_checks(self):
        from engine.eod import check_today
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = make_config(root)
            sent = []
            thu = datetime(2026, 11, 5, 15, 50, tzinfo=ZoneInfo("Asia/Kolkata"))
            self.assertEqual(check_today(cfg, thu, FakeSend(sent)), ["no_data"])
            self.assertEqual(check_today(cfg, thu.replace(day=7), FakeSend(sent)), [])   # Saturday
            record_day(root, "2026-11-05", n=3)
            self.assertEqual(check_today(cfg, thu, FakeSend(sent)), ["unclean"])
            self.assertEqual(sent, ["Engine: NOTHING recorded today", "Engine recorder DIED and did not restart"])

    def test_eod_no_data_alert_suppressed_only_on_verified_holiday(self):
        from engine.eod import check_today
        from engine.universe import Registry
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(Path(td))
            hol = datetime(2026, 11, 24, 15, 50, tzinfo=ZoneInfo("Asia/Kolkata"))  # Tue, NSE/FAOP/71777
            sent = []
            self.assertEqual(check_today(cfg, hol, FakeSend(sent)), ["no_data"])  # circulars not re-verified today
            reg = Registry(cfg)
            for c in cfg.get("restrictions.holiday_circulars"):
                reg.log_fetch(hol.date(), f"holiday:{c['ref']}", c["url"], "t", True, c["sha256"], "ok")
            reg.close()
            self.assertEqual(check_today(cfg, hol.replace(day=23), FakeSend([])), ["no_data"])  # trading day
            self.assertEqual(check_today(cfg, hol, FakeSend(sent)), [])
            self.assertEqual(sent, ["Engine: NOTHING recorded today"])


class TestAutomation(unittest.TestCase):
    def test_restart_records_gap_and_uses_new_connection_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = record_day(root, "2026-11-06", n=5)        # first process: conn 0
            store = DayStore(d)
            clock = Clock(t=2 * 10**18)
            rec = Recorder(make_config(root), store, clock_ns=clock, disk_free=lambda: 10**12)
            self.assertEqual(rec.resume(), 1)
            rec.stop()
            store.close()
            import sqlite3
            c = sqlite3.connect(d / "buffer.sqlite")
            kinds = [k for k, in c.execute("SELECT kind FROM gaps")]
            c.close()
            self.assertEqual(kinds, ["restart"])

    def test_single_recorder_lock_and_eod_refuses_while_held(self):
        from engine.eod import run as eod_run
        from engine.recorder import acquire_lock
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            held = acquire_lock(root)
            self.assertIsNotNone(held)
            self.assertIsNone(acquire_lock(root))
            self.assertIn("error", eod_run(make_config(root), oi_out=root / "oi.md"))
            held.close()
            self.assertIsNotNone(acquire_lock(root))

    def test_eod_compacts_writes_cadence_and_runs_retention(self):
        from engine.eod import run as eod_run
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data"
            for day in ("2026-11-05", "2026-11-06"):
                record_day(root, day, n=30)
            cfg = make_config(root, **{"retention.raw_sessions_local": 1,
                                       "retention.archive_target": str(Path(td) / "arch")})
            sent = []
            friday = datetime(2026, 11, 6, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))   # pinned: weekend runs send no health alerts (Q-9-24)
            out = eod_run(cfg, oi_out=Path(td) / "oi.md", send=FakeSend(sent), now=friday)
            self.assertEqual(sorted(out["days"]), ["2026-11-05", "2026-11-06"])
            self.assertTrue(all(all(r["verified"].values()) and r["buffer_deleted"] for r in out["days"].values()))
            self.assertIn("NFO:NIFTY26NOVFUT", (Path(td) / "oi.md").read_text())
            self.assertEqual(set(out["retention"]), {"2026-11-05"})
            self.assertTrue((root / "eod_last.json").exists())
            self.assertEqual(sent, ["Engine recorder DIED and did not restart"])  # fixture day has no shutdown event
            again = eod_run(cfg, oi_out=Path(td) / "oi.md", send=FakeSend(sent), now=friday)  # idempotent second run
            self.assertEqual(again["days"], {})

    def test_failed_buffer_step_holds_compaction_and_next_eod_reruns_it(self):
        from unittest import mock
        from engine import eod
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data"
            for day in ("2026-11-05", "2026-11-06"):
                record_day(root, day, n=30)
            cfg = make_config(root, **{"retention.archive_target": str(Path(td) / "arch")})
            friday = datetime(2026, 11, 6, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
            timeout = lambda days: {"2026-11-05": {"signals": "done"},
                                    "2026-11-06": {"chain": "ok", "signals": "error: timeout after 1800 s",
                                                   "paper": "skipped: signals not done", "dashboard": "ok"}}
            out = eod.run(cfg, oi_out=Path(td) / "oi.md", send=FakeSend([]), now=friday, before_compaction=timeout)
            self.assertTrue(eod.failed(out))
            self.assertIn("signals failed", out["days"]["2026-11-06"]["compaction_held"])
            self.assertTrue((root / "2026-11-06" / "buffer.sqlite").exists())        # kept for a re-run
            self.assertTrue(out["days"]["2026-11-05"]["buffer_deleted"])              # the healthy day still compacts
            # a whole-chain crash holds every day
            boom = lambda days: (_ for _ in ()).throw(RuntimeError("oom"))
            out = eod.run(cfg, oi_out=Path(td) / "oi.md", send=FakeSend([]), now=friday, before_compaction=boom)
            self.assertIn("oom", out["days"]["2026-11-06"]["compaction_held"])
            self.assertTrue((root / "2026-11-06" / "buffer.sqlite").exists())
            # the next evening re-runs the held day (the intraday job's run row would otherwise mark it done)
            with mock.patch.object(eod, "dashboard_chain", return_value={}) as chain:
                eod._chain_then_trader_test(sorted(p for p in root.iterdir() if p.is_dir()), "2026-11-09")
            self.assertEqual(chain.call_args.kwargs["rerun"], {"2026-11-09", "2026-11-06"})
            out = eod.run(cfg, oi_out=Path(td) / "oi.md", send=FakeSend([]), now=friday,
                          before_compaction=lambda days: {"2026-11-06": {"signals": "ok", "paper": "ok"}})
            self.assertTrue(out["days"]["2026-11-06"]["buffer_deleted"])

    def test_archive_failure_is_a_failed_eod_with_one_alert_and_the_summary_written(self):
        from unittest import mock
        from engine import eod
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data"
            for day in ("2026-11-05", "2026-11-06"):
                record_day(root, day, n=30)
            blocker = Path(td) / "not-a-dir"
            blocker.write_text("x")   # the archive root is a file: every upload fails, so every file is KEPT
            cfg = make_config(root, **{"retention.raw_sessions_local": 1, "retention.archive_target": str(blocker)})
            sent, friday = [], datetime(2026, 11, 6, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
            out = eod.run(cfg, oi_out=Path(td) / "oi.md", send=FakeSend(sent), now=friday)
            self.assertTrue(eod.failed(out))
            self.assertTrue((root / "2026-11-05" / "frames.bin.zst").exists())   # nothing deleted
            self.assertIn("Engine archive to cloud FAILED: files kept on the Mac", sent)
            with mock.patch.object(eod, "retention_run", side_effect=RuntimeError("no GCS HMAC key")):
                out = eod.run(cfg, oi_out=Path(td) / "oi.md", send=FakeSend(sent), now=friday)
            self.assertEqual(out["retention"], {"error": "RuntimeError('no GCS HMAC key')"})
            self.assertTrue(eod.failed(out))
            self.assertIn("no GCS HMAC key", (root / "eod_last.json").read_text())


class TestStreamingCompaction(unittest.TestCase):
    """Q-6-5: compaction must verify every event with bounded memory and still catch any difference."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_never_builds_a_full_event_list(self):
        from unittest import mock
        from engine import compact as C, replay as R, store
        d = record_day(self.root, "2026-11-06")
        boom = mock.Mock(side_effect=AssertionError("full event list built"))
        with mock.patch.object(R, "frames_events", boom), mock.patch.object(R, "parquet_events", boom), \
                mock.patch.object(R, "day_events", boom), mock.patch.object(store, "buffer_events", boom), \
                mock.patch.object(C, "BATCH_ROWS", 7):                     # many batches even on a small fixture
            rep = C.compact(d, keep_buffer=True)
        self.assertTrue(all(rep["verified"].values()), rep)
        self.assertEqual(rep["replay"]["events_buffer"], rep["replay"]["events_parquet"])
        boom.assert_not_called()

    def _tamper(self, d, change):
        import pyarrow.parquet as pq
        f = sorted((d / "parquet" / "ticks").rglob("*.parquet"))[0]
        rows = pq.read_table(f).to_pylist()
        rows = change(rows)
        import pyarrow as pa
        pq.write_table(pa.Table.from_pylist(rows, schema=pq.read_schema(f)), f)

    def test_one_changed_value_or_missing_row_is_caught(self):
        from engine import compact as C
        for name, change in (("value", lambda r: [dict(r[0], ltp=(r[0]["ltp"] or 0) + 1)] + r[1:]),
                             ("missing row", lambda r: r[1:]),
                             ("swapped order", lambda r: [r[1], r[0]] + r[2:])):
            with self.subTest(name), tempfile.TemporaryDirectory() as td:
                d = record_day(Path(td), "2026-11-06")
                C.write_parquet(d)
                self._tamper(d, change)
                same, info = C.verify_parquet(d, C._families(d))
                self.assertFalse(same, name)
                self.assertIn("ticks", info["reason"])

    def test_corrupt_frames_archive_keeps_the_buffer(self):
        from unittest import mock
        import pyarrow as pa
        from engine import compact as C
        d = record_day(self.root, "2026-11-06")

        def bad_zst(day_dir):                       # same length, one byte flipped
            raw = bytearray((day_dir / "frames.bin").read_bytes())
            raw[len(raw) // 2] ^= 0xFF
            (day_dir / "frames.bin.zst").write_bytes(len(raw).to_bytes(8, "little") + pa.compress(bytes(raw), codec="zstd", asbytes=True))
            return 0
        with mock.patch.object(C, "write_frames_zst", bad_zst):
            rep = C.compact(d)
        self.assertFalse(rep["verified"]["frames_zst_roundtrip"])
        self.assertFalse(rep["buffer_deleted"])
        self.assertTrue((d / "buffer.sqlite").exists() and (d / "frames.bin").exists())
