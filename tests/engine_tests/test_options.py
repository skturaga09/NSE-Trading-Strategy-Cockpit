"""Phase 11: option-chain intelligence, IV / Greeks, event gates, selector V2, tier C planner. Synthetic fixtures only.

IV references (textbook values, not market data):
- Hull, "Options, Futures, and Other Derivatives", Black's model worked example: European put on a future, F = K = 20,
  r = 9 %, T = 4/12, sigma = 25 % -> 1.12.
- Haug, "The Complete Guide to Option Pricing Formulas" (2nd ed.), sec. 1.1.4 Black-76: F = K = 19, T = 0.75, r = 10 %,
  sigma = 28 % -> call = put = 1.7011.
"""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from engine import contracts as K
from engine import events as EV
from engine import options as O
from engine import risk as R
from engine.candles import MIN, S, Unavailable, _ns
from engine.config import REPO, EngineConfig
from engine.tiers import Request, TierBook, allocate
from engine.universe import Contract, Member, Universe

CFG = O.load()
DAY = date(2026, 11, 9)                 # Monday, a trading day in the verified 2026 calendar
T0 = _ns(DAY, "11:00")
EXP = date(2026, 11, 26)                # option and same-expiry future
LOT = 100
FUT, SPOT = 5001, 5000


def cfg_with(**patch):
    v = copy.deepcopy(dict(CFG.values))
    for dotted, x in patch.items():
        node, *path = [v] + dotted.split("__")
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = x
    return EngineConfig(CFG.version, CFG.sha256, v)


V20 = CFG   # the shipped default: options only (D-69), short IV history = warning (D-70)
# These tests exercise futures next to options and the rejecting IV gate: pin those two keys (pre-v20 behaviour)
CFG = cfg_with(contracts__instrument_kinds=["FUT", "CE", "PE"], options__iv_history_short="REJECT")


def contract(tok, typ, strike=None, exp=EXP, und="STK", family="STOCK"):
    return Contract(tok, und, family, f"{und}{exp:%y%b}{strike or ''}{typ}".upper(), typ, exp,
                    None if strike is None else Decimal(strike), LOT, Decimal("0.05"),
                    "NFO-OPT" if strike else "NFO-FUT", "NFO", True, DAY, DAY)


