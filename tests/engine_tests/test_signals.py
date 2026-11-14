"""Phase 8: setup families, eligibility gates, evidence scoring, recommendation object, lifecycle. Synthetic fixtures only."""

import copy
import json
import pickle
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from engine import opportunity as O
from engine import risk as R
from engine import signal_report as SR
from engine import signals as G
from engine import structure as T
from engine.candles import MIN, S, DataQuality, Unavailable
from engine.config import ConfigError, EngineConfig
from engine.positioning import Feature, PositioningState, View
from engine.tiers import TierBook
from tests.engine_tests.test_contracts_risk import (CONTRACTS, DAY, FUT_NEAR, FUT_QUOTES, SPOT, SPOT_Q, TRADABLE, T as T0,
                                                    option_quotes, quote)

CFG = G.load()
ATR = 1000.0
FW = CFG.get("positioning.feature_window_min")
TF = 3
Q = DataQuality("fixture", None, None, T0, None, (), None, (), "OK")


def cfg_with(**patch):
    values = copy.deepcopy(dict(CFG.values))
    for dotted, v in patch.items():
        node, *path = [values] + dotted.split("__")
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = v
    return EngineConfig(CFG.version, CFG.sha256, values)


V20 = CFG   # shipped default: options only (D-69), short IV history = warning (D-70)
# The fixtures here are a futures trade (and the rejecting IV gate): pin those two keys to their pre-v20 behaviour
CFG = cfg_with(contracts__instrument_kinds=["FUT", "CE", "PE"], options__iv_history_short="REJECT")


# Futures margin at 20 % of notional so that one candidate can pass every Phase 7 check (v14 default 1.0 rejected all, Q-RISK-1).
# Risk per trade pinned at the 2,000 the fixture was sized on (v18 default is 10,000: more lots, so capital would fail).
PASSING = cfg_with(contracts__futures_margin__fraction=0.2, risk__max_risk_per_trade_inr=2000)


def det(typ, t, level=None, tf=f"{TF}m", und="STK", id_=None, **attrs):
    return T.Detection(id_ or f"{typ}@{t}", typ, und, FUT_NEAR, tf, level, t, t, (), attrs, "", "fixture")


def pstate(hyp, rvol=2.0, move=1.5, raw=None, near=None, t=T0, reasons=(), und="STK"):
    v = lambda h: View(h, reasons if h == G.NEUTRAL else (), None, ())  # noqa: E731
    feats = (Feature(f"rvol_{FW}m", rvol, Q), Feature(f"atr_move_{FW}m", move, Q))
    return PositioningState(und, t, FUT_NEAR, "STK26NOVFUT", "2026-11-26", (FUT_NEAR,), v(hyp), v(raw or hyp), v(near or hyp),
                            (), feats, "fixture")


def history(hyp, rvols=(2.0, 2.0, 2.0)):
    """(ts, state) oldest first, spaced by the feature window, ending at T0."""
    n = len(rvols)
    return tuple((T0 - (n - 1 - i) * FW * MIN, pstate(hyp, rvol=r, t=T0 - (n - 1 - i) * FW * MIN)) for i, r in enumerate(rvols))


MARKET_UP = G.MarketContext(T0, 1, 0.7, 30, G.LONG_BUILDUP)
MARKET_DOWN = G.MarketContext(T0, -1, 0.3, 30, G.SHORT_BUILDUP)

# Phase 6 setups. Prices in paise on the near-month future (FUT_NEAR, quoted 999.90 / 1000.10).
FIRST, CONF = T0 - 6 * MIN, T0 - 3 * MIN
SET_A = O.Setup("a1", "BREAKOUT", "BREAKOUT_ACCEPTED", "STK", FUT_NEAR, TF, 1, FIRST, 100000, CONF, 100000, 99000, 99900, 0.3, None)
SET_B = replace(SET_A, id="b1", source_type="BREAKDOWN_ACCEPTED", direction=-1, structural_stop=101000, broken_level=100100)
SET_E = replace(SET_A, id="e1", family="SWEEP", source_type="SWEEP_LOW", broken_level=99500)
SET_F = replace(SET_B, id="f1", family="SWEEP", source_type="SWEEP_HIGH", broken_level=100500)


