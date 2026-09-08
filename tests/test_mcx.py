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


class Black76(unittest.TestCase):
    def test_call_put_parity_and_positivity(self):
        from dashboard import black76
        F, K, T, s = 8800.0, 8800.0, 20 / 365, 0.35
        c = black76.price(F, K, T, s, True)
        p = black76.price(F, K, T, s, False)
        self.assertGreater(c, 0); self.assertGreater(p, 0)
        self.assertAlmostEqual(c, p, places=2)          # ATM on a future: call ≈ put
        # put-call parity: C - P = disc*(F-K) = 0 at ATM
        self.assertAlmostEqual(c - p, 0.0, places=2)

    def test_iv_round_trip(self):
        from dashboard import black76
        F, K, T = 8800.0, 9000.0, 25 / 365
        px = black76.price(F, K, T, 0.42, True)
        iv = black76.implied_vol(px, F, K, T, True)
        self.assertAlmostEqual(iv, 42.0, places=1)

    def test_prob_and_expected_move(self):
        from dashboard import black76
        F, T, s = 8800.0, 25 / 365, 0.40
        self.assertAlmostEqual(black76.prob_above(F, F, T, s), 0.5, delta=0.03)  # ATM ≈ 50%
        self.assertAlmostEqual(black76.expected_move(F, s, T), F * s * (25 / 365) ** 0.5, places=2)

    def test_iv_none_below_intrinsic(self):
        from dashboard import black76
        # deep ITM call priced below intrinsic → no IV
        self.assertIsNone(black76.implied_vol(50.0, 9000.0, 8000.0, 0.05, True))


class Analytics(unittest.TestCase):
    def test_probability_suppressed_on_one_sided_quote(self):
        from dashboard import mcx_analytics
        an = mcx_analytics.option_analytics(8800.0, 8800.0, date(2026, 9, 25), True,
                                            bid=120.0, ask=None, ltp=125.0, lot_size=100,
                                            entry_premium=110.0, today=date(2026, 9, 8))
        self.assertIn(an["iv_confidence"], ("low", "medium"))
        self.assertEqual(an["p_itm"], {"low": None, "high": None})   # no two-sided → no precise prob

    def test_two_sided_produces_iv_band_and_prob(self):
        from dashboard import mcx_analytics
        an = mcx_analytics.option_analytics(8800.0, 8800.0, date(2026, 9, 25), True,
                                            bid=118.0, ask=124.0, ltp=121.0, lot_size=100,
                                            entry_premium=110.0, today=date(2026, 9, 8))
        self.assertEqual(an["iv_confidence"], "high")
        self.assertIsNotNone(an["iv_bid"]); self.assertIsNotNone(an["iv_ask"])
        self.assertIsNotNone(an["p_itm"]["low"]); self.assertIsNotNone(an["p_itm"]["high"])
        self.assertLessEqual(an["p_itm"]["low"], an["p_itm"]["high"])
        self.assertIsNotNone(an["expected_move_pts"])


