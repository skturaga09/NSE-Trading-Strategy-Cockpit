#!/usr/bin/env python3
"""Desk guard: the session discipline rules in exit_monitor.guard_breaches."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard.exit_monitor import guard_breaches

CFG = {"daily_loss_cap": 5000, "max_losers_per_day": 2, "max_open_positions": 2, "no_averaging_down": True}


def pos(sym, qty, pnl, m2m=None):
    return {"tradingsymbol": sym, "quantity": qty, "pnl": pnl, "m2m": pnl if m2m is None else m2m}


class TestDeskGuard(unittest.TestCase):
    def test_quiet_day(self):
        net = [pos("A", 50, 800)]
        self.assertEqual(guard_breaches(net, net, CFG, {"A": 50}), [])

    def test_loss_cap_and_losers(self):
        net = [pos("A", 0, -3000), pos("B", 0, -2500)]
        keys = [k for k, _, _ in guard_breaches(net, net, CFG, {})]
        self.assertEqual(keys, ["loss_cap", "losers"])

    def test_carry_pnl_not_counted_in_cap(self):
        # big lifetime loss, but today's m2m small → no cap breach
        net = [pos("A", 50, -9000, m2m=-200)]
        self.assertEqual(guard_breaches(net, [], CFG, {"A": 50}), [])

    def test_too_many_open(self):
        net = [pos("A", 1, 0), pos("B", 1, 0), pos("C", 1, 0)]
        self.assertEqual([k for k, _, _ in guard_breaches(net, [], CFG, {})], ["open3"])

    def test_averaging_down_only_on_loser(self):
        self.assertEqual(guard_breaches([pos("P", 260, -1000)], [], CFG, {"P": 130})[0][0], "avg:P:260")
        self.assertEqual(guard_breaches([pos("P", 260, 1000)], [], CFG, {"P": 130}), [])   # adding to a winner
        self.assertEqual(guard_breaches([pos("P", 65, -1000)], [], CFG, {"P": 130}), [])   # scaling out


if __name__ == "__main__":
    unittest.main()