def evaluation(s, price=100000, above=103000, below=97000, age_s=0, structure=(), flags_vwap=None, t=T0):
    """A Phase 6 evaluation built by Phase 6 itself (opportunity_age) from a fixture snapshot."""
    ob = lambda lv: None if lv is None else T.Obstacle("SWING_HIGH" if lv > price else "SWING_LOW", "3m", lv,  # noqa: E731
                                                      lv - price, {"3m": (lv - price) / ATR}, f"o{lv}")
    lm = T.LevelMap("STK", FUT_NEAR, t, price, {"3m": ATR}, ob(above), ob(below), 2)
    vw = flags_vwap if flags_vwap is not None else price - 200 * s.direction
    snap = O.Snapshot(t, price, t - age_s * S, t - age_s * S + S, ATR, vw, lm, structure, None, ATR)
    return O.opportunity_age(s, snap, CFG)


def struct(s, *extra, vwap=None):
    """Phase 5 detections known at T0: the setup's own detection, the setup-timeframe VWAP, plus extras."""
    own = {"BREAKOUT_ACCEPTED": dict(box="box1", via="closes", closes_beyond=2),
           "BREAKDOWN_ACCEPTED": dict(box="box1", via="closes", closes_beyond=2),
           "SWEEP_LOW": dict(extreme=99000, rejection_rvol=2.0, reclaim_bars=1, swept="sw", swept_type="SWING_LOW"),
           "SWEEP_HIGH": dict(extreme=101000, rejection_rvol=2.0, reclaim_bars=1, swept="sw", swept_type="SWING_HIGH")}
    v = vwap if vwap is not None else 100000 - 200 * s.direction
    return (det(s.source_type, CONF, s.broken_level, id_=s.id, **own[s.source_type]),
            det("VWAP", T0 - MIN, v, atr=ATR)) + extra


def evidence(s, hyp, market=MARKET_UP, extra=(), hist=None, **kw):
    pos = None if hyp is None else pstate(hyp, **kw)
    return G.Evidence(T0, pos, hist if hist is not None else history(hyp or G.NEUTRAL), struct(s, *extra), market)


BOS_UP, BOS_DOWN = det("BOS_UP", T0 - 2 * MIN, 99950), det("BOS_DOWN", T0 - 2 * MIN, 100050)
CHOCH_UP, CHOCH_DOWN = det("CHOCH_UP", T0 - 2 * MIN, 99950), det("CHOCH_DOWN", T0 - 2 * MIN, 100050)
FLAT = R.PortfolioState(T0 - MIN, DAY, 0.0, 0.0, 0.0, (), 0.0, 0, 0, None)


def inputs(s=SET_A, x=None, ev=None, portfolio=FLAT, quotes=None, spot=SPOT_Q):
    x = x or evidence(s, G.LONG_BUILDUP, extra=(BOS_UP,))
    ev = ev or evaluation(s)
    shift = lambda v: replace(v, receive_ns=v.receive_ns + ev.as_of - T0,  # noqa: E731  quotes 1 s before the decision
                              exchange_ts_ns=v.exchange_ts_ns and v.exchange_ts_ns + ev.as_of - T0)
    q = {k: shift(v) for k, v in {**FUT_QUOTES, **option_quotes(), **(quotes or {})}.items()}
    return G.SignalInputs(s, ev, x, tuple(CONTRACTS), TRADABLE, q, spot and shift(spot), {}, {}, portfolio)


def late(t=T0):
    """VALID_BUT_LATE (EXTENDED, STOP_TOO_WIDE) while Phase 7's net R:R still passes."""
    return evaluation(SET_A, price=100600, above=104000, t=t)