class Events(unittest.TestCase):
    def setUp(self):
        from zoneinfo import ZoneInfo
        self.IST = ZoneInfo("Asia/Kolkata")

    def _eia(self):
        return {"id": "eia", "name": "EIA Petroleum", "commodity_roots": ["CRUDEOIL"],
                "timezone": "America/New_York", "schedule_type": "recurring",
                "rule": "WEEKLY WEDNESDAY 10:30", "severity": "high",
                "pre_event_minutes": 360, "post_event_cooldown_minutes": 30, "overrides": []}

    def test_eia_summer_edt_to_ist(self):
        from dashboard import mcx_events
        # Monday 2026-07-13 IST; next EIA = Wed 2026-07-15 10:30 EDT = 20:00 IST (UTC+5:30, EDT=UTC-4)
        now = datetime(2026, 7, 13, 9, 0, tzinfo=self.IST)
        st = mcx_events.event_state(self._eia(), now)
        self.assertEqual(st["status"], "scheduled")
        ist = datetime.fromisoformat(st["event_time_ist"])
        self.assertEqual((ist.hour, ist.minute), (20, 0))     # EDT → 20:00 IST

    def test_eia_winter_est_to_ist(self):
        from dashboard import mcx_events
        # Monday 2026-01-12 IST; next EIA = Wed 2026-01-14 10:30 EST = 21:00 IST (EST=UTC-5)
        now = datetime(2026, 1, 12, 9, 0, tzinfo=self.IST)
        st = mcx_events.event_state(self._eia(), now)
        ist = datetime.fromisoformat(st["event_time_ist"])
        self.assertEqual((ist.hour, ist.minute), (21, 0))     # EST → 21:00 IST (DST shift handled)

    def test_within_guard_flag(self):
        from dashboard import mcx_events
        # 3h before the Wed 20:00 IST EIA (summer) → within the 360-min guard
        now = datetime(2026, 7, 15, 17, 0, tzinfo=self.IST)
        st = mcx_events.event_state(self._eia(), now)
        self.assertTrue(st["within_guard"])
        self.assertLessEqual(st["time_to_event_minutes"], 360)

    def test_override_only_unknown_without_dates(self):
        from dashboard import mcx_events
        fomc = {"id": "fomc", "name": "FOMC", "commodity_roots": ["ALL"], "timezone": "America/New_York",
                "schedule_type": "override_only", "rule": None, "severity": "high",
                "pre_event_minutes": 720, "post_event_cooldown_minutes": 60, "overrides": []}
        st = mcx_events.event_state(fomc, datetime(2026, 3, 2, 9, 0, tzinfo=self.IST))
        self.assertEqual(st["status"], "unknown")            # no fabricated date
        self.assertIsNone(st["event_time_ist"])


class Backtest(unittest.TestCase):
    def _contracts(self):
        return [{"symbol": "CRUDEOIL26SEPFUT", "token": 1, "expiry": date(2026, 9, 19)},
                {"symbol": "CRUDEOIL26OCTFUT", "token": 2, "expiry": date(2026, 10, 19)}]

    def test_active_contract_rolls_before_expiry(self):
        from dashboard.mcx_backtest import active_contract
        cs = self._contracts()
        self.assertEqual(active_contract(cs, date(2026, 9, 15), 3)["symbol"], "CRUDEOIL26SEPFUT")
        self.assertEqual(active_contract(cs, date(2026, 9, 17), 3)["symbol"], "CRUDEOIL26OCTFUT")  # rolled

    def test_stitch_flags_roll_transition(self):
        from dashboard.mcx_backtest import stitch_series
        def bar(d, c):
            return [f"{d} 00:00:00", c, c + 1, c - 1, c, 100]
        cbt = {
            1: [bar("2026-09-15", 100), bar("2026-09-16", 101)],
            2: [bar("2026-09-15", 100), bar("2026-09-16", 101), bar("2026-09-17", 102), bar("2026-09-18", 103)],
        }
        s = stitch_series(self._contracts(), cbt, roll_days_before=3)
        bydate = {x["date"].isoformat(): x for x in s}
        self.assertEqual(bydate["2026-09-16"]["contract"], "CRUDEOIL26SEPFUT")
        self.assertEqual(bydate["2026-09-17"]["contract"], "CRUDEOIL26OCTFUT")
        self.assertTrue(bydate["2026-09-17"]["roll_transition"])
        self.assertFalse(bydate["2026-09-16"]["roll_transition"])

    def test_regime(self):
        from dashboard.mcx_backtest import _regime
        self.assertEqual(_regime([100 + i for i in range(21)]), "trend")   # +20% over 20 bars
        self.assertEqual(_regime([100 + (i % 2) * 0.2 for i in range(21)]), "range")

    def test_metrics_rescued_whipsaw_drawdown(self):
        from dashboard.mcx_backtest import _metrics
        trades = [
            {"pnl": 1.0, "base": -0.5, "hold": 5, "mae": -0.8, "r_mult": 0.5, "ever_fav": True},   # rescued
            {"pnl": -1.0, "base": -1.0, "hold": 3, "mae": -1.2, "r_mult": -0.5, "ever_fav": True},  # whipsaw
            {"pnl": 2.0, "base": 2.0, "hold": 8, "mae": -0.3, "r_mult": 1.0, "ever_fav": True},
        ]
        m = _metrics(trades)
        self.assertEqual(m["rescued"], 1)
        self.assertEqual(m["whipsaw"], 1)
        self.assertEqual(m["trades"], 3)
        self.assertLess(m["max_drawdown"], 0)