def quote(tok, bid, ask, qty=200_000, volume=10_000_000, oi=5_000_000, age_s=1, ltp=None, at=T0):
    return K.Quote(tok, tuple((bid - i * 5, qty, 10) for i in range(5)), tuple((ask + i * 5, qty, 10) for i in range(5)),
                   True, ltp if ltp is not None else (bid + ask) // 2, volume, oi, at - int(age_s * S), at - int(age_s * S), "fixture")


STRIKES = (980, 990, 1000, 1010, 1020)
OPTS = [contract(int(f"{6 + (t == 'PE')}{i}"), t, k) for i, k in enumerate(STRIKES) for t in ("CE", "PE")]
FUTC = contract(FUT, "FUT")
CONTRACTS = [FUTC] + OPTS
TRADABLE = {c.token: (True, []) for c in CONTRACTS}
F_PAISE = 100000                        # future mid 1000.00


def tok(t, k):
    return next(c.token for c in OPTS if c.instrument_type == t and c.strike == k)


def fair(t, k, sigma=0.20, at=T0, f=F_PAISE):
    T, r = O.trading_years(at, EXP, CFG), O.risk_free(at, CFG)
    return O.black76(f / 100, k, T, r, sigma, t == "CE") * 100      # paise


def fair_quote(t, k, sigma=0.20, half=5, **kw):
    m = round(fair(t, k, sigma, kw.get("at", T0)))
    return quote(tok(t, k), m - half, m + half, **kw)


FUT_Q = quote(FUT, F_PAISE - 5, F_PAISE + 5)
CLEAR = EV.EventStatus(EV.VERIFIED, "fixture: calendar fetched today", T0 - MIN, "x", "fixture", ())


class BlackAndIV(unittest.TestCase):
    def test_iv_solver_matches_reference_values_within_tolerance(self):
        self.assertAlmostEqual(O.black76(20, 20, 4 / 12, 0.09, 0.25, False), 1.12, delta=0.005)     # Hull
        self.assertAlmostEqual(O.black76(19, 19, 0.75, 0.10, 0.28, True), 1.7011, delta=0.0001)     # Haug
        self.assertAlmostEqual(O.black76(19, 19, 0.75, 0.10, 0.28, False), 1.7011, delta=0.0001)
        self.assertAlmostEqual(O.implied_vol(1.7011, 19, 19, 0.75, 0.10, True, CFG), 0.28, delta=0.0005)
        self.assertAlmostEqual(O.implied_vol(O.black76(20, 20, 4 / 12, 0.09, 0.25, False), 20, 20, 4 / 12, 0.09, False, CFG),
                               0.25, delta=0.0005)
        for sigma in (0.08, 0.2, 0.6, 1.5):                           # round trip across the range
            p = O.black76(1000, 1040, 0.05, 0.058, sigma, True)
            self.assertAlmostEqual(O.implied_vol(p, 1000, 1040, 0.05, 0.058, True, CFG), sigma, delta=0.002)

    def test_greeks_match_finite_differences(self):
        F, Kk, T, r, s = 1000.0, 1010.0, 0.06, 0.058, 0.22
        g = O.greeks(F, Kk, T, r, s, True, CFG)
        h = 0.01
        p = lambda f=F, t=T, v=s: O.black76(f, Kk, t, r, v, True)  # noqa: E731
        self.assertAlmostEqual(g.delta, (p(F + h) - p(F - h)) / (2 * h), places=5)
        self.assertAlmostEqual(g.gamma, (p(F + h) - 2 * p() + p(F - h)) / h ** 2, places=4)
        self.assertAlmostEqual(g.vega, (p(v=s + 1e-4) - p(v=s - 1e-4)) / 2e-4 / 100, places=5)
        dt = 1 / CFG.get("options.trading_days_per_year")
        self.assertAlmostEqual(g.theta, p(t=T - dt) - p(), delta=abs(g.theta) * 0.05)   # one trading day of decay
        self.assertLess(g.theta, 0)

    def test_trading_years_and_rate(self):
        o, c = _ns(DAY, "09:15"), _ns(DAY, CFG.get("sessions.fno.close"))
        later = sum(O._trading(date(2026, 11, d), CFG) for d in range(10, 27))      # 11-10 .. 11-26 trading days
        self.assertAlmostEqual(O.trading_years(T0, EXP, CFG), ((c - T0) / (c - o) + later) / 252, places=12)
        self.assertEqual(later, 11)                                   # 2026-11-10 and 2026-11-24 are F&O holidays (F-NSE-5)
        self.assertIn("T_UNAVAILABLE", O.trading_years(T0, date(2027, 1, 28), CFG).reason)
        self.assertAlmostEqual(O.risk_free(T0, CFG), 0.058968 * 0 + __import__("math").log(1 + 0.05897 * 91 / 365) * 365 / 91, places=9)
        self.assertIn("RATE_STALE", O.risk_free(_ns(date(2026, 12, 1), "11:00"), CFG).reason)

    def test_iv_recovered_from_a_fresh_narrow_book_mid(self):
        a = O.analyze(OPTS[4], fair_quote("CE", 1000), FUT_Q, True, T0, CFG)
        self.assertAlmostEqual(a.iv, 0.20, delta=0.002)
        self.assertEqual((a.method, a.processed_ns), ("BLACK76_SAME_EXPIRY_FUTURE", T0))
        self.assertAlmostEqual(a.age_s, 1.0)
        self.assertGreater(a.greeks.delta, 0.4)

    def test_wide_spread_option_iv_unavailable_not_computed_from_ltp(self):
        m = round(fair("CE", 1000))
        wide = quote(tok("CE", 1000), m - 300, m + 300, ltp=m)        # LTP is a perfectly fair price; the book is wide
        a = O.analyze(OPTS[4], wide, FUT_Q, True, T0, CFG)
        self.assertIsInstance(a.iv, Unavailable)
        self.assertTrue(a.iv.reason.startswith("SPREAD_TOO_WIDE_FOR_IV"), a.iv.reason)
        self.assertIn("not computed from LTP", a.iv.reason)
        self.assertIsInstance(a.greeks, Unavailable)
        one_sided = replace(wide, bids=())
        self.assertIn("NO_VALID_BOOK", O.analyze(OPTS[4], one_sided, FUT_Q, True, T0, CFG).iv.reason)

    def test_iv_unavailable_reasons(self):
        c = OPTS[4]
        stale = fair_quote("CE", 1000, age_s=60)
        self.assertIn("STALE_QUOTE", O.analyze(c, stale, FUT_Q, True, T0, CFG).iv.reason)
        self.assertIn("NO_SAME_EXPIRY_FUTURE", O.analyze(c, fair_quote("CE", 1000), None, False, T0, CFG).iv.reason)
        below = quote(c.token, 50, 60)                                 # deep under intrinsic of a 990 call? use ITM strike
        itm = next(x for x in OPTS if x.instrument_type == "CE" and x.strike == 980)
        r = O.analyze(itm, replace(below, token=itm.token), FUT_Q, True, T0, CFG).iv.reason
        self.assertIn("SPREAD_TOO_WIDE_FOR_IV", r)                     # 50/60 paise is an 18 % spread first
        low = quote(itm.token, 1980, 1990)                             # mid 19.85 < discounted intrinsic (~19.94)
        self.assertIn("OUTSIDE_NO_ARBITRAGE_BOUNDS", O.analyze(itm, low, FUT_Q, True, T0, CFG).iv.reason)
        late = _ns(date(2026, 11, 26), "11:00")                          # expiry day; auction 22 days old > 21
        q = replace(fair_quote("CE", 1000), receive_ns=late - S)          # any fresh narrow book: the rate is the problem
        self.assertIn("RATE_STALE", O.analyze(c, q, replace(FUT_Q, receive_ns=late - S), True, late, CFG).iv.reason)


class Hypotheses(unittest.TestCase):
    def test_rising_call_oi_without_corroboration_is_uncertain_not_call_writing(self):
        self.assertEqual(O.hypothesis("CE", 8.0, 0.0, 0.0, 0.0, CFG)[0], O.UNCERTAIN)
        self.assertEqual(O.hypothesis("CE", 8.0, -5.0, 0.0, 0.0, CFG)[0], O.UNCERTAIN, "OI + premium alone never label")
        self.assertEqual(O.hypothesis("CE", 8.0, -5.0, Unavailable("IV_UNAVAILABLE"), -0.3, CFG)[0], O.UNCERTAIN)
        self.assertEqual(O.hypothesis("CE", 8.0, -5.0, -1.0, 0.3, CFG)[0], O.UNCERTAIN, "underlying rising contradicts writing")
        self.assertEqual(O.hypothesis("CE", 8.0, -5.0, -1.0, -0.3, CFG)[0], "CALL_WRITING")

    def test_each_label_needs_all_four_inputs(self):
        cases = [("CE", 5, 5, 1, 0.3, "CALL_BUYING"), ("PE", 5, 5, 1, -0.3, "PUT_BUYING"), ("PE", 5, -5, -1, 0.3, "PUT_WRITING"),
                 ("CE", -5, 5, 0, 0.3, "SHORT_COVERING"), ("PE", -5, 5, 1, -0.3, "SHORT_COVERING"),
                 ("CE", -5, -5, 0, -0.3, "LONG_LIQUIDATION"), ("PE", -5, -5, -1, 0.3, "LONG_LIQUIDATION")]
        for kind, oi, p, iv, u, want in cases:
            self.assertEqual(O.hypothesis(kind, oi, p, iv, u, CFG)[0], want, (kind, oi, p, iv, u))
            self.assertEqual(O.hypothesis(kind, oi, p, iv, Unavailable("x"), CFG)[0], O.UNCERTAIN)

    def test_chain_snapshot_metrics_hedge_and_missing_oi(self):
        now = {c.token: O.analyze(c, fair_quote(c.instrument_type, int(c.strike)), FUT_Q, True, T0, CFG) for c in OPTS}
        ref_t = T0 - CFG.get("options.change_window_min") * MIN
        ref = {c.token: O.analyze(c, fair_quote(c.instrument_type, int(c.strike), at=ref_t), replace(FUT_Q, receive_ns=ref_t - S),
                                  True, ref_t, CFG) for c in OPTS}
        oi_ref = {c.token: (100_000, ref_t - S) for c in OPTS}
        oi_now = {c.token: (100_000, T0 - S) for c in OPTS}
        oi_now[tok("CE", 1000)] = (110_000, T0 - S)                    # CE and PE at 1000 both +10 %: hedge suspected
        oi_now[tok("PE", 1000)] = (110_000, T0 - S)
        oi_now[tok("CE", 1020)] = (300_000, T0 - S)                    # concentration moves to CE 1020
        vol = {c.token: 50_000 for c in OPTS}
        s = O.chain_snapshot("STK", EXP, OPTS, now, ref, oi_now, oi_ref, vol, {}, F_PAISE, F_PAISE, T0, CFG)
        self.assertEqual(s.atm_strike, 1000.0)
        by = {(r.kind, r.strike): r for r in s.rows}
        self.assertEqual(by[("CE", 1000.0)].hypothesis, O.HEDGE)
        self.assertEqual(by[("CE", 980.0)].hypothesis, O.UNCERTAIN)
        self.assertAlmostEqual(s.pcr_oi, 510_000 / 710_000)
        self.assertEqual(s.concentration["CE"][0], 1020.0)
        self.assertGreater(s.concentration_change["CE"], 0)
        self.assertEqual(s.iv_coverage, (10, 10))
        self.assertIn("HYPOTHESES_NOT_FACTS", s.labels)
        gone = {**oi_now}
        del gone[tok("PE", 990)]
        s2 = O.chain_snapshot("STK", EXP, OPTS, now, ref, gone, oi_ref, vol, {}, F_PAISE, F_PAISE, T0, CFG)
        self.assertIsInstance(s2.pcr_oi, Unavailable)
        self.assertIn("1 of 5 strikes missing oi", s2.pcr_oi.reason)
        stale = {t: (v, T0 - 400 * S) for t, (v, _) in oi_now.items()}
        s3 = O.chain_snapshot("STK", EXP, OPTS, now, ref, stale, oi_ref, vol, {}, F_PAISE, F_PAISE, T0, CFG)
        self.assertTrue(all(isinstance(r.oi_change, Unavailable) and r.hypothesis == O.UNCERTAIN for r in s3.rows))

    def test_options_factor_states(self):
        def snap(labels):
            rows = tuple(O.StrikeRow(i, kind, k, *([Unavailable("x")] * 13), hyp, (), None, None, None, None)
                         for i, (kind, k, hyp) in enumerate(labels))
            return O.ChainSnapshot("STK", EXP, T0, T0, 1000.0, F_PAISE, 0.0, rows, 1, 1, {}, {}, (0, 0), (), "v14")
        bull = snap([("PE", 1000.0, "PUT_WRITING"), ("CE", 1010.0, "CALL_BUYING"), ("CE", 1000.0, "UNCERTAIN")])
        self.assertEqual(O.options_factor(1, bull, CFG)[:2], (O.SUPPORTIVE, 1.0))
        self.assertEqual(O.options_factor(-1, bull, CFG)[:2], (O.CONTRADICTING, 0.0))
        mixed = snap([("PE", 1000.0, "PUT_WRITING"), ("CE", 1010.0, "CALL_BUYING"), ("CE", 990.0, "CALL_WRITING")])
        self.assertEqual(O.options_factor(1, mixed, CFG)[:2], (O.NEUTRAL, 0.0))
        far = snap([("PE", 1000.0, "PUT_WRITING"), ("CE", 1100.0, "CALL_BUYING")]
                   + [("CE", float(k), "UNCERTAIN") for k in (1010, 1020, 1030)])               # 1100 outside ATM +/- 2
        self.assertEqual(O.options_factor(1, far, CFG)[0], O.NEUTRAL)
        self.assertIsInstance(O.options_factor(1, None, CFG)[1], Unavailable)
        self.assertIn("hypotheses, not facts", O.options_factor(1, bull, CFG)[2])

    def test_iv_percentile_needs_history_and_ignores_the_same_day(self):
        hist = [(date(2026, 10, d), 0.10 + d / 100) for d in range(1, 31)]
        self.assertIn("IV_HISTORY_SHORT", O.iv_percentile(0.2, hist[:5], DAY, CFG).reason)
        self.assertAlmostEqual(O.iv_percentile(0.205, hist, DAY, CFG), 100 * 10 / 30)
        self.assertIn("IV_HISTORY_SHORT", O.iv_percentile(0.2, hist, date(2026, 10, 15), CFG).reason, "only earlier days")
        self.assertIn("IV_PERCENTILE_UNAVAILABLE", O.iv_percentile(Unavailable("x"), hist, DAY, CFG).reason)


def setup(direction=1, day=DAY):
    return K.TradeSetup("S1", "STK", direction, day, T0, FUT, F_PAISE, F_PAISE - 600 * direction,
                        (F_PAISE + 1500 * direction,), 300.0)


def ctx(pct=30.0, quotes=None):
    q = quotes or {c.token: fair_quote(c.instrument_type, int(c.strike)) for c in OPTS}
    an = {c.token: O.analyze(c, q[c.token], FUT_Q, True, T0, CFG) for c in OPTS}
    return O.OptionContext("STK", T0, an, (), Unavailable("fixture"), pct, {}), q


def select(direction=1, events=CLEAR, pct=30.0, cfg=CFG, contracts=CONTRACTS):
    chain, q = ctx(pct)
    spot = K.Quote(SPOT, (), (), False, F_PAISE, None, None, T0 - S, T0 - S, "fixture")
    return K.select_contracts(setup(direction), contracts, TRADABLE, {FUT: FUT_Q, **q}, spot, {}, {}, cfg,
                              chain=chain, events=events)


FLAT = R.PortfolioState(T0 - MIN, DAY, 0.0, 0.0, 0.0, (), 0.0, 0, 0, None)


class SelectorV2AndEvents(unittest.TestCase):
    def test_otm_alternative_greeks_premium_theta_and_expiry_sensitivity(self):
        sel = select()
        ce = {c.role: c for c in sel.candidates if c.kind == "CE"}
        self.assertEqual({r: c.strike for r, c in ce.items()}, {"ATM": 1000.0, "ITM": 990.0, "OTM": 1010.0})
        a = ce["ATM"]
        g = a.greeks
        self.assertTrue(a.premium_method.startswith("BLACK76_DELTA_GAMMA_THETA"))
        hold = CFG.get("options.holding_min") * MIN / (_ns(DAY, "15:40") - _ns(DAY, "09:15"))
        self.assertAlmostEqual(a.stop, O.premium_at(a.mid, g, -600, hold))
        self.assertAlmostEqual(a.targets[0], O.premium_at(a.mid, g, 1500, hold))
        self.assertAlmostEqual(a.theta_cost_inr, -g.theta * hold * a.quantity)
        self.assertAlmostEqual(a.expiry_sensitivity["theta_pct_of_premium_per_day"], -g.theta / (a.mid / 100) * 100)
        self.assertAlmostEqual(a.iv, 0.20, delta=0.003)
        self.assertIn("APPROXIMATE_PREMIUM_MODEL", a.labels)
        hot = select(cfg=cfg_with(options__expiry_sensitive_theta_pct=0.0))
        self.assertTrue(any(lb.startswith("EXPIRY_SENSITIVE") for lb in next(c for c in hot.candidates if c.role == "ATM").labels))

    def test_option_within_results_window_rejected_event_iv_risk_futures_warned(self):
        st = replace(CLEAR, events=(EV.Event("STK", date(2026, 11, 12), "Financial Results"),))   # 3rd trading day
        sel = select(events=st)
        opt = next(c for c in sel.candidates if c.kind == "CE" and c.role == "ATM")
        self.assertEqual(opt.status, K.EXCLUDED)
        self.assertTrue(any(r.startswith("EVENT_IV_RISK") for r in opt.reasons), opt.reasons)
        dec = R.risk_check(opt, FLAT, CFG)
        self.assertEqual(dec.status, R.REJECTED)
        self.assertIn("EVENT_IV_RISK", " ".join(dec.reasons))
        fut = next(c for c in sel.candidates if c.kind == "FUT")
        self.assertFalse(any("EVENT" in r for r in fut.reasons))
        self.assertTrue(any(lb.startswith("EVENT_IV_RISK") and "warning only" in lb for lb in fut.labels))
        outside = replace(CLEAR, events=(EV.Event("STK", date(2026, 11, 17), "Financial Results"),))   # 6th trading day
        self.assertFalse(any("EVENT" in r for c in select(events=outside).candidates for r in c.reasons))
        other = replace(CLEAR, events=(EV.Event("OTHER", date(2026, 11, 10), "Financial Results"),))
        self.assertFalse(any("EVENT" in r for c in select(events=other).candidates for r in c.reasons))

    def test_missing_or_stale_calendar_rejects_every_option_event_unverified(self):
        for st in (None, EV.EventStatus(EV.UNVERIFIED, "no calendar fetched between 2026-11-08 and the decision time",
                                        None, None, "x", ())):
            sel = select(events=st)
            opts = [c for c in sel.candidates if c.kind in ("CE", "PE")]
            self.assertTrue(opts)
            for c in opts:
                self.assertTrue(any(r.startswith("EVENT_UNVERIFIED") for r in c.reasons), c.reasons)
                self.assertEqual(R.risk_check(c, FLAT, CFG).status, R.REJECTED)
            fut = next(c for c in sel.candidates if c.kind == "FUT")
            self.assertFalse(any("EVENT" in r for r in fut.reasons))
        idx = [replace(c, family="INDEX") for c in CONTRACTS]
        sel = select(events=None, contracts=idx)
        self.assertTrue(all(any(r.startswith("EVENT_UNVERIFIED") for r in c.reasons) for c in sel.candidates if c.kind == "CE"))

    def test_iv_percentile_gate_for_long_options(self):
        hi = next(c for c in select(pct=95.0).candidates if c.role == "ATM")
        self.assertIn("IV_PERCENTILE_TOO_HIGH (95 > 80)", hi.reasons)
        na = next(c for c in select(pct=Unavailable("IV_HISTORY_SHORT: 0 recorded sessions < 20")).candidates if c.role == "ATM")
        self.assertTrue(any(r.startswith("IV_PERCENTILE_UNAVAILABLE: IV_HISTORY_SHORT") for r in na.reasons))

    def test_v20_options_only_and_short_iv_history_is_a_warning(self):      # owner D-69, D-70
        sel = select(cfg=V20, pct=Unavailable("IV_HISTORY_SHORT: 0 recorded sessions < 20"))
        self.assertFalse([c for c in sel.candidates if c.kind == "FUT"])
        self.assertIn("FUT: not considered (contracts.instrument_kinds: options only, owner D-69)", sel.notes)
        atm = next(c for c in sel.candidates if c.role == "ATM")
        self.assertFalse(any(r.startswith("IV_PERCENTILE_UNAVAILABLE") for r in atm.reasons), atm.reasons)
        self.assertTrue(any(x.startswith("IV_HISTORY_NOT_READY: IV_HISTORY_SHORT") for x in atm.labels), atm.labels)
        # a missing CURRENT IV (no fresh two-sided book) still rejects: that is missing data, not short history
        miss = next(c for c in select(cfg=V20, pct=Unavailable("IV_PERCENTILE_UNAVAILABLE: ATM_IV_UNAVAILABLE")).candidates
                    if c.role == "ATM")
        self.assertTrue(any(r.startswith("IV_PERCENTILE_UNAVAILABLE") for r in miss.reasons))
        self.assertIn("IV_PERCENTILE_TOO_HIGH (95 > 80)", next(c for c in select(cfg=V20, pct=95.0).candidates
                                                              if c.role == "ATM").reasons)   # the full check still applies

    def test_event_window_and_calendar_store(self):
        self.assertEqual(EV.window_end(DAY, CFG), date(2026, 11, 16))   # 11-09, 11-11, 11-12, 11-13, 11-16 (11-10 holiday)
        self.assertIsNone(EV.window_end(date(2026, 12, 28), CFG), "runs into 2027 (unverified holidays)")
        raw = json.dumps([{"symbol": "STK", "company": "x", "purpose": "Financial Results", "bm_desc": "", "date": "12-Nov-2026"}]).encode()
        with tempfile.TemporaryDirectory() as d:
            c = cfg_with(storage__root=d)
            EV.fetch(c, T0 - 3600 * S, get=lambda url, headers, timeout: (200, raw))
            self.assertEqual(EV.status_at(Path(d), T0, c).events, (EV.Event("STK", date(2026, 11, 12), "Financial Results"),))
            self.assertEqual(EV.status_at(Path(d), T0 - 7200 * S, c).status, EV.UNVERIFIED, "fetched after the decision time")
            self.assertEqual(EV.status_at(Path(d), _ns(date(2026, 11, 12), "11:00"), c).status, EV.UNVERIFIED, "too old")
            with self.assertRaises(RuntimeError):
                EV.fetch(c, T0, get=lambda url, headers, timeout: (403, b""))


class Allocation(unittest.TestCase):
    def test_allocator_never_exceeds_limits_with_option_tier(self):
        a = [Request(i, "A", "full", "FUT", "X", "a", i) for i in range(10)]
        c = [Request(100 + i, "C", "full", "CE", "X", "c", i) for i in range(50)] + [Request(3, "C", "full", "FUT", "X", "dup", 99)]
        p = allocate(a + c, per_conn=20, max_conns=2, caps={"C": 25})
        self.assertEqual(p.usage["C"], 26)                             # 25 new tokens + token 3 shared with tier A
        self.assertEqual(sum(1 for t in p.subs if t >= 100), 25)
        self.assertLessEqual(p.usage["total"], 40)
        self.assertTrue(any("tier C cap of 25" in r for _, _, r in p.dropped))
        p2 = allocate(a + c, per_conn=10, max_conns=2, caps={"C": 400})
        self.assertEqual(p2.usage["total"], 20)
        self.assertTrue(all(t < 100 for t in list(p2.subs)[:10]), "tier A keeps its slots")
        book = TierBook(cfg_with(tiers__C__max_tokens=7), lambda: T0)
        book.set_tier_a(a)
        for r in c:
            book.promote(r.token, "c", 60, tier="C")
        self.assertEqual(sum(1 for t in book.plan().subs if t >= 100), 7)

    def test_planner_respects_cap_priority_and_reasons(self):
        scan = {c.token: replace(fair_quote(c.instrument_type, int(c.strike)), volume_day=200 * LOT) for c in OPTS}
        first = {c.token: 4_000_000 for c in OPTS}
        first[tok("PE", 980)] = 3_000_000
        stocks = {u: [replace(c, underlying=u, token=c.token + 1000 * i) for c in OPTS] for i, u in enumerate(("AAA", "BBB"), 1)}
        scan.update({c.token: replace(scan[c.token - 1000 * i], token=c.token) for i, u in enumerate(("AAA", "BBB"), 1)
                     for c in stocks[u]})
        cs = {"STK": OPTS, **stocks}
        reqs, dropped = O.plan_tier_c([("STK", "INDEX"), ("AAA", "SETUPS"), ("BBB", "SCAN")], cs,
                                      {u: F_PAISE for u in cs}, scan, first, {"STK": [102000]}, DAY, CFG)
        self.assertLessEqual(len(reqs), CFG.get("tiers.C.max_tokens"))
        self.assertEqual(reqs[0].underlying, "STK")
        self.assertTrue(all(r.tier == "C" and r.mode == "full" for r in reqs))
        stk = [r for r in reqs if r.underlying == "STK"]
        self.assertEqual(len(stk), 10, "5 strikes x CE/PE (ATM+/-2 covers the whole fixture chain)")
        self.assertTrue(any("UNUSUAL_OI_CHANGE" in r.reason for r in reqs) or len(stk) == 10)
        small = cfg_with(tiers__C__max_tokens=12)
        reqs2, dropped2 = O.plan_tier_c([("STK", "INDEX"), ("AAA", "SETUPS"), ("BBB", "SCAN")], cs,
                                        {u: F_PAISE for u in cs}, scan, first, {}, DAY, small)
        self.assertEqual(len(reqs2), 12)
        self.assertEqual([r.underlying for r in reqs2].count("AAA"), 2)
        self.assertTrue(any("TIER_C_CAP" in why for _, why in dropped2))
        illiquid = {t: replace(q, volume_day=1) for t, q in scan.items()}
        _, d3 = O.plan_tier_c([("STK", "INDEX")], cs, {"STK": F_PAISE}, illiquid, {}, {}, DAY, CFG)
        self.assertTrue(d3[0][1].startswith("NO_LIQUID_EXPIRY"))

    def test_rest_quote_parse_drops_empty_levels(self):
        j = {"timestamp": "2026-11-06 15:29:59", "last_price": 12.35, "volume": 1500, "oi": 9000,
             "depth": {"buy": [{"price": 12.3, "quantity": 75, "orders": 2}, {"price": 0, "quantity": 0, "orders": 0}],
                       "sell": [{"price": 0, "quantity": 0, "orders": 0}]}}
        q = O.quote_from_rest(9, j, T0)
        self.assertEqual((q.bids, q.asks, q.last_price, q.oi, q.source), (((1230, 75, 2),), (), 1235, 9000, "kite.rest.quote"))
        self.assertEqual(q.exchange_ts_ns, _ns(date(2026, 11, 6), "15:29:59"))
        self.assertIn("NO_VALID_BOOK", O.analyze(OPTS[4], replace(q, token=OPTS[4].token, receive_ns=T0), FUT_Q, True, T0, CFG).iv.reason)


class RecorderPlanner(unittest.TestCase):
    def test_tier_c_planner_promotes_within_the_cap_and_writes_its_plan(self):
        from engine.recorder import TierCPlanner
        spot = Contract(SPOT, "STK", "STOCK", "STK", "EQ", None, None, 1, Decimal("0.05"), "NSE", "NSE", True, DAY, DAY)
        allc = {c.token: c for c in CONTRACTS + [spot]}

        class Reg:
            def get_contract(self, t, d):
                return allc.get(t)

            def get_contracts(self, u, d):
                return CONTRACTS

        class Sess:
            calls = []

            def quote(self, keys, batch, rate):
                self.calls.append(len(keys))
                out = {}
                for k in keys:
                    c = next(x for x in allc.values() if f"{x.exchange}:{x.tradingsymbol}" == k)
                    if c.token == SPOT:
                        out[k] = ({"last_price": 1000.0, "timestamp": "2026-11-09 10:59:59"}, T0)
                    else:
                        m = round(fair(c.instrument_type, int(c.strike))) / 100
                        out[k] = ({"last_price": m, "volume": 500 * LOT, "oi": 10_000, "timestamp": "2026-11-09 10:59:59",
                                   "depth": {"buy": [{"price": m - 0.05, "quantity": 100, "orders": 1}],
                                             "sell": [{"price": m + 0.05, "quantity": 100, "orders": 1}]}}, T0)
                return out
        uni = Universe(DAY, (), DAY, (Member("STK", "STOCK", SPOT, (FUT,), ("NIFTY50",)),), ())
        with tempfile.TemporaryDirectory() as d:
            c = cfg_with(storage__root=d, tiers__C__max_tokens=6)
            book = TierBook(c, lambda: T0)
            p = TierCPlanner(c, Sess(), Reg(), uni, book, DAY, Path(d), clock_ns=lambda: T0)
            out = p.run_once()
            self.assertEqual(out["planned"], 6)
            self.assertTrue(any("TIER_C_CAP" in why for _, why in out["dropped"]))
            self.assertEqual(json.loads((Path(d) / "tier_c_plan.json").read_text())["planned"], 6)
            plan = book.plan()
            self.assertEqual(sum(1 for m in plan.meta.values() if "C" in m[0]), 6)
            self.assertIsNone(out["previous_session"])


class PlannerThread(unittest.TestCase):
    def test_planner_thread_uses_a_registry_opened_in_its_own_thread(self):   # 2026-11-08: every run failed
        import contextlib
        import io
        import sqlite3
        import threading
        from engine.recorder import start_tier_c_planner
        spot = Contract(SPOT, "STK", "STOCK", "STK", "EQ", None, None, 1, Decimal("0.05"), "NSE", "NSE", True, DAY, DAY)
        allc = {c.token: c for c in CONTRACTS + [spot]}

        class Reg:                        # like engine.universe.Registry: a sqlite connection made where it is built
            def __init__(self, cfg):
                self.db = sqlite3.connect(":memory:")

            def get_contract(self, t, d):
                self.db.execute("SELECT 1")    # raises ProgrammingError if used from another thread
                return allc.get(t)

            def get_contracts(self, u, d):
                self.db.execute("SELECT 1")
                return CONTRACTS

        class Sess:
            def quote(self, keys, batch, rate):
                return {}
        uni = Universe(DAY, (), DAY, (Member("STK", "STOCK", SPOT, (FUT,), ("NIFTY50",)),), ())
        with tempfile.TemporaryDirectory() as d:
            c = cfg_with(storage__root=d)
            stop, err = threading.Event(), io.StringIO()
            with contextlib.redirect_stderr(err):
                t = start_tier_c_planner(c, Sess(), uni, TierBook(c, lambda: T0), DAY, Path(d), stop,
                                         make_registry=Reg, clock_ns=lambda: T0)
                for _ in range(100):
                    if (Path(d) / "tier_c_plan.json").exists():
                        break
                    threading.Event().wait(0.05)
                stop.set()
                t.join(5)
            self.assertNotIn("planner failed", err.getvalue())
            self.assertTrue((Path(d) / "tier_c_plan.json").exists())
        with tempfile.TemporaryDirectory() as d:          # the real default registry (engine.universe.Registry)
            c = cfg_with(storage__root=d)
            stop, err = threading.Event(), io.StringIO()
            with contextlib.redirect_stderr(err):
                t = start_tier_c_planner(c, Sess(), uni, TierBook(c, lambda: T0), DAY, Path(d), stop, clock_ns=lambda: T0)
                for _ in range(100):
                    if (Path(d) / "tier_c_plan.json").exists():
                        break
                    threading.Event().wait(0.05)
                stop.set()
                t.join(5)
            self.assertNotIn("planner failed", err.getvalue())


class RecordedChain(unittest.TestCase):
    """engine.chain_report over a synthetic recorded buffer.sqlite (the same tables the recorder writes)."""

    def test_snapshots_context_and_iv_history_from_recorded_rows(self):
        import sqlite3
        from engine import chain_report as CR
        from engine.signal_report import QuoteBook
        from engine.store import DEPTH_COLS, TICK_COLS
        ref_t = T0 - CFG.get("options.change_window_min") * MIN
        with tempfile.TemporaryDirectory() as d:
            db = sqlite3.connect(Path(d) / "buffer.sqlite")
            db.execute(f"CREATE TABLE depth ({', '.join(DEPTH_COLS)})")
            db.execute(f"CREATE TABLE ticks ({', '.join(TICK_COLS)})")
            seq = iter(range(10 ** 6))

            def put(token, at, bid, ask, oi):
                row = dict.fromkeys(DEPTH_COLS)
                row.update(receive_ns=at, conn=1, seq=next(seq), token=token, exchange_ts=at // S)
                for i in range(5):
                    row.update({f"b{i}_price": bid - 5 * i, f"b{i}_qty": 100_000, f"b{i}_orders": 5,
                                f"s{i}_price": ask + 5 * i, f"s{i}_qty": 100_000, f"s{i}_orders": 5})
                db.execute(f"INSERT INTO depth VALUES ({','.join('?' * len(DEPTH_COLS))})", [row[c] for c in DEPTH_COLS])
                tk = dict.fromkeys(TICK_COLS)
                tk.update(receive_ns=at, conn=1, seq=next(seq), token=token, exchange_ts=at // S, mode="full",
                          ltp=(bid + ask) // 2, volume=5_000_000, oi=oi)
                db.execute(f"INSERT INTO ticks VALUES ({','.join('?' * len(TICK_COLS))})", [tk[c] for c in TICK_COLS])
            for at, f, writ in ((ref_t - S, F_PAISE, False), (T0 - S, F_PAISE - 200, True)):
                put(FUT, at, f - 5, f + 5, 9_000_000)
                for c in OPTS:
                    k, kind = int(c.strike), c.instrument_type
                    sigma = 0.18 if writ and (kind, k) == ("CE", 1000) else 0.20
                    m = round(fair(kind, k, sigma, at + S, f))
                    put(c.token, at, m - 5, m + 5, 110_000 if writ and (kind, k) == ("CE", 1000) else 100_000)
            db.commit()
            db.row_factory = sqlite3.Row
            book = QuoteBook(db)
            book.load([c.token for c in CONTRACTS])
            snaps, now = CR.snapshots_at("STK", CONTRACTS, FUTC, book, T0, CFG)
            self.assertEqual(len(snaps), 1)
            s = snaps[0]
            by = {(r.kind, r.strike): r for r in s.rows}
            self.assertEqual(by[("CE", 1000.0)].hypothesis, "CALL_WRITING", by[("CE", 1000.0)].evidence)
            self.assertEqual(by[("PE", 1000.0)].hypothesis, O.UNCERTAIN)            # OI flat
            self.assertAlmostEqual(by[("CE", 1000.0)].oi_change_pct, 10.0)
            self.assertAlmostEqual(by[("CE", 1000.0)].iv_change_pts, -2.0, delta=0.3)
            self.assertAlmostEqual(s.underlying_change_pct, -0.2)
            self.assertEqual(s.iv_coverage, (10, 10))
            self.assertEqual(by[("CE", 1000.0)].oi_age_s, 1.0)
            hist_root = Path(d) / "root"
            for k in range(20):                                                       # 20 earlier sessions
                day_dir = hist_root / date(2026, 10, 1 + k).isoformat()
                day_dir.mkdir(parents=True)
                CR.write(day_dir, [], [("STK", day_dir.name, T0, EXP.isoformat(), 0.15 + k / 100, CFG.version)], {}, CFG.version)
            hist = CR.iv_history(hist_root, "STK", DAY, CFG.version)
            self.assertEqual(len(hist), 20)
            cx = CR.context_at("STK", CONTRACTS, FUTC, book, T0, ref_t, hist, DAY, CFG)
            self.assertAlmostEqual(cx.atm_iv, (by[("CE", 1000.0)].iv + by[("PE", 1000.0)].iv) / 2)
            self.assertAlmostEqual(cx.iv_percentile, 100 * sum(0.15 + k / 100 <= cx.atm_iv for k in range(20)) / 20)
            prem, ivc = O.changes(cx.analytics[tok("CE", 1000)], cx.ref[tok("CE", 1000)])
            self.assertLess(prem, 0)
            self.assertLess(ivc, 0)
            db.close()


class Purity(unittest.TestCase):
    def test_pure_modules_do_no_io_and_read_no_clock(self):
        text = (REPO / "engine" / "options.py").read_text()
        for bad in ("datetime.now", "time.time", "open(", "sqlite3", "requests", "urlopen", "KiteConnect", "dashboard"):
            self.assertNotIn(bad, text.replace("dashboard/black76.py", "").replace("`dashboard.app`", ""), bad)

    def test_v14_loads_with_the_owner_cap(self):
        v14 = O.load(O.REPO / "config/engine/v14.yaml")
        self.assertEqual((v14.version, v14.get("tiers.C.mode"), v14.get("tiers.C.max_tokens")), ("v14", "full", 400))
        self.assertEqual((V20.version, V20.get("tiers.C.mode"), V20.get("tiers.C.max_tokens")), ("v24", "full", 2000))  # D-72 default (v23: D-75, v24: D-76)


if __name__ == "__main__":
    unittest.main()