class Families(unittest.TestCase):
    """Every family has a positive fixture (a Setup) and negative fixtures (None)."""

    def m(self, s, x, ev=None):
        return G.match(s, ev or evaluation(s), x, CFG)

    def test_A_fresh_long_buildup_breakout(self):
        fs = self.m(SET_A, evidence(SET_A, G.LONG_BUILDUP))
        self.assertEqual((fs.family, fs.label, fs.kind, fs.direction), ("A", "LONG_BUILDUP_BREAKOUT", G.CONTINUATION, 1))
        self.assertTrue(any("LONG_BUILDUP" in e for e in fs.evidence) and any("RVOL" in e for e in fs.evidence))
        self.assertIsNone(self.m(SET_A, evidence(SET_A, G.SHORT_COVERING, move=0.1)), "covering is not buildup")
        self.assertIsNone(self.m(SET_A, evidence(SET_A, G.LONG_BUILDUP, rvol=1.2)), "RVOL not elevated")
        self.assertIsNone(self.m(SET_A, replace(evidence(SET_A, G.LONG_BUILDUP), structure=struct(SET_A, vwap=100100))),
                          "price below the setup-timeframe VWAP detection")
        self.assertIsNone(self.m(SET_A, evidence(SET_A, None)), "no positioning state: missing evidence, no setup")
        self.assertIsNone(self.m(SET_A, evidence(SET_A, G.NEUTRAL, reasons=("OI_WINDOW_DISABLED",))))
        self.assertIsNone(self.m(SET_A, evidence(SET_A, G.LONG_BUILDUP), evaluation(SET_A, price=99880, below=97000)),
                          "price back below the broken resistance")

    def test_B_fresh_short_buildup_breakdown(self):
        x = evidence(SET_B, G.SHORT_BUILDUP, market=MARKET_DOWN)
        fs = self.m(SET_B, x, evaluation(SET_B))
        self.assertEqual((fs.family, fs.label, fs.direction), ("B", "SHORT_BUILDUP_BREAKDOWN", -1))
        self.assertIsNone(self.m(SET_B, evidence(SET_B, G.LONG_BUILDUP), evaluation(SET_B)))
        self.assertIsNone(self.m(SET_B, evidence(SET_B, G.SHORT_BUILDUP, rvol=1.0), evaluation(SET_B)))
        self.assertIsNone(self.m(SET_B, replace(x, structure=struct(SET_B, vwap=99900)), evaluation(SET_B)), "not below VWAP")

    def test_C_short_covering_momentum_is_labelled_and_exhaustion_checked(self):
        fs = self.m(SET_A, evidence(SET_A, G.SHORT_COVERING, rvol=1.1, move=1.2))
        self.assertEqual((fs.family, fs.label, fs.kind), ("C", "SHORT_COVERING_MOMENTUM", G.CONTINUATION))
        self.assertIn("covering, not confirmed new buying", fs.warnings)
        self.assertTrue(any(w.startswith("EXHAUSTION_CHECK") for w in fs.warnings))
        self.assertIsNone(self.m(SET_A, evidence(SET_A, G.SHORT_COVERING, rvol=1.1, move=0.5)), "not up sharply")
        self.assertIsNone(self.m(SET_A, evidence(SET_A, G.SHORT_COVERING, rvol=0.5, move=1.2)), "volume not supportive")
        self.assertIsNone(self.m(SET_B, evidence(SET_B, G.SHORT_COVERING, move=1.2), evaluation(SET_B)), "needs a resistance break")

    def test_D_long_unwinding_continuation_needs_persistent_volume(self):
        x = evidence(SET_B, G.LONG_UNWINDING, hist=history(G.LONG_UNWINDING, (1.2, 1.1, 1.3)))
        fs = self.m(SET_B, x, evaluation(SET_B))
        self.assertEqual((fs.family, fs.label, fs.direction), ("D", "LONG_UNWINDING_CONTINUATION", -1))
        self.assertIsNone(self.m(SET_B, replace(x, positioning_history=history(G.LONG_UNWINDING, (1.2, 0.6, 1.3))),
                                 evaluation(SET_B)), "volume not persistent")
        self.assertIsNone(self.m(SET_B, replace(x, positioning_history=history(G.LONG_UNWINDING)[1:]), evaluation(SET_B)),
                          "a missing window is not persistence")
        self.assertIsNone(self.m(SET_B, replace(x, structure=struct(SET_B, vwap=99900)), evaluation(SET_B)), "not below VWAP")

    def test_E_F_liquidity_sweep_reversals(self):
        fs = self.m(SET_E, evidence(SET_E, None, extra=(CHOCH_UP,)))
        self.assertEqual((fs.family, fs.label, fs.kind, fs.direction), ("E", "BULLISH_SWEEP_REVERSAL", G.REVERSAL, 1))
        self.assertIsNone(self.m(SET_E, evidence(SET_E, None)), "no bullish structure confirmation")
        self.assertIsNone(self.m(SET_E, evidence(SET_E, None, extra=(BOS_DOWN,))), "confirmation in the wrong direction")
        weak = evidence(SET_E, None, extra=(CHOCH_UP,))
        weak = replace(weak, structure=(replace(weak.structure[0], attrs={**weak.structure[0].attrs, "rejection_rvol": 1.0}),)
                       + weak.structure[1:])
        self.assertIsNone(self.m(SET_E, weak), "rejection RVOL too low")
        early = replace(CHOCH_UP, confirmed_ts=FIRST - MIN, created_ts=FIRST - MIN)
        self.assertIsNone(self.m(SET_E, evidence(SET_E, None, extra=(early,))), "confirmation before the sweep")
        fs = self.m(SET_F, evidence(SET_F, None, extra=(CHOCH_DOWN,)), evaluation(SET_F))
        self.assertEqual((fs.family, fs.label, fs.direction), ("F", "BEARISH_SWEEP_REVERSAL", -1))
        self.assertIsNone(self.m(SET_F, evidence(SET_F, None, extra=(CHOCH_UP,)), evaluation(SET_F)))

    def test_G_exhaustion_is_an_observation_and_a_warning_never_an_entry(self):
        ev = evaluation(SET_A, flags_vwap=98000)            # 2 x 15m ATR above VWAP => Phase 6 POSSIBLE_EXHAUSTION
        self.assertEqual((ev.classification, ev.exhaustion), (O.EXHAUSTED, "POSSIBLE_EXHAUSTION"))
        ob = G.exhaustion_observation(SET_A, ev, CFG)
        self.assertEqual((ob.label, ob.setup_id), ("POSSIBLE_EXHAUSTION", "a1"))
        self.assertTrue(any(r.startswith("VWAP_EXTENSION") for r in ob.reasons))
        self.assertIsNone(G.exhaustion_observation(SET_A, evaluation(SET_A), CFG))
        fs = self.m(SET_A, evidence(SET_A, G.LONG_BUILDUP), ev)
        self.assertTrue(any(w.startswith("POSSIBLE_EXHAUSTION") for w in fs.warnings), "attached as a warning")
        rec = G.recommend(inputs(ev=ev), PASSING)
        self.assertEqual(rec.status, G.REJECTED, "an exhausted setup never becomes ENTRY_ELIGIBLE")
        self.assertIn("TIMELINESS", [g.name for g in rec.gates if not g.passed])

    def test_suspected_accumulation_and_distribution(self):
        dets = (det("VWAP", T0 - MIN, 99800),)
        ob = G.accumulation("STK", history(G.LONG_BUILDUP), dets, T0, CFG)
        self.assertEqual(ob.label, "SUSPECTED_ACCUMULATION")
        self.assertTrue(any("not evidence of institutional" in r for r in ob.reasons))
        self.assertEqual(G.accumulation("STK", history(G.SHORT_BUILDUP), dets, T0, CFG).label, "SUSPECTED_DISTRIBUTION")
        brk = det("BREAKOUT_ACCEPTED", T0 - 10 * MIN, 99900, box="box1")
        self.assertIsNone(G.accumulation("STK", history(G.LONG_BUILDUP), dets + (brk,), T0, CFG), "a breakout happened")
        mixed = history(G.LONG_BUILDUP)[:2] + ((T0, pstate(G.NEUTRAL, reasons=("NOT_SIGNIFICANT",))),)
        self.assertIsNone(G.accumulation("STK", mixed, dets, T0, CFG), "not persistent")
        self.assertIsNone(G.accumulation("STK", history(G.LONG_BUILDUP)[1:], dets, T0, CFG), "too few windows")

    def test_all_twelve_state_labels_exist_and_are_reachable(self):
        self.assertEqual(len(G.LABELS), 12)
        seen = {G.match(s, evaluation(s), x, CFG).label for s, x in (
            (SET_A, evidence(SET_A, G.LONG_BUILDUP)), (SET_B, evidence(SET_B, G.SHORT_BUILDUP, market=MARKET_DOWN)),
            (SET_A, evidence(SET_A, G.SHORT_COVERING, move=1.2)),
            (SET_B, evidence(SET_B, G.LONG_UNWINDING, hist=history(G.LONG_UNWINDING))),
            (SET_E, evidence(SET_E, None, extra=(CHOCH_UP,))), (SET_F, evidence(SET_F, None, extra=(CHOCH_DOWN,))))}
        seen.add(G.exhaustion_observation(SET_A, evaluation(SET_A, flags_vwap=98000), CFG).label)
        seen |= {G.accumulation("STK", history(h), (), T0, CFG).label for h in (G.LONG_BUILDUP, G.SHORT_BUILDUP)}
        seen.add(G.recommend(inputs(ev=evaluation(SET_A, age_s=60)), PASSING).classification)                 # UNCERTAIN
        seen.add(G.recommend(inputs(ev=evaluation(SET_A, above=None)), PASSING).classification)               # NO_TRADE (no R:R)
        seen.add(G.recommend(inputs(x=evidence(SET_A, G.LONG_BUILDUP, raw=G.SHORT_BUILDUP)), PASSING).classification)
        no_stop = inputs(s=replace(SET_A, structural_stop=Unavailable("INSUFFICIENT_DATA: test")))
        seen.add(G.recommend(replace(no_stop, evaluation=evaluation(no_stop.setup)), PASSING).classification)  # NO_TRADE
        self.assertEqual(seen, set(G.LABELS))