class SetupRadar(unittest.TestCase):
    CFG = {"mcx_setup_ema_fast": 9, "mcx_setup_ema_slow": 20, "structure_pivot_k": 2,
           "mcx_setup_breakout_atr_mult": 1.0, "mcx_setup_volume_mult": 1.3}

    def _bar(self, o, h, l, c, v=1000):
        return ["d", o, h, l, c, v]

    def test_trend_long_and_short(self):
        from dashboard.mcx_setups import trend_signal
        up = [self._bar(100 + i, 101 + i, 99 + i, 100.6 + i) for i in range(30)]
        dn = [self._bar(100 - i, 101 - i, 99 - i, 100 - i) for i in range(30)]
        self.assertEqual(trend_signal(up, self.CFG)["direction"], "LONG")
        self.assertEqual(trend_signal(dn, self.CFG)["direction"], "SHORT")

    def test_pullback_long(self):
        from dashboard.mcx_setups import pullback_signal
        # uptrend, then a shallow pullback toward the 20-EMA with a bounce bar → LONG pullback
        up = [self._bar(100 + i, 101 + i, 99 + i, 100.6 + i) for i in range(28)]
        up += [self._bar(126, 126.5, 123, 123.5)]      # dip toward EMA20
        up += [self._bar(123.6, 125, 123.4, 124.8)]    # bounce bar (closes up, upper half)
        s = pullback_signal(up, {**self.CFG, "mcx_setup_pullback_band": 3.0})
        self.assertEqual(s["direction"], "LONG")
        self.assertEqual(s["kind"], "pullback")
        # a wide gap above the EMA (no pullback) must NOT fire
        self.assertEqual(pullback_signal(up, {**self.CFG, "mcx_setup_pullback_band": 1.0})["direction"], "NONE")

    def test_breakout_up(self):
        from dashboard.mcx_setups import breakout_signal
        base = [self._bar(100, 101, 99, 100, 1000) for _ in range(24)]
        base[10] = self._bar(100, 103, 99, 100, 1000)     # a confirmed swing-high pivot ~103
        brk = base + [self._bar(101, 108, 100, 107, 3000)]  # close 107 > pivot, big range, high vol
        s = breakout_signal(brk, self.CFG)
        self.assertEqual(s["direction"], "LONG")
        self.assertEqual(s["kind"], "breakout")

    def test_conflict_stands_aside(self):
        # A genuine trend-vs-breakout disagreement is hard to contrive with candles, so stub the
        # two detectors to return opposite directions and assert the resolution stands aside.
        from dashboard import mcx_setups
        candles = [self._bar(100, 101, 99, 100) for _ in range(30)]
        orig_t, orig_b = mcx_setups.trend_signal, mcx_setups.breakout_signal
        try:
            mcx_setups.trend_signal = lambda c, cfg: {"direction": "LONG", "kind": "trend", "strength": 0.8}
            mcx_setups.breakout_signal = lambda c, cfg: {"direction": "SHORT", "kind": "breakout", "strength": 0.8}
            s = mcx_setups.evaluate_setup(candles, self.CFG, "high")
            self.assertEqual(s["direction"], "NONE")
            self.assertEqual(s["kind"], "conflict")
        finally:
            mcx_setups.trend_signal, mcx_setups.breakout_signal = orig_t, orig_b

    def test_score_and_no_setup(self):
        from dashboard.mcx_setups import evaluate_setup
        flat = [self._bar(100, 100.2, 99.8, 100) for _ in range(30)]
        self.assertEqual(evaluate_setup(flat, self.CFG)["direction"], "NONE")
        up = [self._bar(100 + i, 101 + i, 99 + i, 100.6 + i) for i in range(30)]
        s = evaluate_setup(up, self.CFG, "high")
        self.assertEqual(s["direction"], "LONG")
        self.assertGreater(s["score"], 0)

    def test_trade_state_gating(self):
        from dashboard.mcx_setups import _trade_state
        setup = {"direction": "LONG", "kind": "trend", "score": 70}
        # eligible ONLY when validated=True
        self.assertEqual(_trade_state(setup, "A", "front_liquid", "high", False, 55, "B", validated=True)["state"], "ELIGIBLE_FOR_REVIEW")
        self.assertEqual(_trade_state(setup, "D", "front_liquid", "high", False, 55, "B", validated=True)["state"], "ILLIQUID")
        self.assertEqual(_trade_state(setup, "A", "expiry_risk", "high", False, 55, "B", validated=True)["state"], "ROLL_GUARD")
        self.assertEqual(_trade_state(setup, "A", "front_liquid", "high", True, 55, "B", validated=True)["state"], "EVENT_GUARD")
        self.assertEqual(_trade_state({"direction": "NONE", "kind": None, "score": 0}, "A", "front_liquid", "high", False, 55, "B")["state"], "WATCH")

    def test_unvalidated_never_eligible(self):
        from dashboard.mcx_setups import _trade_state
        setup = {"direction": "LONG", "kind": "trend+breakout", "score": 90}
        s = _trade_state(setup, "A", "front_liquid", "high", False, 0, "B", validated=False)
        self.assertEqual(s["state"], "WATCH")          # not validated → never eligible
        self.assertIn("not validated", s["why"])


