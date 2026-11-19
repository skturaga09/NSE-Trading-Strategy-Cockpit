import unittest
from unittest import mock

from dashboard import target_calc as TC


class Estimate(unittest.TestCase):
    def test_call_premium_at_target_and_reward_risk_against_the_stop(self):
        e = TC.estimate(spot=1118, target=1140, K=1100, T=10 / 365, premium=30.0, is_call=True, lot=750, stop_line=1110.67)
        self.assertAlmostEqual(TC._bs(1118, 1100, 10 / 365, e["iv_pct"] / 100, True), 30.0, delta=0.05)   # fitted to the live price
        self.assertTrue(0.5 < e["delta"] < 0.8)                    # 1 strike in the money
        self.assertGreater(e["est_premium"], e["at_expiry"])       # time value left before expiry
        self.assertEqual(e["at_expiry"], 40)                       # 1140 - 1100
        self.assertTrue(e["premium_at_stop"] < 30.0 < e["est_premium"])
        self.assertAlmostEqual(e["gain_per_lot"], (e["est_premium"] - 30.0) * 750, delta=0.005 * 750 + 1)   # premium shown rounded to the paisa
        self.assertEqual(e["reward_risk"], round(e["gain_per_lot"] / e["loss_per_lot"], 1))

    def test_put_gains_when_the_stock_falls_and_no_stop_means_no_risk_figures(self):
        e = TC.estimate(spot=1118, target=1090, K=1140, T=10 / 365, premium=32.0, is_call=False, lot=750)
        self.assertTrue(-0.8 < e["delta"] < -0.5)
        self.assertGreater(e["gain_per_lot"], 0)
        self.assertEqual(e["at_expiry"], 50)                       # 1140 - 1090
        self.assertNotIn("reward_risk", e)


NFO = [{"tradingsymbol": f"ATHERENERG26NOV{k}{t}", "name": "ATHERENERG", "strike": str(k), "instrument_type": t,
        "expiry": "2026-11-23", "lot_size": "375", "segment": "NFO-OPT"} for k in (1900, 1920, 1940, 1960, 1980) for t in ("CE", "PE")]


class Forward(unittest.TestCase):
    def run_forward(self, symbol, target, net=()):
        def get(url, params=None, **kw):
            if url.endswith("/portfolio/positions"):
                data = {"net": list(net)}
            else:
                key = params[0][1]
                data = {key: {"last_price": 1945.0} if key.startswith("NSE:") else
                        {"last_price": 48.5, "depth": {"buy": [{"price": 48.4}], "sell": [{"price": 48.6}]}}}
            return mock.Mock(json=lambda: {"status": "success", "data": data})
        rows = [{"symbol": "ATHERENERG", "trend": "UP", "line": 1926.81}]
        with mock.patch("dashboard.fno_scanner.fno_universe", return_value=["ATHERENERG"]), \
                mock.patch.object(TC, "_instruments", return_value=NFO), mock.patch.object(TC, "_connected", return_value=True), \
                mock.patch.object(TC, "_headers", return_value={}), mock.patch.object(TC.requests, "get", side_effect=get), \
                mock.patch("dashboard.supertrend.board", return_value={"rows": rows}):
            return TC.forward(symbol, target)

    def test_your_held_option_is_used_with_your_buy_price_and_qty(self):
        mine = [{"tradingsymbol": "ATHERENERG26NOV1940CE", "quantity": 375, "average_price": 45.35}]
        for typed in ("ATHERENERG", "atherenerg26nov1940ce"):          # the stock name or the option name
            r = self.run_forward(typed, 1988, net=mine)
            self.assertEqual((r["option"], r["which"], r["qty"], r["avg"]), ("ATHERENERG26NOV1940CE", "yours", 375, 45.35))
            self.assertEqual(r["pnl_now"], round((48.5 - 45.35) * 375))                   # mid of 48.4 / 48.6
            self.assertEqual(r["pnl_at_target"], round((r["est_premium"] - 45.35) * 375))
            self.assertEqual(r["stop_line"], 1926.81)                                    # a call, with the UP trend
        down = self.run_forward("ATHERENERG", 1900, net=mine)          # a fall prices YOUR call (a loss), not a new put
        self.assertEqual(down["option"], "ATHERENERG26NOV1940CE")
        self.assertLess(down["pnl_at_target"], 0)

    def test_without_a_position_a_typed_option_or_the_rules_pick_is_priced(self):
        r = self.run_forward("ATHERENERG26NOV1960PE", 1900)
        self.assertEqual((r["option"], r["which"], r["stop_line"]), ("ATHERENERG26NOV1960PE", "typed", None))   # put vs UP trend
        self.assertNotIn("pnl_now", r)
        r = self.run_forward("ATHERENERG", 1988)                       # up: 1 strike in the money call
        self.assertEqual((r["option"], r["which"]), ("ATHERENERG26NOV1960CE", "rules"))

    def test_bad_input_is_refused(self):
        self.assertEqual(self.run_forward("XYZ", 10), {"error": "XYZ is not an F&O stock, index or option"})
        self.assertEqual(self.run_forward("ATHERENERG", 0), {"error": "enter a target price above 0"})


if __name__ == "__main__":
    unittest.main()