class GatesAndScore(unittest.TestCase):
    def test_passing_fixture_is_entry_eligible(self):
        rec = G.recommend(inputs(), PASSING)
        self.assertEqual(rec.status, G.ENTRY_ELIGIBLE, [g for g in rec.gates if not g.passed])
        self.assertIsNotNone(rec.approval, "ENTRY_ELIGIBLE carries the Phase 7 token-backed Recommendation")
        self.assertEqual(rec.approval.candidate.tradingsymbol, rec.contract)

    def test_high_score_with_a_failed_gate_is_rejected_never_entry_eligible(self):
        open_pos = replace(FLAT, open_underlyings=("OTHER",), capital_in_use_inr=10_000.0)
        for cfg, p, gate in ((PASSING, open_pos, "NO_CONFLICTING_POSITION"), (CFG, FLAT, "RISK_CHECK_APPROVED")):
            rec = G.recommend(inputs(portfolio=p), cfg)
            self.assertGreaterEqual(rec.score.headline.points, CFG.get("signals.bands.medium"), "high score")
            self.assertEqual(rec.status, G.REJECTED)
            self.assertIsNone(rec.approval)
            self.assertIn(gate, [g.name for g in rec.gates if not g.passed])
        evs = [evaluation(SET_A, t=T0 + k * MIN) for k in range(5)]
        lc, recs = G.drive(SET_A, evs, lambda s, t: evidence(SET_A, G.LONG_BUILDUP, extra=(BOS_UP,)),
                           lambda s, ev, x: inputs(ev=ev, x=x, portfolio=open_pos), T0 + 600 * MIN, PASSING)
        self.assertNotIn(G.ENTRY_ELIGIBLE, [r.to_state for r in lc.rows])
        self.assertEqual(lc.state, G.REJECTED)

    def test_stale_critical_data_cannot_reach_entry_eligible(self):
        stale_price = G.recommend(inputs(ev=evaluation(SET_A, age_s=CFG.get("quality.stale_price_s") + 1)), PASSING)
        stale_quote = G.recommend(inputs(quotes={FUT_NEAR: quote(FUT_NEAR, 99990, 100010, qty=2000, age_s=30)}), PASSING)
        for rec in (stale_price, stale_quote):
            self.assertEqual(rec.status, G.REJECTED)
            self.assertIn("DATA_QUALITY", [g.name for g in rec.gates if not g.passed])
            self.assertEqual(rec.classification, "UNCERTAIN")
        evs = [evaluation(SET_A, t=T0 + k * MIN, age_s=60) for k in range(3)]
        lc, _ = G.drive(SET_A, evs, lambda s, t: evidence(SET_A, G.LONG_BUILDUP), lambda s, ev, x: inputs(ev=ev, x=x),
                        T0 + 600 * MIN, PASSING)
        self.assertNotIn(G.ENTRY_ELIGIBLE, [r.to_state for r in lc.rows])

    def test_late_waits_for_retest_unknown_is_rejected(self):
        rec = G.recommend(inputs(ev=late()), PASSING)
        self.assertEqual((rec.status, [g.name for g in rec.gates if not g.passed]), (G.WAIT_FOR_RETEST, ["TIMELINESS"]))
        unknown = G.recommend(inputs(ev=evaluation(SET_A, above=None)), PASSING)
        self.assertEqual((unknown.status, unknown.classification), (G.REJECTED, "NO_TRADE"))

    def test_options_factor_scored_from_the_chain_and_opportunity_age_option_fields_filled(self):
        from engine import options as O
        from engine.candles import Unavailable

        def snap(labels):
            rows = tuple(O.StrikeRow(i, kind, k, *([Unavailable("x")] * 13), hyp, (), None, None, None, None)
                         for i, (kind, k, hyp) in enumerate(labels))
            return O.ChainSnapshot("STK", DAY, T0, T0, 1000.0, 100000, 0.0, rows, 1, 1, {}, {}, (0, 0), (), "v14")
        ctx = O.OptionContext("STK", T0, {}, (snap([("PE", 1000.0, "PUT_WRITING"), ("CE", 1000.0, "CALL_BUYING")]),),
                              Unavailable("x"), Unavailable("IV_HISTORY_SHORT"), {})
        rec = G.recommend(replace(inputs(), options=ctx), PASSING)
        opt = next(f for f in rec.score.headline.factors if f.name == "options")
        self.assertEqual((opt.points, opt.available_max), (20, 20))
        self.assertTrue(opt.parts[0].detail.startswith("SUPPORTIVE"))
        age = rec.opportunity_age
        self.assertIn("option_premium_change", age)
        self.assertTrue(isinstance(age["option_premium_change"], Unavailable))
        self.assertTrue(age["option_iv_change"].reason.startswith(("NOT_AN_OPTION", "NO_CANDIDATE")), age["option_iv_change"])

    def test_missing_option_data_scores_zero_listed_missing_and_max_available_reported(self):
        sc = G.recommend(inputs(), PASSING).score.headline
        opt = next(f for f in sc.factors if f.name == "options")
        self.assertEqual((opt.points, opt.available_max), (0, 0))
        self.assertTrue(opt.missing and opt.missing[0].startswith("NO_OPTION_CHAIN"))   # Phase 11: no recorded chain
        self.assertIn("options", " ".join(sc.missing))
        self.assertEqual(sc.max_points, 100)
        self.assertLessEqual(sc.available_max, 80)
        self.assertEqual(sc.summary, f"{sc.points:g}/{sc.available_max:g} available (of {sc.max_points}); not a probability")
        self.assertEqual(sum(f.weight for f in sc.factors), 100)
        for f in sc.factors:
            self.assertTrue(all(p.detail for p in f.parts), f"every part explains itself: {f.name}")

    def test_scores_are_separate_and_counter_direction_scores_lower(self):
        ss = G.recommend(inputs(), PASSING).score
        self.assertGreater(ss.bullish.points, ss.bearish.points)
        self.assertEqual((ss.continuation.kind, ss.reversal.kind), (G.CONTINUATION, G.REVERSAL))
        self.assertEqual(ss.headline, ss.bullish)
        self.assertIn(ss.headline.band, ("RESEARCH_PRIORITY_HIGH", "RESEARCH_PRIORITY_MEDIUM", "RESEARCH_PRIORITY_LOW"))
        self.assertIn("not a probability", ss.headline.summary)

    def test_recommendation_has_every_field_and_prices_from_quotes(self):
        rec = G.recommend(inputs(), PASSING)
        fields = ("signal_id", "as_of", "underlying", "contract", "instrument_type", "expiry", "strike", "lot_size",
                  "direction", "setup_family", "classification", "score", "entry_trigger", "entry_range",
                  "underlying_invalidation", "contract_stop_estimate", "t1", "t2", "expected_net_rr", "max_planned_loss_inr",
                  "full_premium_at_risk_inr", "capital_inr", "liquidity", "spread_pct", "slippage_pct", "data_freshness",
                  "opportunity_age", "why_selected", "contradicting_evidence", "reasons_to_cancel", "config_version", "status")
        for f in fields:
            self.assertTrue(hasattr(rec, f), f)
        c = rec.approval.candidate
        self.assertEqual(rec.entry_range, (c.ask if c.side == "BUY" else c.bid, c.entry))
        self.assertEqual(rec.entry_trigger, 100000)
        self.assertEqual((rec.t1, rec.t2), (103000, Unavailable("NO_LEVEL_BEYOND_T1: no known level beyond target 1")))
        self.assertEqual(rec.config_version, PASSING.version)

    def test_no_defensible_stop_is_no_trade(self):
        s = replace(SET_A, structural_stop=Unavailable("INSUFFICIENT_DATA: test"))
        rec = G.recommend(inputs(s=s, ev=evaluation(s)), PASSING)
        self.assertEqual((rec.status, rec.classification), (G.REJECTED, "NO_TRADE"))