class IntradayStitch(unittest.TestCase):
    def test_keeps_intraday_resolution_and_flags_roll(self):
        from dashboard.mcx_intraday_backtest import stitch_intraday
        contracts = [{"symbol": "CRUDEOIL26SEPFUT", "token": 1, "expiry": date(2026, 9, 19)},
                     {"symbol": "CRUDEOIL26OCTFUT", "token": 2, "expiry": date(2026, 10, 19)}]

        def bar(ts, c):
            return [ts, c, c + 1, c - 1, c, 100]
        # two 15-min bars per day on each contract; SEP active 09-15, OCT active from 09-17 (roll 3d before 09-19)
        cbt = {
            1: [bar("2026-09-15 09:15:00", 100), bar("2026-09-15 09:30:00", 101)],
            2: [bar("2026-09-15 09:15:00", 100), bar("2026-09-15 09:30:00", 101),
                bar("2026-09-17 09:15:00", 103), bar("2026-09-17 09:30:00", 104)],
        }
        s = stitch_intraday(contracts, cbt, roll_days_before=3)
        by = [(x["ts"], x["contract"], x["roll_transition"]) for x in s]
        # 09-15 keeps SEP's two bars (intraday resolution preserved), 09-17 keeps OCT's two
        self.assertEqual([b[1] for b in by], ["CRUDEOIL26SEPFUT", "CRUDEOIL26SEPFUT",
                                              "CRUDEOIL26OCTFUT", "CRUDEOIL26OCTFUT"])
        self.assertEqual(sum(1 for b in by if b[2]), 1)   # exactly one roll transition


class SetupValidation(unittest.TestCase):
    def test_score_buckets(self):
        from dashboard.mcx_setup_backtest import score_buckets
        trades = [{"pnl": 1.0, "score": 30}, {"pnl": -0.5, "score": 45},
                  {"pnl": 2.0, "score": 60}, {"pnl": 3.0, "score": 80}, {"pnl": -1.0, "score": 80}]
        b = {x["bucket"]: x for x in score_buckets(trades)}
        self.assertEqual(b["0-40"]["n"], 1)
        self.assertEqual(b["55-70"]["n"], 1)
        self.assertEqual(b["70-101"]["n"], 2)
        self.assertAlmostEqual(b["70-101"]["avg_pnl"], 1.0, places=2)  # (3 + -1)/2

    def test_setup_policy_enters_on_trend(self):
        from dashboard.mcx_setup_backtest import run_setup_policy
        def bar(c):
            return ["d", c, c + 1, c - 1, c, 1000]
        # a clean uptrend → LONG setups should fire and produce trades
        series = [{"bar": bar(100 + i), "roll_window": False, "roll_transition": False} for i in range(60)]
        cfg = {"mcx_setup_ema_fast": 9, "mcx_setup_ema_slow": 20, "structure_pivot_k": 2,
               "mcx_setup_breakout_atr_mult": 1.0, "mcx_setup_volume_mult": 1.3}
        trades = run_setup_policy(series, cfg, 1.75, min_score=0.0)
        self.assertGreater(len(trades), 0)
        self.assertTrue(all("score" in t for t in trades))


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
