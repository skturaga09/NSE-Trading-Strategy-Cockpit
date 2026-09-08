#!/usr/bin/env python3
"""Unit tests for MCX commodities support (C0.5 + C1a core). Fixture-driven — no network."""

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from dashboard import mcx, mcx_expiry
from dashboard import mcx_contract_profiles as profiles
from dashboard.zerodha_plumbing import ZerodhaPlumbingInspector as Z


def _fut(name, exp, token, lot=100, tick=1.0):
    return {"token": token, "tradingsymbol": f"{name}FUT{token}", "name": name,
            "segment": "MCX-FUT", "exchange": "MCX", "instrument_type": "FUT",
            "strike": None, "expiry": date.fromisoformat(exp), "lot_size": lot, "tick_size": tick}


def _opt(name, exp, token, strike, typ="CE", lot=100):
    return {"token": token, "tradingsymbol": f"{name}{strike}{typ}", "name": name,
            "segment": "MCX-OPT", "exchange": "MCX", "instrument_type": typ,
            "strike": strike, "expiry": date.fromisoformat(exp), "lot_size": lot, "tick_size": 0.1}


# A fixture master: CRUDEOIL fut Sep/Oct, GOLD & GOLDM futures Oct, plus options, plus one NFO row.
FIX = [
    _fut("CRUDEOIL", "2026-09-19", 1001),
    _fut("CRUDEOIL", "2026-10-19", 1002),
    _fut("GOLD", "2026-10-05", 2001, lot=100),
    _fut("GOLDM", "2026-10-05", 2002, lot=10),
    _opt("CRUDEOIL", "2026-09-16", 1101, 5500, "CE"),
    _opt("GOLD", "2026-09-29", 2101, 73000, "CE", lot=100),
    _opt("GOLDM", "2026-09-29", 2102, 73000, "CE", lot=10),
    # an NFO row that must be ignored by MCX filters despite a similar shape
    {"token": 9999, "tradingsymbol": "RELIANCE26SEP1400CE", "name": "RELIANCE",
     "segment": "NFO-OPT", "exchange": "NFO", "instrument_type": "CE", "strike": 1400,
     "expiry": date(2026, 9, 24), "lot_size": 500, "tick_size": 0.05},
]
TODAY = date(2026, 9, 8)


class ContractMapping(unittest.TestCase):
    def test_maps_to_nearest_future_on_or_after_option_expiry(self):
        r = mcx.option_underlying_future("CRUDEOIL", date(2026, 9, 16), FIX, TODAY)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["future"]["expiry"], date(2026, 9, 19))   # Sep, not Oct

    def test_mapping_fails_when_option_outlives_all_futures(self):
        r = mcx.option_underlying_future("CRUDEOIL", date(2026, 12, 31), FIX, TODAY)
        self.assertEqual(r["status"], "mapping_uncertain")
        self.assertIsNone(r["future"])

    def test_mapping_fails_for_unknown_root(self):
        r = mcx.option_underlying_future("WHEAT", date(2026, 9, 16), FIX, TODAY)
        self.assertEqual(r["status"], "mapping_uncertain")

    def test_main_and_mini_not_cross_mapped(self):
        g = mcx.option_underlying_future("GOLD", date(2026, 9, 29), FIX, TODAY)
        gm = mcx.option_underlying_future("GOLDM", date(2026, 9, 29), FIX, TODAY)
        self.assertEqual(g["future"]["tradingsymbol"], "GOLDFUT2001")
        self.assertEqual(gm["future"]["tradingsymbol"], "GOLDMFUT2002")
        self.assertNotEqual(g["future"]["token"], gm["future"]["token"])

    def test_mcx_filter_ignores_nfo_rows(self):
        # futures_map / options must never include the NFO RELIANCE row
        self.assertNotIn("RELIANCE", mcx.futures_map(FIX))
        self.assertTrue(all(o["exchange"] == "MCX" for o in mcx._opts(FIX)))

    def test_economic_root_aliases_only_where_configured(self):
        self.assertEqual(mcx.economic_root("GOLDM"), "GOLD")
        self.assertEqual(mcx.economic_root("CRUDEOILM"), "CRUDEOIL")
        self.assertEqual(mcx.economic_root("COPPER"), "COPPER")     # self
        self.assertEqual(mcx.economic_root("XYZ"), "XYZ")           # unknown → self, no guess

    def test_contract_link_is_auditable(self):
        opt = next(o for o in FIX if o["tradingsymbol"] == "GOLDM73000CE")
        link = mcx.contract_link(opt, FIX, TODAY)
        self.assertEqual(link.economic_root, "GOLD")
        self.assertEqual(link.underlying_future_symbol, "GOLDMFUT2002")
        self.assertEqual(link.contract_status, "tradable")
        self.assertEqual(link.mapping_confidence, "medium")   # fallback rule → medium, not high
        self.assertGreaterEqual(link.days_option_to_future_expiry, 0)


