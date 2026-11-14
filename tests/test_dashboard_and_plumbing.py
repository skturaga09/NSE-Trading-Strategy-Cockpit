#!/usr/bin/env python3
"""
Unit Tests for Zerodha Kite Trade Plumbing Inspector and Strategy Dashboard.
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "skills" / "options-strategy-advisor" / "scripts"))

import gzip
import tempfile

import dashboard.zerodha_plumbing as ZP
from dashboard.zerodha_plumbing import ZerodhaPlumbingInspector, LOT_SIZES, FREEZE_LIMITS

try:
    from black_scholes import OptionPricer, OptionType
    BLACK_SCHOLES_OK = True
except ImportError:
    BLACK_SCHOLES_OK = False


def write_master(root: Path, rows) -> None:
    """A minimal exchange instrument master (same columns the engine stores daily)."""
    d = root / "2026-11-06"
    d.mkdir(parents=True, exist_ok=True)
    head = "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
    body = "".join(f"{i},{i},{n}FUT,{n},0,{exp},0,0.05,{lot},FUT,NFO-FUT,NFO\n" for i, (n, exp, lot) in enumerate(rows, 1))
    (d / "instruments.csv.gz").write_bytes(gzip.compress((head + body).encode()))


class TestZerodhaPlumbingInspector(unittest.TestCase):

    def setUp(self):
        self.inspector = ZerodhaPlumbingInspector()
        self.td = tempfile.TemporaryDirectory()      # lot sizes come from a fixture master, never the live data dir
        write_master(Path(self.td.name), [("NIFTY", "2099-11-23", 65), ("NIFTY", "2099-12-29", 65),
                                          ("BANKNIFTY", "2099-11-23", 30)])
        self._root, ZP.MASTER_ROOT = ZP.MASTER_ROOT, Path(self.td.name)

    def tearDown(self):
        ZP.MASTER_ROOT = self._root
        ZP.refresh_lot_sizes()
        self.td.cleanup()

    def test_symbol_resolution(self):
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("RELIANCE.NS"), "RELIANCE")
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("^NSEI"), "NIFTY")
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("BANKNIFTY"), "BANKNIFTY")
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("tcs.bo"), "TCS")

    def test_lot_size_validation(self):
        # lot sizes come from the instrument master (NIFTY 65 in the fixture, as in the 2026-11-06 master)
        diag_nifty = ZerodhaPlumbingInspector.validate_lot_size("NIFTY", 130)
        self.assertEqual(diag_nifty.status, "PASSED")
        self.assertIn("instrument master", diag_nifty.details["source"])

        diag_bank = ZerodhaPlumbingInspector.validate_lot_size("BANKNIFTY", 60)  # 2 lots of 30
        self.assertEqual(diag_bank.status, "PASSED")

        # the old hardcoded 75 is not a NIFTY lot
        diag_invalid = ZerodhaPlumbingInspector.validate_lot_size("NIFTY", 75)
        self.assertEqual(diag_invalid.status, "FAILED")
        self.assertEqual(diag_invalid.details["recommended_quantity"], 130)

    def test_lot_size_unknown_without_a_master_is_a_warning_not_a_guess(self):
        ZP.MASTER_ROOT = Path(self.td.name) / "empty"
        diag = ZerodhaPlumbingInspector.validate_lot_size("FINNIFTY", 25)
        self.assertEqual((diag.status, diag.details["lot_size"]), ("WARNING", None))
        self.assertIn("UNKNOWN", diag.message)

    def test_fno_rates_come_from_the_verified_schedule(self):
        # verified-facts F-COST-2 (STT from 2026-04-01) and F-COST-3 (exchange charges)
        self.assertEqual((ZP.STT_RATES["FNO_FUTURES_SELL"], ZP.STT_RATES["FNO_OPTIONS_SELL"]), (0.0005, 0.0015))
        self.assertEqual((ZP.EXCHANGE_CHARGES_RATES["FNO_FUTURES"], ZP.EXCHANGE_CHARGES_RATES["FNO_OPTIONS"]), (1.83e-05, 0.0003553))

    def test_order_freeze_slicing(self):
        # Quantity within limit (150 NIFTY)
        diag_small, slices_small = ZerodhaPlumbingInspector.check_order_slicing("NIFTY", 150)
        self.assertEqual(diag_small.status, "PASSED")
        self.assertEqual(len(slices_small), 1)

        # Quantity exceeding freeze limit (2000 NIFTY > 1800 limit)
        diag_large, slices_large = ZerodhaPlumbingInspector.check_order_slicing("NIFTY", 2000)
        self.assertEqual(diag_large.status, "WARNING")
        self.assertEqual(len(slices_large), 2)
        self.assertEqual(slices_large[0]["quantity"], 1800)
        self.assertEqual(slices_large[1]["quantity"], 200)

    def test_trade_costs_calculation(self):
        # Equity Delivery Buy
        costs = ZerodhaPlumbingInspector.calculate_trade_costs(
            symbol="RELIANCE", transaction_type="BUY", product="CNC", quantity=100, price=2900.0
        )
        self.assertEqual(costs.brokerage, 0.0) # Zerodha CNC delivery is Rs 0 brokerage
        self.assertGreater(costs.stt, 0.0)
        self.assertGreater(costs.stamp_duty, 0.0)
        self.assertGreater(costs.gst, 0.0)
        self.assertGreater(costs.total_friction, 0.0)

        # Option Sell Premium
        opt_costs = ZerodhaPlumbingInspector.calculate_trade_costs(
            symbol="NIFTY", transaction_type="SELL", product="NRML", quantity=65, price=140.0, is_option=True
        )
        self.assertLessEqual(opt_costs.brokerage, 20.0)
        self.assertGreater(opt_costs.stt, 0.0)

    def test_order_safety_validation(self):
        # Option SL-M warning check
        diags = ZerodhaPlumbingInspector.validate_order_parameters(
            symbol="NIFTY", product="NRML", order_type="SL-M", transaction_type="BUY", quantity=65, price=140.0, trigger_price=130.0, is_option=True
        )
        warning_found = any(d.check_name == "Order Safety Check" and d.status == "WARNING" for d in diags)
        self.assertTrue(warning_found)

    def test_gtt_validation(self):
        # Valid LONG GTT (Last price 140, Target 195, Stop loss 95)
        diag_valid = ZerodhaPlumbingInspector.validate_gtt_params(
            last_price=140.0, target_price=195.0, stop_loss_price=95.0, transaction_type="BUY"
        )
        self.assertEqual(diag_valid.status, "PASSED")

        # Invalid Stop loss > last price
        diag_invalid_sl = ZerodhaPlumbingInspector.validate_gtt_params(
            last_price=140.0, target_price=195.0, stop_loss_price=150.0, transaction_type="BUY"
        )
        self.assertEqual(diag_invalid_sl.status, "FAILED")

    def test_full_trade_validation(self):
        result = self.inspector.run_full_trade_validation(
            symbol="NIFTY",
            product="NRML",
            order_type="LIMIT",
            transaction_type="BUY",
            quantity=65,                # one NIFTY lot (fixture master)
            price=140.0,
            stop_loss_price=95.0,
            target_price=195.0,
            is_option=True,
            available_margin=50000.0,
            allow_after_hours=True,  # test order structure, not session timing
        )
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertIsNotNone(result.cost_breakdown)

    def test_market_session(self):
        # Closed sessions must not be tradeable; open must be.
        from datetime import datetime
        weekend = datetime(2026, 8, 22, 11, 0)   # Saturday
        after = datetime(2026, 8, 21, 20, 0)     # Friday after close
        during = datetime(2026, 8, 21, 11, 0)    # Friday mid-session
        self.assertFalse(ZerodhaPlumbingInspector.market_session(weekend)["is_open"])
        self.assertFalse(ZerodhaPlumbingInspector.market_session(after)["is_open"])
        self.assertTrue(ZerodhaPlumbingInspector.market_session(during)["is_open"])

    def test_special_session_muhurat_opens_only_in_its_notified_window(self):
        # NSE/FAOP/76940: Sun 2026-11-08 pre-open 14:05, continuous trading 14:20-15:40 (F&O).
        from datetime import datetime
        ms = lambda t: ZerodhaPlumbingInspector.market_session(datetime.fromisoformat(t))  # noqa: E731
        self.assertEqual([(ms(t)["session"], ms(t)["is_open"]) for t in
                          ("2026-11-08 10:00", "2026-11-08 14:10", "2026-11-08 14:20", "2026-11-08 15:40", "2026-11-08 15:41")],
                         [("PRE_MARKET", False), ("PRE_OPEN", False), ("OPEN", True), ("OPEN", True), ("CLOSED", False)])
        self.assertIn("NSE/FAOP/76940", ms("2026-11-08 14:30")["message"])
        self.assertFalse(ms("2026-11-15 14:30")["is_open"])        # an ordinary Sunday stays closed
        self.assertFalse(ZerodhaPlumbingInspector.market_session(datetime(2026, 11, 8, 14, 30), "MCX")["is_open"])

    def test_nse_holiday_is_closed_all_day(self):
        # NSE/FAOP/71777: Tue 2026-11-10 Diwali-Balipratipada; the header said "OPEN 13:00" on it.
        from datetime import datetime
        s = ZerodhaPlumbingInspector.market_session(datetime(2026, 11, 10, 13, 0))
        self.assertEqual((s["is_open"], s["session"]), (False, "HOLIDAY"))
        self.assertIn("Diwali-Balipratipada", s["message"])
        self.assertTrue(ZerodhaPlumbingInspector.market_session(datetime(2026, 11, 11, 13, 0))["is_open"])
        self.assertTrue(ZerodhaPlumbingInspector.market_session(datetime(2026, 11, 10, 13, 0), "MCX")["is_open"])
        y27 = ZerodhaPlumbingInspector.market_session(datetime(2027, 1, 26, 11, 0))     # no 2027 list yet
        self.assertFalse(y27["holidays_verified"])
        self.assertIn("not verified", y27["message"])

    def test_ignite_volume_pace_unchanged_on_normal_days(self):
        from datetime import datetime
        from dashboard import intraday_ignite as I
        self.assertAlmostEqual(I._expected_volume_fraction(datetime(2026, 11, 9, 11, 0)), (105 / 375) ** 0.8)
        self.assertAlmostEqual(I._expected_volume_fraction(datetime(2026, 11, 8, 14, 40)), (20 / 80) ** 0.8)

    def test_black_scholes_engine_importable(self):
        # Guards the dashboard wiring: app.py depends on this exact API, so a
        # broken import must fail loudly here rather than silently skip.
        self.assertTrue(
            BLACK_SCHOLES_OK,
            "black_scholes.OptionPricer/OptionType must be importable for the dashboard options endpoint",
        )

    @unittest.skipUnless(BLACK_SCHOLES_OK, "Black-Scholes engine not imported")
    def test_black_scholes_pricing(self):
        pricer = OptionPricer(
            spot=24000.0, strike=24000.0, time_to_expiry=7 / 365,
            volatility=0.15, risk_free_rate=0.07,
        )
        price = pricer.price(OptionType.CALL)
        self.assertGreater(price, 0.0)

        greeks = pricer.all_greeks(OptionType.CALL)
        # ATM call delta sits near 0.5
        self.assertGreater(greeks.delta, 0.4)
        self.assertLess(greeks.delta, 0.6)
        # Long option time decay is negative
        self.assertLess(greeks.theta, 0.0)


if __name__ == "__main__":
    unittest.main()
