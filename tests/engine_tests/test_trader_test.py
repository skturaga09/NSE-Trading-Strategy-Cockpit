"""scripts/trader_test.py account view: a signal is taken only when it fits the owner's money rules at that moment."""

import importlib.util
import unittest
from pathlib import Path

from tests.engine_tests.test_paper import CFG

_spec = importlib.util.spec_from_file_location("trader_test", Path(__file__).resolve().parents[2] / "scripts" / "trader_test.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


def row(time, exit_time, net, symbol="X", entry=1000.0, qty=100):
    return {"day": "2026-11-06", "time": time, "exit_time": exit_time, "net": net, "gross": net, "costs": 0.0,
            "symbol": symbol, "entry": entry, "qty": qty, "result": "CLOSED"}


class Account(unittest.TestCase):
    def test_daily_cap_open_limit_and_margin_are_applied_in_time_order(self):
        cap = CFG.get("risk.max_daily_loss_inr")
        rows = [row("10:00", "10:30", -cap, "A"),                  # first loss reaches the daily cap at 10:30
                row("10:15", "11:00", 500.0, "B"),                 # entered while A is still open: allowed
                row("10:45", "11:30", 900.0, "C"),                 # after A closed at the cap: day stopped
                row("09:30", "09:45", 100.0, "BIG", entry=1e6)]    # margin far above the per-trade limit
        taken, notes = T.account_view(rows, CFG)
        self.assertEqual([r["symbol"] for r in taken], ["A", "B"])
        self.assertTrue(any("BIG" in n and "per-trade limit" in n for n in notes))
        self.assertTrue(any("C" in n and "day stopped" in n for n in notes))

    def test_open_position_limit(self):
        n = CFG.get("risk.max_open_positions")
        rows = [row(f"10:0{i}", "14:00", 10.0, f"S{i}") for i in range(n + 1)]
        taken, notes = T.account_view(rows, CFG)
        self.assertEqual(len(taken), n)
        self.assertIn("open-position limit", notes[0])


if __name__ == "__main__":
    unittest.main()