class Lifecycle(unittest.TestCase):
    def test_illegal_transitions_raise_and_rows_are_appended(self):
        lc = G.start("x", T0, "detected")
        for bad in (G.ACTIVE, G.ENTRY_ELIGIBLE, G.TRIGGERED, G.EXIT_REQUIRED, G.DETECTED):
            with self.assertRaises(G.IllegalTransition):
                G.advance(lc, bad, T0 + MIN, "skip")
        lc = G.advance(lc, G.WATCHING, T0 + MIN, "confirmed")
        with self.assertRaises(G.IllegalTransition):
            G.advance(lc, G.CONFIRMED, T0, "back in time")
        path = [G.CONFIRMED, G.ENTRY_ELIGIBLE, G.TRIGGERED, G.ACTIVE, G.WEAKENING, G.ACTIVE, G.EXIT_REQUIRED]
        for i, st in enumerate(path, 2):
            lc = G.advance(lc, st, T0 + i * MIN, f"cause {i}")
        self.assertEqual([r.to_state for r in lc.rows], [G.DETECTED, G.WATCHING] + path)
        self.assertEqual([r.seq for r in lc.rows], list(range(len(path) + 2)))
        self.assertTrue(all(r.cause and r.ts for r in lc.rows))
        for terminal in (G.REJECTED, G.INVALIDATED, G.EXPIRED, G.EXIT_REQUIRED):
            with self.assertRaises(G.IllegalTransition):
                G.advance(replace(lc, rows=lc.rows[:-1] + (replace(lc.rows[-1], to_state=terminal),)), G.WATCHING,
                          T0 + 99 * MIN, "out of a terminal state")

    def test_driver_retest_then_eligible_then_expired(self):
        ok = evaluation(SET_A, t=T0 + MIN)
        x = lambda s, t: evidence(SET_A, G.LONG_BUILDUP, extra=(BOS_UP,))  # noqa: E731
        lc, recs = G.drive(SET_A, [late(), ok, late(T0 + 2 * MIN)], x, lambda s, ev, xx: inputs(ev=ev, x=xx), T0 + 600 * MIN,
                           PASSING)
        self.assertEqual([r.to_state for r in lc.rows], [G.DETECTED, G.WATCHING, G.CONFIRMED, G.WAIT_FOR_RETEST,
                                                          G.CONFIRMED, G.ENTRY_ELIGIBLE, G.EXPIRED])
        self.assertEqual([r.status for r, _ in recs], [G.WAIT_FOR_RETEST, G.ENTRY_ELIGIBLE])
        self.assertTrue(lc.rows[-1].cause.startswith("NO_LONGER_TIMELY"))
        inval = replace(ok, as_of=T0 + 2 * MIN, state="INVALIDATED", classification=None, reason="CLOSE_THROUGH_STOP")
        lc, _ = G.drive(SET_A, [ok, inval], x, lambda s, ev, xx: inputs(ev=ev, x=xx), T0 + 600 * MIN, PASSING)
        self.assertEqual(lc.state, G.INVALIDATED)
        lc, recs = G.drive(SET_A, [ok], lambda s, t: evidence(SET_A, G.SHORT_BUILDUP), lambda *a: inputs(), T0, PASSING)
        self.assertEqual(([r.to_state for r in lc.rows], recs), ([G.DETECTED, G.WATCHING, G.EXPIRED], []),
                         "no family evidence: watched, never confirmed, expired at the close")
        zone = replace(SET_A, family="ZONE", source_type="ZONE_DEFENDED")
        self.assertEqual(G.drive(zone, [ok], x, lambda *a: inputs(), T0, PASSING), (None, []))

    def test_entry_eligible_promotes_underlying_and_candidates_to_tier_b(self):
        rec = G.recommend(inputs(), PASSING)
        reqs = G.promotions([rec, G.recommend(inputs(portfolio=replace(FLAT, open_underlyings=("X",))), PASSING)], PASSING)
        self.assertEqual({t for t, _, _ in reqs}, {FUT_NEAR, SPOT} | set(rec.candidate_tokens))
        self.assertTrue(all(ttl == PASSING.get("signals.tier_b_ttl_s") and rec.signal_id in why for _, why, ttl in reqs))
        book = TierBook(PASSING, lambda: T0, lambda t: ("FUT", "STK"))
        G.promote(book, reqs)
        plan = book.plan()
        self.assertTrue(all("B" in plan.meta[t][0] for t, _, _ in reqs))


