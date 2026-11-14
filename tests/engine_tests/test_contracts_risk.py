"""Phase 7: cost model, contract selector V1, risk engine. Synthetic fixtures only (no live calls)."""

import copy
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import yaml

from engine import contracts as K
from engine import costs as C
from engine import events as EV
from engine import options as O
from engine import risk as R
from engine.candles import MIN, S, _ns
from engine.config import REPO, ConfigError, EngineConfig
from engine.universe import Contract

CFG = K.load()
DAY = date(2026, 11, 6)
T = _ns(DAY, "11:00")
LOT = 100
FUT_NEAR, FUT_NEXT, SPOT = 1001, 1002, 1000


def cfg_with(**patch):
    values = copy.deepcopy(dict(CFG.values))
    for dotted, v in patch.items():
        node, *path = [values] + dotted.split("__")
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = v
    return EngineConfig(CFG.version, CFG.sha256, values)


def contract(tok, typ, exp, strike=None, lot=LOT):
    return Contract(tok, "STK", "STOCK", f"STK{exp:%d%b}{strike or ''}{typ}".upper(), typ, exp,
                    None if strike is None else Decimal(strike), lot, Decimal("0.05"), "NFO-OPT" if strike else "NFO-FUT",
                    "NFO", True, DAY, DAY)


E1, E2, E3 = DAY + timedelta(1), DAY + timedelta(6), DAY + timedelta(13)
FUTS = [contract(FUT_NEAR, "FUT", DAY + timedelta(20)), contract(FUT_NEXT, "FUT", DAY + timedelta(48))]
OPTS = [contract(int(f"{2 + (typ == 'PE')}{i}{k:02d}"), typ, e, 990 + 5 * k)
        for i, e in enumerate((E1, E2, E3)) for typ in ("CE", "PE") for k in range(5)]
CONTRACTS = FUTS + OPTS
TRADABLE = {c.token: (True, []) for c in CONTRACTS}


def tok(typ, exp, strike):
    return next(c.token for c in OPTS if c.instrument_type == typ and c.expiry == exp and c.strike == strike)


def book(bid, ask, qty=500, step=None, levels=5):
    step = step or max(1, ask - bid)
    return (tuple((bid - i * step, qty, 3) for i in range(levels)), tuple((ask + i * step, qty, 3) for i in range(levels)))


