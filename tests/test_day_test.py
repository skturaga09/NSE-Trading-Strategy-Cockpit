#!/usr/bin/env python3
"""Day-clustered significance used by the swing journal + recommendation ledger verdicts."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.swing_journal import day_test

HIT = lambda r: r["w"]


def rows(day_hits):
    return [{"d": f"D{i}", "w": w} for i, hits in enumerate(day_hits) for w in hits]


class TestDayTest(unittest.TestCase):
    def test_one_big_day_is_not_an_edge(self):
        # 12/12 wins on one sell-off day + 25 coin-flip days → per-signal looks great, per-day doesn't
        t = day_test(rows([[1.0] * 12] + [[1.0, 0.0]] * 25), "d", HIT, 0.5)
        self.assertEqual(t["days"], 26)
        self.assertFalse(t["significant"])

    def test_consistent_edge_across_days(self):
        t = day_test(rows([[1.0, 1.0, 0.0], [1.0, 1.0, 1.0]] * 12), "d", HIT, 0.5)
        self.assertTrue(t["significant"])
        self.assertGreater(t["mean"], 0.5)

    def test_too_few_days(self):
        self.assertFalse(day_test(rows([[1.0] * 20] * 3), "d", HIT, 0.5)["significant"])

    def test_skips_none(self):
        t = day_test([{"d": "a", "w": None}, {"d": "b", "w": 1.0}], "d", HIT, 0.5)
        self.assertEqual(t["days"], 1)


if __name__ == "__main__":
    unittest.main()
