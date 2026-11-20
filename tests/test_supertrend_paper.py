"""Live paper trading: a signal becomes a paper order and fill, the exit rule sells it, net P&L is booked. Kite mocked."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import supertrend_paper as PP  # noqa: E402
from dashboard import supertrend_trades as T  # noqa: E402
from tests.test_supertrend_trades import MASTER, NOW, quote_get, row  # noqa: E402


class Paper(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.p = [mock.patch.object(PP, "STATE", Path(d) / "paper.json"), mock.patch.object(PP, "_costs", return_value=40.0),
                  mock.patch.object(PP, "STRONG_STATE", Path(d) / "strong.json"),
                  mock.patch.object(PP, "RULES_STATE", Path(d) / "rules.json"),
                  mock.patch("dashboard.option_chain._instruments", return_value=MASTER),
                  mock.patch("dashboard.option_chain.ensure_fresh_config"), mock.patch("dashboard.app.KITE_CONFIG", {"api_key": "k"})]
        for x in self.p:
            x.start()
        self.sent = []

    def tearDown(self):
        for x in self.p:
            x.stop()

    def minute(self, rows, quotes, at):
        get = quote_get(quotes, {})                       # no account paths: paper mode must not read the Kite account
        with mock.patch.object(T, "_get", side_effect=get), mock.patch.object(T, "board", return_value={"rows": rows, "bar": "x"}):
            return PP.step(at, notify=lambda title, *a, **k: self.sent.append(title))

    def test_signal_to_order_to_exit_to_pnl(self):
        up = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        out = self.minute(up, {"NFO:PNB26NOV128CE": 3.6, "NSE:PNB": 126.3}, NOW)
        self.assertEqual(out["bought"], ["PNB26NOV128CE"])
        st = PP.load()
        self.assertEqual(st["orders"][0]["transaction_type"], "BUY")                     # the exact order auto mode would POST
        self.assertEqual((st["open"][0]["qty"], st["open"][0]["entry"]), (500, 3.6))     # bought at the ask; 1 lot although the budget fits 18
        self.assertAlmostEqual(st["cash"], 100_000 - 3.6 * 500)

        out = self.minute(up, {"NFO:PNB26NOV128CE": 3.6, "NSE:PNB": 126.3}, NOW.replace(minute=1))
        self.assertEqual(out["bought"], [])                                              # same signal never bought twice

        down = [row("PNB", "DOWN", "2026-11-16T10:05:00+05:30", 127.0, close=123.9)]
        out = self.minute(down, {"NFO:PNB26NOV128CE": 4.4, "NSE:PNB": 123.9}, NOW.replace(minute=15))
        self.assertEqual(out["sold"], ["PNB26NOV128CE"])
        c = PP.load()["closed"][0]
        self.assertAlmostEqual(c["gross"], round((4.4 * 0.99 - 3.6) * 500, 2), places=0)
        self.assertEqual(c["net"], round(c["gross"] - 40.0, 2))
        self.assertEqual(PP.load()["orders"][-1]["transaction_type"], "SELL")
        self.assertEqual(len(self.sent), 2)

    def test_shadow_book_holds_through_a_line_touch_and_sells_on_the_closed_candle_flip(self):
        up = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        self.minute(up, {"NFO:PNB26NOV128CE": 3.6, "NSE:PNB": 126.3}, NOW)
        self.assertEqual(len(PP.load()["shadow"]["open"]), 1)                            # every buy is mirrored
        out = self.minute(up, {"NFO:PNB26NOV128CE": 3.0, "NSE:PNB": 124.0}, NOW.replace(minute=5))   # touch, no flip
        st = PP.load()
        self.assertEqual((out["sold"], len(st["shadow"]["open"]), st["shadow"]["closed"]), (["PNB26NOV128CE"], 1, []))
        down = [row("PNB", "DOWN", "2026-11-16T10:05:00+05:30", 125.0, close=123.5)]
        out = self.minute(down, {"NFO:PNB26NOV128CE": 2.9, "NSE:PNB": 123.5}, NOW.replace(minute=10))
        sh = PP.load()["shadow"]
        self.assertEqual((out["shadow_sold"], sh["open"]), (["PNB26NOV128CE"], []))
        self.assertIn("turned DOWN", sh["closed"][0]["exit_why"])
        self.assertEqual(sh["closed"][0]["exit"], round(2.9 * 0.99, 2))
        self.assertEqual(PP.load()["cash"], st["cash"])                                  # shadow never moves main cash

    def test_paper_sells_on_the_trailing_stop_after_a_run_up(self):
        up = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        self.minute(up, {"NFO:PNB26NOV128CE": 3.6, "NSE:PNB": 126.3}, NOW)
        self.minute(up, {"NFO:PNB26NOV128CE": 6.0, "NSE:PNB": 130.0}, NOW.replace(minute=5))
        self.assertEqual(PP.load()["open"][0]["peak"], 6.0)
        out = self.minute(up, {"NFO:PNB26NOV128CE": 4.4, "NSE:PNB": 127.0}, NOW.replace(minute=6))  # trend still UP
        c = PP.load()["closed"][0]
        self.assertEqual(out["sold"], ["PNB26NOV128CE"])
        self.assertIn("trailing stop", c["exit_why"])
        self.assertGreater(c["net"], 0)                                   # the stop kept part of the gain
        self.assertEqual(out["shadow_sold"], ["PNB26NOV128CE"])           # same stop in the shadow book

    def test_strong_book_buys_only_strong_flips_on_its_own_cash_and_never_alerts(self):
        weak = {**row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3), "since_strength": 1.2}
        strong = {**row("TCS", "DOWN", "2026-11-16T09:45:00+05:30", 2470, close=2455), "since_strength": 2.4}
        q = {"NFO:PNB26NOV128CE": 3.6, "NFO:TCS26NOV2400PE": 100, "NSE:PNB": 126.3, "NSE:TCS": 2455}
        out = self.minute([weak, strong], q, NOW)
        self.assertEqual(sorted(out["bought"]), ["PNB26NOV128CE", "TCS26NOV2400PE"])         # main book: unchanged rules
        self.assertEqual(out["strong"]["bought"], ["TCS26NOV2400PE"])
        s = PP.load(PP.STRONG_STATE)
        self.assertEqual((len(s["open"]), s["cash"], "shadow" in s), (1, 100_000 - 100 * 175, False))
        self.assertEqual(len(self.sent), 2)                                                   # alerts: main book only
        out = self.minute([weak, strong], q, NOW.replace(minute=1))
        self.assertEqual(out["strong"]["bought"], [])                                         # never the same signal twice

    def _two_losses(self, day_open):
        losses = [{"option": "X", "entry_at": NOW.isoformat(), "exit_at": NOW.isoformat(), "net": -100.0},
                  {"option": "Y", "entry_at": NOW.isoformat(), "exit_at": NOW.isoformat(), "net": -100.0}]
        for path in (PP.STATE, PP.RULES_STATE):
            st = PP.load()
            st.update(day=NOW.date().isoformat(), keys=[], day_open=day_open, closed=losses)
            path.write_text(__import__("json").dumps(st))

    def test_rules_book_stops_after_two_losses_main_book_does_not(self):
        self._two_losses(50_000.0)                                             # budget fine: only the 2-losses rule bites
        up = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        out = self.minute(up, {"NFO:PNB26NOV128CE": 3.6}, NOW)
        self.assertEqual(out["rules"]["bought"], [])
        self.assertEqual(out["bought"], ["PNB26NOV128CE"])
        self.assertEqual(len(self.sent), 1)                                    # alerts: main book only

    def test_main_book_buys_past_the_day_loss_budget_rules_book_does_not(self):
        self._two_losses(120_000.0)                                            # down past 10 % of the morning balance
        up = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        out = self.minute(up, {"NFO:PNB26NOV128CE": 3.6}, NOW)
        self.assertEqual(out["rules"]["bought"], [])
        st = PP.load()
        self.assertEqual((out["bought"], st["open"][0]["qty"]), (["PNB26NOV128CE"], 500))   # still 1 lot

    def test_open_trade_keeps_the_systems_last_check_and_live_prices_are_cached(self):
        up = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        self.minute(up, {"NFO:PNB26NOV128CE": 3.6, "NSE:PNB": 126.3}, NOW)
        self.minute(up, {"NFO:PNB26NOV128CE": 3.8, "NSE:PNB": 126.5}, NOW.replace(minute=1))
        o = PP.load()["open"][0]
        self.assertEqual((o["stock"], o["line"], o["checked"][11:16]), (126.5, 124.1, "10:01"))
        self.assertIn("sell if the stock trades below", o["plan"])
        calls = []
        def get(path, params):
            calls.append(params)
            return {"NFO:PNB26NOV128CE": {"last_price": 3.9}, "NSE:PNB": {"last_price": 126.6}}
        PP._LIVE.update(at=0.0, syms=[], px={})
        with mock.patch.object(T, "_get", side_effect=get):
            a = PP.live_prices([PP.load()])
            b = PP.live_prices([PP.load()])                    # within 5 s: no second Kite call
        self.assertEqual((a["px"]["NFO:PNB26NOV128CE"], b, len(calls)), (3.9, a, 1))


if __name__ == "__main__":
    unittest.main()