def quote(token, bid, ask, qty=500, volume=200_000, oi=100_000, age_s=1, depth=True, levels=5):
    bids, asks = book(bid, ask, qty, levels=levels if depth else 1)
    return K.Quote(token, bids, asks, depth, (bid + ask) // 2, volume, oi, T - age_s * S, T - age_s * S, "fixture")


SETUP_LONG = K.TradeSetup("s1", "STK", 1, DAY, T, FUT_NEAR, 100000, 99000, (103000,), 500.0)
SETUP_SHORT = K.TradeSetup("s2", "STK", -1, DAY, T, FUT_NEAR, 100000, 101000, (97000,), 500.0)
SPOT_Q = K.Quote(SPOT, (), (), False, 100000, None, None, T - S, T - S, "fixture")


def option_quotes(mid=2000, half=10):
    return {c.token: quote(c.token, mid - half, mid + half) for c in OPTS}


def bars(delta_by_token, n=31, seed_und=100000):
    """Underlying 1m closes zig-zag; each option = 2000 + delta x (und - first)."""
    ends = [T - (n - i) * MIN for i in range(n)]
    und = {t: seed_und + (40 if i % 2 else -25) * ((i % 5) + 1) for i, t in enumerate(ends)}
    out = {FUT_NEAR: und}
    for tk, d in delta_by_token.items():
        out[tk] = {t: round(2000 + d * (u - seed_und)) for t, u in und.items()}
    return out


ALL_BARS = bars({c.token: (0.5 if c.instrument_type == "CE" else -0.5) for c in OPTS})
FUT_QUOTES = {FUT_NEAR: quote(FUT_NEAR, 99990, 100010, qty=2000, volume=100_000), FUT_NEXT: quote(FUT_NEXT, 100490, 100510)}


# Selector V2 (Phase 11): options need an event calendar and an IV percentile. These V1 tests pass a verified calendar
# with no events and a percentile of 30 with no Greeks, so the V1 empirical premium model is what they check.
_V14 = yaml.safe_load((REPO / "config/engine/v14.yaml").read_text())
CFG = EngineConfig(CFG.version, CFG.sha256, {**CFG.values, "options": _V14["options"], "events": _V14["events"]})
CLEAR = EV.EventStatus(EV.VERIFIED, "fixture: calendar fetched, no events", T - MIN, "x", "fixture", ())
V1_CHAIN = O.OptionContext("STK", T, {}, (), O.Unavailable("fixture"), 30.0, {})


def select(setup=SETUP_LONG, quotes=None, bars_=ALL_BARS, margins=None, cfg=CFG, contracts=CONTRACTS, spot=SPOT_Q,
           chain=V1_CHAIN, events=CLEAR):
    q = {**FUT_QUOTES, **option_quotes(), **(quotes or {})}
    return K.select_contracts(setup, contracts, TRADABLE, q, spot, bars_, margins or {}, cfg, chain=chain, events=events)


def by_symbol(sel):
    return {c.tradingsymbol: c for c in sel.candidates}


FLAT = R.PortfolioState(T - MIN, DAY, 0.0, 0.0, 0.0, (), 0.0, 0, 0, None)


class CostModel(unittest.TestCase):
    def test_round_trip_matches_hand_computation_from_verified_rates(self):
        e = C.round_trip(CFG, "FUT", "BUY", 1000.0, 1030.0, 100, DAY)
        buy, sell = 100_000.0, 103_000.0
        brk = min(0.0003 * buy, 20) + min(0.0003 * sell, 20)                   # F-COST-1
        exch, sebi, ipft = 0.0000183 * (buy + sell), 0.000001 * (buy + sell), 1e-9 * (buy + sell)
        expected = brk + 0.0005 * sell + exch + sebi + 0.00002 * buy + ipft + 0.18 * (brk + exch + sebi + ipft)
        self.assertEqual(e.status, C.VERIFIED)
        self.assertAlmostEqual(e.total_inr, expected, places=9)
        o = C.round_trip(CFG, "OPT", "BUY", 20.0, 35.0, 300, DAY)
        buy, sell = 6000.0, 10500.0
        exch, sebi, ipft = 0.0003553 * (buy + sell), 0.000001 * (buy + sell), 1e-9 * (buy + sell)
        self.assertAlmostEqual(o.total_inr, 40 + 0.0015 * sell + exch + sebi + 0.00003 * buy + ipft
                               + 0.18 * (40 + exch + sebi + ipft), places=9)

    def test_unverified_rate_or_no_rate_in_force_sets_unverified(self):
        entries = copy.deepcopy(CFG.get("costs.entries"))
        next(e for e in entries if e["product"] == "OPT" and e["component"] == "stt")["verified"] = False
        e = C.round_trip(cfg_with(costs__entries=entries), "OPT", "BUY", 20.0, 35.0, 300, DAY)
        self.assertEqual(e.status, C.UNVERIFIED)
        self.assertIn("SELL stt: OPT rate not verified (F-COST-2)", e.unverified)
        old = C.round_trip(CFG, "FUT", "BUY", 1000.0, 1030.0, 100, date(2026, 3, 2))
        self.assertEqual(old.status, C.UNVERIFIED)
        self.assertTrue(any("stt: no FUT rate in force on 2026-03-02" in u for u in old.unverified))
        # carried to the candidate and to the risk decision
        sel = select(cfg=cfg_with(costs__entries=entries))
        ce = next(c for c in sel.candidates if c.kind == "CE" and c.status == K.ELIGIBLE)
        self.assertIn("UNVERIFIED_COSTS", ce.labels)
        d = R.risk_check(ce, FLAT, cfg_with(costs__entries=entries))
        self.assertEqual(d.status, R.REJECTED)
        self.assertTrue(any(r.startswith("NET_RR_VERIFIED") for r in d.reasons))

    def test_slippage_walks_depth_or_is_estimated_without_depth(self):
        bids, asks = ((990, 100, 1), (980, 100, 1)), ((1010, 100, 1), (1020, 100, 1), (1030, 100, 1))
        f = C.fill(bids, asks, True, "BUY", 250, CFG)
        self.assertEqual((f.avg_price, f.half_spread, f.method, f.covered), ((101000 + 102000 + 51500) / 250, 10, C.DEPTH, True))
        self.assertAlmostEqual(f.impact, f.avg_price - 1010)
        self.assertAlmostEqual(f.per_unit, 10 + f.impact)
        self.assertIsNone(C.fill(bids, asks, True, "SELL", 250, CFG).avg_price, "2 visible bid levels hold 200 < 250")
        g = C.fill(bids[:1], asks[:1], False, "BUY", 250, CFG)
        self.assertEqual((g.method, g.per_unit, g.covered), (C.ESTIMATED, 1.0 * 20, None))


class PremiumModel(unittest.TestCase):
    def test_empirical_delta_recovered_and_rejected_when_not_defensible(self):
        m = K.premium_model(ALL_BARS[OPTS[0].token], ALL_BARS[FUT_NEAR], T, "CE", CFG)
        self.assertAlmostEqual(m.delta, 0.5, places=2)
        self.assertGreater(m.r2, 0.99)
        self.assertIn("APPROXIMATE", m.method)
        self.assertTrue(K.premium_model({}, ALL_BARS[FUT_NEAR], T, "CE", CFG).reason.startswith("NO_PREMIUM_MODEL"))
        wrong = K.premium_model(ALL_BARS[OPTS[0].token], ALL_BARS[FUT_NEAR], T, "PE", CFG)
        self.assertIn("outside the range of a long PE", wrong.reason)
        noisy = {t: 2000 + (300 if i % 3 else -300) for i, t in enumerate(sorted(ALL_BARS[FUT_NEAR]))}
        self.assertIn("NO_PREMIUM_MODEL", K.premium_model(noisy, ALL_BARS[FUT_NEAR], T, "CE", CFG).reason)
        later = {t + 31 * MIN: v for t, v in ALL_BARS[OPTS[0].token].items()}
        self.assertIn("NO_PREMIUM_MODEL", K.premium_model(later, ALL_BARS[FUT_NEAR], T, "CE", CFG).reason,
                      "bars after the decision time are never used")


class Selector(unittest.TestCase):
    def test_missing_premium_model_option_no_trade_futures_still_evaluated(self):
        sel = select(bars_={FUT_NEAR: ALL_BARS[FUT_NEAR]}, margins={FUT_NEAR: 30000.0})
        opts = [c for c in sel.candidates if c.kind in K.OPTION_KINDS]
        self.assertEqual(len(opts), 6)   # ATM, ITM and (V2) OTM on two expiries
        self.assertTrue(all(c.status == K.NO_TRADE and c.reasons[0].startswith("NO_PREMIUM_MODEL") for c in opts))
        fut = next(c for c in sel.candidates if c.kind == "FUT")
        self.assertEqual((fut.status, fut.tradingsymbol, fut.capital_method), (K.ELIGIBLE, FUTS[0].tradingsymbol, "MARGIN_API"))
        self.assertEqual(sel.decision, "CANDIDATES")
        self.assertEqual(sel.candidates[0], fut)

    def test_wide_spread_option_excluded(self):
        atm = tok("CE", E2, 1000)
        sel = select(quotes={atm: quote(atm, 1900, 2100)})
        c = by_symbol(sel)[next(x.tradingsymbol for x in OPTS if x.token == atm)]
        self.assertEqual(c.status, K.EXCLUDED)
        self.assertTrue(any(r.startswith("SPREAD_TOO_WIDE") for r in c.reasons), c.reasons)

    def test_no_short_option_candidate_is_ever_generated(self):
        for setup in (SETUP_LONG, SETUP_SHORT):
            sel = select(setup=setup)
            opts = [c for c in sel.candidates if c.kind in K.OPTION_KINDS]
            self.assertTrue(opts)
            self.assertEqual({(c.kind, c.side) for c in opts}, {("CE" if setup.direction > 0 else "PE", "BUY")})
        short_fut = next(c for c in select(setup=SETUP_SHORT).candidates if c.kind == "FUT")
        self.assertEqual(short_fut.side, "SELL")
        any_opt = next(c for c in select().candidates if c.kind == "CE")
        with self.assertRaises(ValueError):
            replace(any_opt, side="SELL")

    def test_strikes_expiries_and_rollover_come_from_the_registry(self):
        sel = select()
        opts = [c for c in sel.candidates if c.kind == "CE"]
        self.assertEqual(sorted((c.expiry, c.strike, c.role) for c in opts),
                         [(E2, 995.0, "ITM"), (E2, 1000.0, "ATM"), (E2, 1005.0, "OTM"),
                          (E3, 995.0, "ITM"), (E3, 1000.0, "ATM"), (E3, 1005.0, "OTM")])
        self.assertTrue(any("EXPIRY_TOO_CLOSE (dte 1 < 2)" in n for n in sel.notes))
        puts = [c for c in select(setup=SETUP_SHORT).candidates if c.kind == "PE"]
        self.assertEqual(sorted({(c.strike, c.role) for c in puts}), [(995.0, "OTM"), (1000.0, "ATM"), (1005.0, "ITM")],
                         "ITM put = one strike above ATM, OTM put = one below")
        tie = replace(SPOT_Q, last_price=99750)     # midway 995 / 1000: the ITM side wins for a call
        self.assertEqual(sorted({c.strike for c in select(spot=tie).candidates if c.kind == "CE"}), [990.0, 995.0, 1000.0])
        late = replace(SETUP_LONG, day=FUTS[0].expiry - timedelta(2))
        roll = K.select_contracts(late, CONTRACTS, TRADABLE, {**FUT_QUOTES}, None, {}, {}, CFG)
        self.assertEqual([c.token for c in roll.candidates if c.kind == "FUT"], [FUT_NEXT])
        self.assertIn("BASIS_ASSUMED_CONSTANT", roll.candidates[0].labels)
        self.assertTrue(any("rollover window (dte 2 <= 3); next month used" in n for n in roll.notes), roll.notes)

    def test_ranking_is_net_rr_times_liquidity_never_cheap_premium(self):
        e2_itm, e2_atm = tok("CE", E2, 995), tok("CE", E2, 1000)
        q = {e2_atm: quote(e2_atm, 990, 1010), e2_itm: quote(e2_itm, 2990, 3010, qty=60)}  # ATM cheaper; ITM thin book
        sel = select(quotes=q)
        elig = [c for c in sel.candidates if c.status == K.ELIGIBLE]
        self.assertEqual([c.score for c in elig], sorted((c.score for c in elig), reverse=True))
        for c in elig:
            self.assertAlmostEqual(c.score, c.rr_net * c.liquidity_score)
        itm = next(c for c in elig if c.token == e2_itm)
        self.assertLess(itm.liquidity_score, 1.0)
        tied = [replace(c, score=1.0) for c in elig]
        self.assertEqual(sorted(tied, key=lambda c: (-c.score, c.required_capital_inr))[0].required_capital_inr,
                         min(c.required_capital_inr for c in tied))

    def test_exclusions_are_named(self):
        atm = tok("CE", E2, 1000)
        c = by_symbol(select(quotes={atm: quote(atm, 1990, 2010, volume=1000, oi=None, age_s=60)}))
        sym = lambda t: next(x.tradingsymbol for x in OPTS if x.token == t)  # noqa: E731
        self.assertTrue(c[sym(atm)].reasons[0].startswith("DATA_NOT_OK:STALE_QUOTE"))
        c = by_symbol(select(quotes={atm: quote(atm, 1990, 2010, volume=1000, oi=None)}))[sym(atm)]
        self.assertIn("ILLIQUID:OI_UNAVAILABLE", c.reasons)
        self.assertTrue(any(r.startswith("ILLIQUID:VOLUME") for r in c.reasons))
        restricted = {**TRADABLE, atm: (False, ["BANNED"])}
        sel = K.select_contracts(SETUP_LONG, CONTRACTS, restricted, {**FUT_QUOTES, **option_quotes()}, SPOT_Q, ALL_BARS, {}, CFG)
        self.assertIn("RESTRICTED:BANNED", by_symbol(sel)[sym(atm)].reasons)
        fut = next(x for x in select().candidates if x.kind == "FUT")
        self.assertTrue(any(r.startswith("CAPITAL_ABOVE_LIMIT") for r in fut.reasons), "full-notional margin estimate")
        self.assertIn("MARGIN_ESTIMATED", fut.labels)
        wide = by_symbol(select(quotes={atm: quote(atm, 1990, 2010)}, setup=replace(SETUP_LONG, targets=(100200,))))[sym(atm)]
        self.assertTrue(any(r.startswith("SPREAD_VS_MOVE_TOO_WIDE") for r in wide.reasons), wide.reasons)
        none = select(quotes={t: None for t in TRADABLE}, margins={FUT_NEAR: 1.0})
        self.assertEqual(none.decision, "NO_TRADE")

    def test_risk_measures_options_full_premium_futures_gap(self):
        sel = select(margins={FUT_NEAR: 30000.0})
        opt = next(c for c in sel.candidates if c.kind == "CE" and c.status == K.ELIGIBLE)
        self.assertLessEqual(opt.planned_risk_inr, CFG.get("risk.max_risk_per_trade_inr"))
        self.assertAlmostEqual(opt.full_premium_at_risk_inr, opt.entry * opt.quantity / 100 + opt.costs_at_stop.total_inr)
        self.assertAlmostEqual(opt.required_capital_inr, opt.entry * opt.quantity / 100)
        self.assertGreater(opt.full_premium_at_risk_inr, opt.planned_risk_inr)
        bigger = K._evaluate(SETUP_LONG, next(c for c in OPTS if c.token == opt.token), TRADABLE,
                             option_quotes()[opt.token], ALL_BARS, {}, cfg_with(risk__max_risk_per_trade_inr=10 ** 6))
        self.assertGreater(bigger.lots, opt.lots, "size comes from planned risk")
        fut = next(c for c in sel.candidates if c.kind == "FUT")
        self.assertAlmostEqual(fut.gap_risk_inr - fut.planned_risk_inr, 1.0 * 500.0 * fut.quantity / 100)
        self.assertAlmostEqual(fut.planned_risk_inr, (fut.entry - (99000 - fut.exit_fill.per_unit)) * fut.quantity / 100
                               + fut.costs_at_stop.total_inr)
        self.assertEqual((fut.receive_ns, fut.processed_ns, fut.age_s, fut.config_version), (T - S, T, 1.0, "v9"))


class Risk(unittest.TestCase):
    def eligible(self):
        return next(c for c in select(margins={FUT_NEAR: 30000.0}).candidates if c.status == K.ELIGIBLE)

    def test_capital_above_limit_rejected(self):
        c = self.eligible()
        d = R.risk_check(c, FLAT, cfg_with(risk__max_capital_per_trade_inr=c.required_capital_inr - 1))
        self.assertEqual(d.status, R.REJECTED)
        self.assertTrue(any(r.startswith("CAPITAL_ABOVE_LIMIT") for r in d.reasons))
        self.assertIsNone(d.token)
        o = next(x for x in select().candidates if x.kind == "CE" and x.status == K.ELIGIBLE)
        between = cfg_with(risk__max_capital_per_trade_inr=(o.required_capital_inr + o.full_premium_at_risk_inr) / 2)
        self.assertTrue(any(r.startswith("CAPITAL_ABOVE_LIMIT") for r in R.risk_check(o, FLAT, between).reasons),
                        "options: the capital check uses the full premium + costs, not premium x qty")
        fut = next(x for x in select().candidates if x.kind == "FUT")     # MARGIN_ESTIMATED full notional
        self.assertTrue(any(r.startswith("CAPITAL_ABOVE_LIMIT") for r in R.risk_check(fut, FLAT, CFG).reasons))

    def test_daily_loss_breach_rejects_every_candidate_for_the_day(self):
        cands = select(margins={FUT_NEAR: 30000.0}).candidates
        hit = replace(FLAT, realized_pnl_inr=-4000.0, unrealized_pnl_inr=-2000.0, worst_day_pnl_inr=-6000.0)
        later = replace(hit, as_of=T, unrealized_pnl_inr=+1500.0)   # recovered since, still breached today
        for state in (hit, later):
            for c in cands:
                d = R.risk_check(c, state, CFG)
                self.assertEqual(d.status, R.REJECTED)
                self.assertTrue(any(r.startswith("DAILY_LOSS_LIMIT") for r in d.reasons), c.id)
        self.assertEqual(R.risk_check(self.eligible(), FLAT, CFG).status, R.APPROVED)

    def test_every_check_is_named(self):
        c = self.eligible()
        cases = {
            "MAX_OPEN_POSITIONS": replace(FLAT, open_underlyings=("A", "B", "C")),
            "MAX_DAILY_TRADES": replace(FLAT, trades_today=5),
            "CONSECUTIVE_LOSSES_COOLDOWN": replace(FLAT, consecutive_losses=3, last_loss_ns=T - 10 * MIN),
            "SINGLE_POSITION_PER_UNDERLYING": replace(FLAT, open_underlyings=("STK",)),
            "CAPITAL_RESERVE": replace(FLAT, capital_in_use_inr=159_000.0),
            "PORTFOLIO_STATE": replace(FLAT, day=DAY - timedelta(1)),
        }
        for name, state in cases.items():
            d = R.risk_check(c, state, CFG)
            self.assertEqual([r.split(":")[0] for r in d.reasons], [name], name)
        self.assertEqual(R.risk_check(c, replace(FLAT, consecutive_losses=3, last_loss_ns=T - 61 * MIN), CFG).status, R.APPROVED)
        late = replace(c, as_of=_ns(DAY, "15:00"))
        self.assertIn("INTRADAY_CUTOFF", [r.split(":")[0] for r in R.risk_check(late, FLAT, CFG).reasons])
        self.assertIn("EVENT_DAY", [r.split(":")[0] for r in R.risk_check(c, FLAT, cfg_with(risk__event_days=[DAY])).reasons])
        self.assertIn("EXPIRY_DAY", [r.split(":")[0] for r in R.risk_check(replace(c, expiry=DAY), FLAT, CFG).reasons])
        self.assertIn("MIN_NET_RR", [r.split(":")[0] for r in R.risk_check(c, FLAT, cfg_with(risk__min_rr_net=99)).reasons])
        self.assertIn("MAX_SLIPPAGE", [r.split(":")[0] for r in R.risk_check(c, FLAT, cfg_with(
            risk__max_slippage_pct={"FUT": 0.0, "OPT": 0.0})).reasons])
        self.assertIn("CONFIG_VERSION", [r.split(":")[0] for r in R.risk_check(replace(c, config_version="v8"), FLAT, CFG).reasons])
        self.assertTrue(all(k.name and k.detail for k in R.risk_check(c, FLAT, CFG).checks))

    def test_recommendation_requires_an_approval_token_from_risk_check(self):
        c = self.eligible()
        with self.assertRaises(PermissionError):
            R.Recommendation(c, None)
        with self.assertRaises(PermissionError):
            R.ApprovalToken(object(), c.id, c.config_version, c.as_of)
        d = R.risk_check(c, FLAT, CFG)
        self.assertEqual((d.status, d.config_version), (R.APPROVED, "v9"))
        self.assertEqual(R.Recommendation(c, d.token).approval.candidate_id, c.id)
        other = next(x for x in select(margins={FUT_NEAR: 30000.0}).candidates if x.id != c.id and x.status == K.ELIGIBLE)
        with self.assertRaises(PermissionError):
            R.Recommendation(other, d.token)
        with self.assertRaises(AttributeError):
            d.token.candidate_id = other.id
        rejected = R.risk_check(c, replace(FLAT, trades_today=99), CFG)
        self.assertIsNone(rejected.token)


class ConfigAndPurity(unittest.TestCase):
    def test_v9_loads_and_missing_key_fails(self):
        self.assertEqual(CFG.version, "v9")
        values = yaml.safe_load((REPO / "config/engine/v9.yaml").read_text())
        del values["risk"]["min_rr_net"]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "v.yaml"
            p.write_text(yaml.safe_dump(values))
            with self.assertRaises(ConfigError):
                K.load(p)

    def test_pure_modules_do_no_io_and_read_no_clock(self):
        for name in ("costs", "contracts", "risk"):
            text = (REPO / "engine" / f"{name}.py").read_text()
            for bad in ("datetime.now", "time.time", "open(", "sqlite3", "requests", "urlopen", "KiteConnect"):
                self.assertNotIn(bad, text, f"{name}.py: {bad}")


if __name__ == "__main__":
    unittest.main()