class Liquidity(unittest.TestCase):
    def test_tight_two_sided_with_depth_is_A(self):
        g = mcx.liquidity_grade(100.0, 100.4, 100.2, bid_qty=50, ask_qty=50, oi=1000, volume=500, max_spread_pct=8.0)
        self.assertEqual(g["grade"], "A")

    def test_tight_without_depth_capped_below_A(self):
        g = mcx.liquidity_grade(100.0, 100.4, 100.2, max_spread_pct=8.0)
        self.assertIn(g["grade"], ("B",))
        self.assertEqual(g["grade_confidence"], "low")

    def test_wide_spread_is_C(self):
        g = mcx.liquidity_grade(100.0, 112.0, 106.0, oi=10, volume=5, max_spread_pct=8.0)
        self.assertEqual(g["grade"], "C")

    def test_one_sided_is_D(self):
        self.assertEqual(mcx.liquidity_grade(100.0, None, 100.0)["grade"], "D")
        self.assertEqual(mcx.liquidity_grade(None, None, None)["grade"], "D")


class ExpiryRisk(unittest.TestCase):
    def test_devolved_side_matrix(self):
        f = mcx_expiry._devolved_side
        self.assertEqual(f("CE", "LONG", "ITM"), "LONG")
        self.assertEqual(f("PE", "LONG", "ITM"), "SHORT")
        self.assertEqual(f("CE", "SHORT", "ITM"), "SHORT")
        self.assertEqual(f("PE", "SHORT", "ITM"), "LONG")
        self.assertEqual(f("CE", "LONG", "OTM"), "NONE")

    def test_itm_state_uses_atr_buffer(self):
        s = mcx_expiry._itm_state
        self.assertEqual(s("CE", 5500, 5600, 100, 0.15), "ITM")
        self.assertEqual(s("CE", 5500, 5400, 100, 0.15), "OTM")
        self.assertEqual(s("CE", 5500, 5505, 100, 0.15), "ATM")   # within 0.15*100 buffer
        self.assertEqual(s("CE", 5500, None, 100, 0.15), "UNKNOWN")

    def test_unverified_profile_forces_unknown_state(self):
        # CRUDEOIL profile ships verified=false → settlement 'unknown' → safe-degrade to UNKNOWN
        self.assertFalse(profiles.is_verified("CRUDEOIL"))
        opt = next(o for o in FIX if o["name"] == "CRUDEOIL" and o["instrument_type"] == "CE")
        link = mcx.contract_link(opt, FIX, TODAY)
        pos = {"position_id": "p1", "option_symbol": opt["tradingsymbol"], "option_token": opt["token"],
               "option_type": "CE", "side": "LONG", "quantity_lots": 1}
        risk = mcx_expiry.evaluate(pos, link, future_price=5600, strike=5500, lot_size=100,
                                   atr=120, cfg=mcx._cfg(), today=date(2026, 9, 15))
        self.assertEqual(risk.settlement_mode, "unknown")
        self.assertEqual(risk.expiry_risk_state, "UNKNOWN")
        self.assertTrue(any("manual review" in w for w in risk.warnings))

    def test_no_auto_action_config_defaults_false(self):
        c = mcx._cfg()
        self.assertFalse(c.get("mcx_auto_squareoff_enabled"))
        self.assertFalse(c.get("mcx_auto_contrary_instruction_enabled"))
        self.assertFalse(c.get("mcx_auto_roll_enabled"))


