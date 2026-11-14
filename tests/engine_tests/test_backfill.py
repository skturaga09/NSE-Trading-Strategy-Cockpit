"""Phase 3: historical backfill (token bucket, range cap, separate labelled store) and baselines. No network."""

import json
import sqlite3
import unittest
from datetime import date
from pathlib import Path

from engine.backfill import TokenBucket, backfill, window
from engine.baselines import oi_change_distribution, percentile_rank, relative_volume, volume_baseline
from engine.candles import Unavailable

from .fixtures import make_config

AS_OF = date(2026, 11, 6)


def rows(day: str, vols, ois=None):
    return [[f"{day}T09:{15 + i:02d}:00+0530", 1, 1, 1, 1, v] + ([ois[i]] if ois else []) for i, v in enumerate(vols)]


class FakeClock:
    def __init__(self):
        self.t, self.calls = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def mark(self):
        self.calls.append(self.t)


class FakeSession:
    def __init__(self, data, fail=()):
        self.data, self.fail, self.calls = data, set(fail), []

    def historical(self, token, interval, start, end, oi):
        self.calls.append((token, interval, start, end, oi))
        if token in self.fail:
            raise RuntimeError("HTTP 500")
        return [r if oi else r[:6] for r in self.data[token]]


class TestBackfill(unittest.TestCase):
    def test_token_bucket_never_exceeds_rate(self):
        c = FakeClock()
        b = TokenBucket(3, clock=c, sleep=c.sleep)
        for _ in range(10):
            b.take()
            c.mark()
        self.assertAlmostEqual(c.calls[-1] - c.calls[0], 3.0)        # 9 intervals at 3/s
        self.assertTrue(all(b2 - a >= 1 / 3 - 1e-9 for a, b2 in zip(c.calls, c.calls[1:])))

    def test_window_respects_the_measured_range_cap(self):
        cfg = make_config(Path("/tmp"))
        self.assertEqual(window(cfg, AS_OF), ("2026-09-29 09:00:00", "2026-11-05 23:59:59"))   # 38 days, cap 60
        with self.assertRaises(ValueError):
            window(make_config(Path("/tmp"), **{"baselines.sessions": 50}), AS_OF)

    def test_backfill_labels_source_records_failures_and_builds_baselines(self):
        cfg = make_config(Path("/tmp"), **{"baselines.sessions": 2, "baselines.oi_change_windows_min": [1, 5]})
        fut = rows("2026-11-03", [10, 20], [100, 110]) + rows("2026-11-04", [30, 40], [200, 210]) \
            + rows("2026-11-05", [50, 60], [300, 330]) + rows("2026-11-06", [999, 999], [1, 1])  # as_of: excluded
        s = FakeSession({1: fut, 2: rows("2026-11-05", [7, 8])}, fail={3})
        db = sqlite3.connect(":memory:")
        c = FakeClock()
        res = backfill(cfg, s, AS_OF, {1: "FUT", 2: "EQ", 3: "FUT"}, TokenBucket(3, c, c.sleep), db)
        self.assertEqual((res["ok"], list(res["failed"])), (2, [3]))
        self.assertEqual([x[4] for x in s.calls], [True, False, True])      # oi=1 for NFO futures only
        self.assertEqual(db.execute("SELECT DISTINCT source FROM hist_candles").fetchall(), [("HISTORICAL_API",)])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM hist_candles WHERE oi IS NOT NULL AND token=2").fetchone(), (0,))
        vb = json.loads(db.execute("SELECT payload FROM baselines WHERE token=1 AND kind='volume_by_minute'").fetchone()[0])
        self.assertEqual(vb["sessions"], ["2026-11-04", "2026-11-05"])      # last N=2 sessions before as_of
        self.assertEqual(vb["minutes"], {"09:15": [40, 2], "09:16": [50, 2]})
        od = json.loads(db.execute("SELECT payload FROM baselines WHERE token=1 AND kind='oi_change_pct'").fetchone()[0])
        self.assertEqual(od["windows"]["1"], [5.0, 10.0])                   # 200->210, 300->330
        self.assertEqual(od["windows"]["5"], [])
        self.assertIsNone(db.execute("SELECT 1 FROM baselines WHERE token=3").fetchone())

    def test_readers(self):
        vb = volume_baseline(rows("2026-11-05", [10, 0]), AS_OF, 20)
        self.assertEqual(relative_volume(25, "09:15", vb), 2.5)
        self.assertIsInstance(relative_volume(5, "09:16", vb), Unavailable)    # zero baseline: no ratio
        self.assertIsInstance(relative_volume(Unavailable("gap"), "09:15", vb), Unavailable)
        self.assertEqual(percentile_rank([1.0, 2.0, 3.0, 4.0], 2.5), 0.5)
        self.assertIsInstance(percentile_rank([], 1.0), Unavailable)
        od = oi_change_distribution(rows("2026-11-05", [1, 1, 1], [0, 100, 120]), AS_OF, 20, [1])
        self.assertEqual(od["windows"]["1"], [20.0])                          # OI 0 skipped (Q-HIST-5)


if __name__ == "__main__":
    unittest.main()
