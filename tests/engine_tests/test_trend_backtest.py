import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from trend_backtest import exit_of, signal  # noqa: E402

from engine.candles import IST


def day(prices, vol=100):
    """5-minute candles from 09:15: prices = [(o, h, l, c), ...]."""
    t0 = datetime(2026, 11, 9, 9, 15, tzinfo=IST)
    return [(t0 + timedelta(minutes=5 * i), o, h, l, c, vol) for i, (o, h, l, c) in enumerate(prices)]


OR = [(100, 101, 99.5, 100.5)] * 3                       # opening range 99.5 - 101 (1.5 %)
UP_NIFTY = day([(200, 201, 199, 200.5)] + [(201, 202, 200, 201)] * 70)
DOWN_NIFTY = day([(200, 201, 199, 199.5)] + [(199, 199.5, 198, 199)] * 70)


class Rule(unittest.TestCase):
    def test_call_on_a_breakout_with_the_market(self):
        s = signal(day(OR + [(100.5, 101.6, 100.4, 101.5)]), UP_NIFTY)
        self.assertEqual((s["side"], s["entry"], s["stop"], s["target"]), (1, 101.5, 99.5, 105.5))
        self.assertEqual(s["t"].strftime("%H:%M"), "09:35")

    def test_no_call_against_the_market_and_no_trade_on_a_wide_range(self):
        self.assertIsNone(signal(day(OR + [(100.5, 101.6, 100.4, 101.5)]), DOWN_NIFTY))
        self.assertIsNone(signal(day([(100, 103, 99, 102)] * 3 + [(102, 104, 101.9, 103.5)]), UP_NIFTY))

    def test_exit_stop_first_when_one_candle_hits_both(self):
        cs = day(OR + [(100.5, 101.6, 100.4, 101.5), (101.5, 106, 99, 102)])
        s = signal(cs, UP_NIFTY)
        self.assertEqual(exit_of(s, cs)[1:], (99.5, "STOP"))

    def test_exit_at_target_then_time(self):
        cs = day(OR + [(100.5, 101.6, 100.4, 101.5), (101.5, 105.6, 101.4, 105)])
        self.assertEqual(exit_of(signal(cs, UP_NIFTY), cs)[1:], (105.5, "TARGET"))
        flat = day(OR + [(100.5, 101.6, 100.4, 101.5)] + [(101.5, 102, 101, 101.8)] * 70)
        t, px, why = exit_of(signal(flat, UP_NIFTY), flat)
        self.assertEqual((t.strftime("%H:%M"), px, why), ("15:10", 101.8, "TIME_15:10"))


if __name__ == "__main__":
    unittest.main()