class Reproducibility(unittest.TestCase):
    def test_replaying_stored_inputs_regenerates_an_identical_object(self):
        for inp in (inputs(), inputs(ev=late()), inputs(portfolio=replace(FLAT, trades_today=9))):
            rec = G.recommend(inp, PASSING)
            again = G.recommend(pickle.loads(pickle.dumps(inp)), PASSING)
            self.assertEqual(G.payload(rec), G.payload(again))
        with tempfile.TemporaryDirectory() as d:
            lc, recs = G.drive(SET_A, [evaluation(SET_A)], lambda s, t: evidence(SET_A, G.LONG_BUILDUP),
                               lambda s, ev, x: inputs(ev=ev, x=x), T0 + 600 * MIN, PASSING)
            SR.write(Path(d), {SET_A.id: (lc, recs)}, [], PASSING)
            SR.write(Path(d), {SET_A.id: (lc, recs)}, [], PASSING)   # idempotent
            stored = SR.read(Path(d), PASSING.version)
            self.assertEqual(len(stored["recommendations"]), 1)
            self.assertEqual(len(stored["lifecycle"]), len(lc.rows))
            self.assertEqual(SR.replay_check(Path(d), PASSING), {"checked": 1, "identical": 1, "different": []})


class MarketContextValues(unittest.TestCase):                 # Phase 8 SC4 (Phase 15 G-8)
    def test_trend_from_latest_index_turn_and_breadth_share_above_vwap(self):
        tf, need = CFG.get("signals.market.trend_timeframe_min"), CFG.get("signals.market.breadth_min_underlyings")
        up = det("BOS_UP", T0, tf=f"{tf}m", und="NIFTY")
        down = det("CHOCH_DOWN", T0 + 5 * MIN, tf=f"{tf}m", und="NIFTY")
        pts = tuple((101, 100) for _ in range(need - 5)) + tuple((99, 100) for _ in range(5))   # close vs vwap
        m = G.market_context(T0 + MIN, (up, down), None, pts, CFG)                 # CHOCH_DOWN not knowable yet
        self.assertEqual((m.nifty_trend, m.breadth, m.breadth_n), (1, (need - 5) / need, need))
        self.assertEqual(G.market_context(T0 + 5 * MIN, (up, down), None, pts, CFG).nifty_trend, -1)
        few = G.market_context(T0, (), None, pts[:need - 1], CFG)
        self.assertIsInstance(few.nifty_trend, Unavailable)
        self.assertIsInstance(few.breadth, Unavailable)


