import unittest
from datetime import date, datetime
from unittest import mock

from engine import recorder as R
from engine.candles import IST


class HolidaySkip(unittest.TestCase):
    """2026-11-10 (Diwali-Balipratipada): the weekday launchd job started the recorder on a closed exchange."""

    def run_on(self, day: date):
        cfg = mock.Mock()
        cfg.get.return_value = [{"date": date(2026, 11, 10), "ref": "NSE/FAOP/71777", "title": "Diwali-Balipratipada"}]
        with mock.patch.object(R, "load_config", return_value=cfg), mock.patch.object(R, "datetime") as dt, \
                mock.patch.object(R, "acquire_lock", return_value=None) as lock:
            dt.now.return_value = datetime.combine(day, datetime.min.time(), IST).replace(hour=9)
            rc = R.main([])
        return rc, lock

    def test_holiday_exits_before_taking_the_lock(self):
        rc, lock = self.run_on(date(2026, 11, 10))
        self.assertEqual(rc, 0)
        lock.assert_not_called()

    def test_trading_day_goes_on(self):
        rc, lock = self.run_on(date(2026, 11, 11))
        self.assertEqual(rc, 0)          # the patched lock is held elsewhere -> exits after trying it
        lock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
