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

from dashboard.zerodha_plumbing import ZerodhaPlumbingInspector, LOT_SIZES, FREEZE_LIMITS

try:
    from black_scholes import OptionPricer, OptionType
    BLACK_SCHOLES_OK = True
except ImportError:
    BLACK_SCHOLES_OK = False


class TestZerodhaPlumbingInspector(unittest.TestCase):

    def setUp(self):
        self.inspector = ZerodhaPlumbingInspector()

    def test_symbol_resolution(self):
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("RELIANCE.NS"), "RELIANCE")
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("^NSEI"), "NIFTY")
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("BANKNIFTY"), "BANKNIFTY")
        self.assertEqual(ZerodhaPlumbingInspector.resolve_symbol("tcs.bo"), "TCS")

    def test_lot_size_validation(self):
        # Valid lot sizes
        diag_nifty = ZerodhaPlumbingInspector.validate_lot_size("NIFTY", 75)
        self.assertEqual(diag_nifty.status, "PASSED")

        diag_bank = ZerodhaPlumbingInspector.validate_lot_size("BANKNIFTY", 30) # 2 lots of 15
        self.assertEqual(diag_bank.status, "PASSED")

        # Invalid lot size (e.g. 50 NIFTY)
        diag_invalid = ZerodhaPlumbingInspector.validate_lot_size("NIFTY", 50)
        self.assertEqual(diag_invalid.status, "FAILED")
        self.assertEqual(diag_invalid.details["recommended_quantity"], 75)

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
            symbol="NIFTY", transaction_type="SELL", product="NRML", quantity=75, price=140.0, is_option=True
        )
        self.assertLessEqual(opt_costs.brokerage, 20.0)
        self.assertGreater(opt_costs.stt, 0.0)

    def test_order_safety_validation(self):
        # Option SL-M warning check
        diags = ZerodhaPlumbingInspector.validate_order_parameters(
            symbol="NIFTY", product="NRML", order_type="SL-M", transaction_type="BUY", quantity=75, price=140.0, trigger_price=130.0, is_option=True
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
            quantity=75,
            price=140.0,
            stop_loss_price=95.0,
            target_price=195.0,
            is_option=True,
            available_margin=50000.0
        )
        self.assertTrue(result.is_valid)
        self.assertEqual(len(result.errors), 0)
        self.assertIsNotNone(result.cost_breakdown)

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