class Context(unittest.TestCase):
    def test_attribution_splits_move(self):
        from dashboard.mcx_context import _attribution
        # MCX +1.05, global +0.72, fx +0.18 → residual +0.15, aligned high
        a = _attribution(1.05, 0.72, 0.18)
        self.assertAlmostEqual(a["residual_return_pct"], 0.15, places=2)
        self.assertEqual(a["alignment"], "high")

    def test_attribution_low_alignment_when_residual_dominates(self):
        from dashboard.mcx_context import _attribution
        a = _attribution(2.0, 0.2, 0.1)     # residual 1.7 of a 2.0 move → low
        self.assertEqual(a["alignment"], "low")

    def test_attribution_unavailable_when_no_benchmark(self):
        from dashboard.mcx_context import _attribution
        a = _attribution(1.0, None, 0.1)
        self.assertEqual(a["alignment"], "unavailable")
        self.assertIsNone(a["residual_return_pct"])

    def test_base_metal_has_no_free_benchmark(self):
        from dashboard.mcx_context import GLOBAL_BENCHMARK
        self.assertIsNone(GLOBAL_BENCHMARK.get("ZINC"))
        self.assertIsNotNone(GLOBAL_BENCHMARK.get("CRUDEOIL"))


class ChandelierAndArm(unittest.TestCase):
    def test_chandelier_long_exit_and_hold(self):
        from dashboard.structure_exit import chandelier
        def C(o, h, l, c):
            return ["d", o, h, l, c, 1000]
        # 30 rising bars (range ~2 each) → ATR ~2; high ~ index. Then a sharp drop breaches stop.
        up = [C(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(30)]
        hold = chandelier(up + [C(129, 130, 128, 129)], "LONG", 3.0)   # close near the high → hold
        brk = chandelier(up + [C(129, 129, 118, 119)], "LONG", 3.0)    # close far below → exit
        self.assertIsNone(hold)
        self.assertIsNotNone(brk)
        self.assertIn("stop", brk)

    def test_chandelier_short(self):
        from dashboard.structure_exit import chandelier
        def C(o, h, l, c):
            return ["d", o, h, l, c, 1000]
        dn = [C(100 - i, 101 - i, 99 - i, 100 - i) for i in range(30)]
        brk = chandelier(dn + [C(71, 82, 71, 81)], "SHORT", 3.0)   # rallied above stop → exit
        self.assertIsNotNone(brk)

    def test_mcx_arm_is_static_not_regime(self):
        # exchange-aware arm: MCX must use the flat per-exchange arm, not the equity regime.
        from dashboard import exit_monitor as em
        cfg = em.get_config()
        self.assertIn("MCX", cfg.get("breakeven_arm_by_exchange", {}))
        self.assertEqual(float(cfg["breakeven_arm_by_exchange"]["MCX"]), 8.0)


class Session(unittest.TestCase):
    def test_mcx_evening_open_when_nse_closed(self):
        t = datetime(2026, 9, 8, 20, 0)  # Tuesday 20:00 — NSE shut, MCX evening
        self.assertFalse(Z.market_session(t, "NSE")["is_open"])
        self.assertTrue(Z.market_session(t, "MCX")["is_open"])

    def test_mcx_closed_weekend(self):
        t = datetime(2026, 9, 12, 20, 0)  # Saturday
        self.assertFalse(Z.market_session(t, "MCX")["is_open"])

    def test_nse_session_unchanged(self):
        t = datetime(2026, 9, 8, 11, 0)
        s = Z.market_session(t, "NSE")
        self.assertTrue(s["is_open"])
        self.assertEqual(s["session"], "OPEN")


if __name__ == "__main__":
    unittest.main()