class LiveHorizon(unittest.TestCase):
    def test_live_write_stores_nothing_after_the_last_packet(self):
        from types import SimpleNamespace as NS
        rows = [NS(signal_id="s", seq=i, ts=ts, from_state="A", to_state="B", cause="c") for i, ts in enumerate((10, 20, 30))]
        results = {"s": (NS(rows=rows), [])}
        with tempfile.TemporaryDirectory() as d:
            SR.write(Path(d), results, [], CFG, horizon_ns=20)       # data ends at 20: the 30 row is not known yet
            self.assertEqual([r["ts"] for r in SR.read(Path(d), CFG.version)["lifecycle"]], [10, 20])
            SR.write(Path(d), results, [], CFG)                      # the full-day run adds the tail, keeps the prefix
            self.assertEqual([r["ts"] for r in SR.read(Path(d), CFG.version)["lifecycle"]], [10, 20, 30])


class ConfigAndPurity(unittest.TestCase):
    def test_v10_loads_missing_key_and_bad_weights_fail(self):
        self.assertEqual(V20.version, "v24")   # D-76 cloud archive; Phase 15: D-61/62 risk, D-67 OI age, D-69 options only, D-70 IV warn, D-71 limits, D-72 coverage; v10 still loads
        self.assertEqual(G.load(G.REPO / "config/engine/v10.yaml").version, "v10")
        raw = yaml.safe_load(Path(G.DEFAULT_CONFIG).read_text())
        for mutate in (lambda v: v["signals"]["families"].pop("rejection_rvol"),
                       lambda v: v["signals"]["weights"].update(options=21)):
            v = copy.deepcopy(raw)
            mutate(v)
            with tempfile.NamedTemporaryFile("w", suffix=".yaml") as f:
                yaml.safe_dump(v, f)
                with self.assertRaises(ConfigError):
                    G.load(f.name)

    def test_signal_core_is_pure(self):
        src = Path(G.__file__).read_text()
        for bad in ("sqlite3", "open(", "datetime.now", "time.time", "requests", "urllib", "Path(", "KiteConnect"):
            self.assertNotIn(bad, src, bad)
        # order-method names: covered repo-wide by test_edges.test_no_order_methods_in_repo_code

    def test_labels_never_claim_institutional_activity(self):
        text = json.dumps(G.payload(G.recommend(inputs(), PASSING)))
        self.assertNotRegex(text.lower(), r"institutional (buying|selling)(?! or)")
        self.assertIn("not evidence of institutional", G.DISCLAIMER)


if __name__ == "__main__":
    unittest.main()
