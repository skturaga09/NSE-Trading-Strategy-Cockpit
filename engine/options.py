"""Phase 11 option-chain intelligence (pure): IV and Greeks, chain metrics, positioning hypotheses, IV percentile, the
Phase 8 options factor and the tier C subscription planner. No clock, disk or network: time is always an input.

IV model: Black-76 on the option's SAME-EXPIRY future (F-OPT-1/2: NSE index and stock options are European). The future
price already carries dividends and cost of carry, so no dividend forecast is needed; the rate only discounts the payoff.
The rate is the RBI 91-day T-bill cut-off YTM (F-RATE-RBI-1, simple annualised) converted to continuous compounding.
An expiry with no listed same-expiry future (weekly index options) => IV UNAVAILABLE (NO_SAME_EXPIRY_FUTURE, Q-11-4).
`dashboard/black76.py` is not imported: it pulls in `dashboard.app` (mock order routes) and reads kite_config.json at import
(Q-11-12); the formulas here reproduce its values on the same textbook references (tests).

IV is computed only from the MID of a fresh two-sided book with spread <= options.iv_max_spread_pct, inside the
no-arbitrage bounds, with a converging solver. Never from LTP. Time to expiry is in trading-calendar years.

Labels describe data. Rising OI is not institutional buying, pending quantities are not volume, 5 visible levels are not a
full book, and a strike's OI concentration is a hypothesis with its evidence, never "resistance".
Prices are paise (exchange integers); Black-76 works in rupees. IV is a decimal (0.20 = 20 %).
"""

import math
from dataclasses import dataclass, replace as _replace
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping

from .candles import IST, MIN, S, Unavailable, _ns
from .config import REPO, load_config
from .contracts import OPTION_KINDS, Quote, quote_problem
from .costs import require
from .tiers import Request

DEFAULT_CONFIG = REPO / "config" / "engine" / "v24.yaml"   # D-72: same config as engine.signals (IV history is keyed by version)
REQUIRED = ["restrictions.holidays", "restrictions.holiday_years", "restrictions.special_sessions",
            "sessions.fno.open", "sessions.fno.close", "quality.stale_depth_s", "quality.stale_oi_s",
            "tiers.C.mode", "tiers.C.max_tokens", "events.url", "events.max_age_days", "events.option_block_trading_days",
            "http.user_agent", "http.timeout_s"] + [f"options.{k}" for k in (
                "model", "risk_free.ytm_pct", "risk_free.tenor_days", "risk_free.as_of", "risk_free.source",
                "risk_free.max_age_days", "trading_days_per_year", "iv_solver", "iv_max_spread_pct", "iv_pct_min_sessions",
                "iv_pct_max_long", "change_window_min", "chain_strikes", "hypothesis", "factor_strikes", "factor_min_labels",
                "holding_min", "expiry_sensitive_theta_pct", "snapshot_interval_min", "planner")]

UNCERTAIN = "UNCERTAIN"
HEDGE = "SPREAD_OR_HEDGE_SUSPECTED"
BULLISH = {("CE", "CALL_BUYING"), ("PE", "PUT_WRITING"), ("CE", "SHORT_COVERING"), ("PE", "LONG_LIQUIDATION")}
BEARISH = {("PE", "PUT_BUYING"), ("CE", "CALL_WRITING"), ("PE", "SHORT_COVERING"), ("CE", "LONG_LIQUIDATION")}
SUPPORTIVE, NEUTRAL, CONTRADICTING = "SUPPORTIVE", "NEUTRAL", "CONTRADICTING"
CHAIN_LABELS = ("HYPOTHESES_NOT_FACTS", "OI_IS_OPEN_CONTRACTS_NOT_BUYING", "DEPTH_IS_PENDING_QTY_5_LEVELS")


def load(path=DEFAULT_CONFIG):
    return require(load_config(path), REQUIRED, path)


def _u(x) -> bool:
    return isinstance(x, Unavailable)


# ---------------------------------------------------------------- time, rate, Black-76
def _trading(d: date, cfg) -> bool:
    r = cfg.get("restrictions")
    return d.weekday() < 5 and all(h["date"] != d for h in r["holidays"]) and all(s["date"] != d for s in r["special_sessions"])


def trading_years(as_of: int, expiry: date, cfg) -> float | Unavailable:
    """Remaining trading time to the expiry-day F&O close, in trading-calendar years: the rest of today's session (if a
    trading day) + every later trading day through the expiry day, / options.trading_days_per_year. Weekends and special
    sessions count as non-trading. A year without a verified holiday circular => UNAVAILABLE (Q-2-3)."""
    now = datetime.fromtimestamp(as_of / S, IST)
    d0 = now.date()
    if expiry < d0:
        return Unavailable(f"EXPIRED: expiry {expiry} before {d0}")
    missing = [y for y in range(d0.year, expiry.year + 1) if y not in cfg.get("restrictions.holiday_years")]
    if missing:
        return Unavailable(f"T_UNAVAILABLE: no verified F&O holiday circular for {missing} (Q-2-3)")
    o, c = _ns(d0, cfg.get("sessions.fno.open")), _ns(d0, cfg.get("sessions.fno.close"))
    today = (c - min(max(as_of, o), c)) / (c - o) if _trading(d0, cfg) else 0.0
    later = sum(_trading(d0 + timedelta(k), cfg) for k in range(1, (expiry - d0).days + 1))
    t = (today + later) / cfg.get("options.trading_days_per_year")
    return t if t > 0 else Unavailable("T_ZERO: at or past the expiry-day close")


def risk_free(as_of: int, cfg) -> float | Unavailable:
    """Continuous rate from the configured T-bill YTM (simple annualised over tenor_days, F-RATE-RBI-1)."""
    rf = cfg.get("options.risk_free")
    age = (datetime.fromtimestamp(as_of / S, IST).date() - rf["as_of"]).days
    if age < 0:
        return Unavailable(f"RATE_AFTER_DECISION_TIME: auction {rf['as_of']}")
    if age > rf["max_age_days"]:
        return Unavailable(f"RATE_STALE: auction {rf['as_of']} is {age} days old > {rf['max_age_days']}")
    n = rf["tenor_days"]
    return math.log(1 + rf["ytm_pct"] / 100 * n / 365) * 365 / n


def _ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _d1d2(F, K, T, sigma):
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    return d1, d1 - v


def black76(F: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    """Black-76 price of a European option on a future (rupees)."""
    disc = math.exp(-r * T)
    d1, d2 = _d1d2(F, K, T, sigma)
    return disc * (F * _ncdf(d1) - K * _ncdf(d2)) if is_call else disc * (K * _ncdf(-d2) - F * _ncdf(-d1))


def bounds(F: float, K: float, T: float, r: float, is_call: bool) -> tuple[float, float]:
    """No-arbitrage bounds for a European option on a future: (discounted intrinsic, discounted F or K)."""
    disc = math.exp(-r * T)
    return (disc * max(F - K, 0.0), disc * F) if is_call else (disc * max(K - F, 0.0), disc * K)


def implied_vol(price: float, F: float, K: float, T: float, r: float, is_call: bool, cfg) -> float | Unavailable:
    lo_b, hi_b = bounds(F, K, T, r, is_call)
    if not lo_b < price < hi_b:
        return Unavailable(f"OUTSIDE_NO_ARBITRAGE_BOUNDS: mid {price:.2f} not in ({lo_b:.2f}, {hi_b:.2f}) INR")
    s = cfg.get("options.iv_solver")
    lo, hi, tol = s["min"], s["max"], s["tol_paise"] / 100
    if black76(F, K, T, r, lo, is_call) > price or black76(F, K, T, r, hi, is_call) < price:
        return Unavailable(f"SOLVER_NO_BRACKET: price outside the model range for IV in [{lo}, {hi}]")
    for _ in range(s["max_iter"]):
        mid = (lo + hi) / 2
        p = black76(F, K, T, r, mid, is_call)
        if abs(p - price) <= tol:
            return mid
        lo, hi = (mid, hi) if p < price else (lo, mid)
    return Unavailable(f"SOLVER_NO_CONVERGENCE after {s['max_iter']} iterations")


@dataclass(frozen=True)
class Greeks:
    delta: float                    # per 1 INR of the future
    gamma: float                    # per 1 INR of the future, per 1 INR
    theta: float                    # INR per trading day (negative = the premium decays)
    vega: float                     # INR per 1 IV point


def greeks(F: float, K: float, T: float, r: float, sigma: float, is_call: bool, cfg) -> Greeks:
    d1, _ = _d1d2(F, K, T, sigma)
    disc, pdf, sq = math.exp(-r * T), math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi), math.sqrt(T)
    dv_dt = -r * black76(F, K, T, r, sigma, is_call) + disc * F * pdf * sigma / (2 * sq)
    return Greeks(disc * (_ncdf(d1) if is_call else _ncdf(d1) - 1), disc * pdf / (F * sigma * sq),
                  -dv_dt / cfg.get("options.trading_days_per_year"), disc * F * pdf * sq / 100)


# ---------------------------------------------------------------- one contract
@dataclass(frozen=True)
class ContractAnalytics:
    token: int
    kind: str
    strike: float                   # INR
    expiry: date
    mid: float | Unavailable        # paise
    spread_pct: float | Unavailable
    future_price: float | Unavailable   # paise: same-expiry future mid
    t_years: float | Unavailable
    rate: float | Unavailable
    iv: float | Unavailable
    greeks: Greeks | Unavailable
    method: str
    source: str | None
    exchange_ts_ns: int | None
    receive_ns: int | None
    processed_ns: int               # = as_of
    age_s: float | None


def analyze(c, q: Quote | None, fut: Quote | None, has_future: bool, as_of: int, cfg) -> ContractAnalytics:
    """c: registry Contract (CE/PE); q: its quote; fut: the same-expiry future's quote; has_future: one is listed."""
    bad = Unavailable
    base = dict(token=c.token, kind=c.instrument_type, strike=float(c.strike), expiry=c.expiry,
                method=cfg.get("options.model"), processed_ns=as_of, source=None if q is None else q.source,
                exchange_ts_ns=None if q is None else q.exchange_ts_ns, receive_ns=None if q is None else q.receive_ns,
                age_s=None if q is None else (as_of - q.receive_ns) / S)
    empty = dict(mid=bad("NO_MID"), spread_pct=bad("NO_MID"), future_price=bad("NOT_REACHED"),
                 t_years=bad("NOT_REACHED"), rate=bad("NOT_REACHED"))

    def out(reason=None, iv=None, greeks=None, **kw):
        why = bad(reason) if reason else None
        return ContractAnalytics(**base, **{**empty, **kw}, iv=why or iv, greeks=why or greeks)

    p = quote_problem(q, as_of, cfg.get("quality.stale_depth_s"))
    if p:
        return out(f"NO_VALID_BOOK: {p} (IV is never computed from LTP)")
    bid, ask = q.bids[0][0], q.asks[0][0]
    mid, spread = (bid + ask) / 2, (ask - bid) / ((bid + ask) / 2) * 100
    m = dict(mid=mid, spread_pct=spread)
    if spread > cfg.get("options.iv_max_spread_pct"):
        return out(f"SPREAD_TOO_WIDE_FOR_IV: {spread:.1f} % > {cfg.get('options.iv_max_spread_pct')} % (not computed from LTP)", **m)
    if not has_future:
        return out(f"NO_SAME_EXPIRY_FUTURE: no listed future expiring {c.expiry} (Q-11-4)", **m)
    fp = quote_problem(fut, as_of, cfg.get("quality.stale_depth_s"))
    if fp:
        return out(f"NO_FUTURE_PRICE: {fp}", **m)
    F = (fut.bids[0][0] + fut.asks[0][0]) / 2
    T, r = trading_years(as_of, c.expiry, cfg), risk_free(as_of, cfg)
    m.update(future_price=F, t_years=T, rate=r)
    for x in (T, r):
        if _u(x):
            return out(x.reason, **m)
    iv = implied_vol(mid / 100, F / 100, float(c.strike), T, r, c.instrument_type == "CE", cfg)
    if _u(iv):
        return out(iv.reason, **m)
    return out(None, **m, iv=iv, greeks=greeks(F / 100, float(c.strike), T, r, iv, c.instrument_type == "CE", cfg))


def premium_at(mid: float, g: Greeks, d_und_paise: float, hold_days: float) -> float:
    """Delta-gamma-theta estimate of the premium (paise) after the future moves d_und and hold_days pass. APPROXIMATE:
    second order in the move, IV assumed unchanged."""
    ds = d_und_paise / 100
    return mid + 100 * (g.delta * ds + 0.5 * g.gamma * ds * ds + g.theta * hold_days)


def changes(now: ContractAnalytics | None, ref: ContractAnalytics | None) -> tuple:
    """(premium change %, IV change in IV points) between two analytics of one contract, or UNAVAILABLE."""
    if now is None or ref is None:
        return (Unavailable("NO_OPTION_HISTORY: no analytics at one of the two times"),) * 2
    prem = Unavailable(f"PREMIUM_UNAVAILABLE: {(now.mid if _u(now.mid) else ref.mid).reason}") \
        if _u(now.mid) or _u(ref.mid) or not ref.mid else (now.mid - ref.mid) / ref.mid * 100
    ivc = Unavailable(f"IV_UNAVAILABLE: {(now.iv if _u(now.iv) else ref.iv).reason}") \
        if _u(now.iv) or _u(ref.iv) else (now.iv - ref.iv) * 100
    return prem, ivc


# ---------------------------------------------------------------- positioning hypotheses
def _sign(x: float, lim: float) -> int:
    return 1 if x >= lim else -1 if x <= -lim else 0


def hypothesis(kind: str, oi_chg_pct, prem_chg_pct, iv_chg_pts, und_chg_pct, cfg) -> tuple[str, tuple]:
    """One strike's hypothesis from OI change + premium change + IV change + underlying move TOGETHER. Any input
    UNAVAILABLE, or a pattern that is not fully corroborated, => UNCERTAIN. OI and premium alone never label anything."""
    ins = {"OI": oi_chg_pct, "premium": prem_chg_pct, "IV": iv_chg_pts, "underlying": und_chg_pct}
    missing = [f"{k}: {v.reason}" for k, v in ins.items() if _u(v)]
    if missing:
        return UNCERTAIN, tuple(missing)
    h = cfg.get("options.hypothesis")
    oi, p = _sign(oi_chg_pct, h["min_oi_chg_pct"]), _sign(prem_chg_pct, h["min_premium_chg_pct"])
    iv, u = _sign(iv_chg_pts, h["min_iv_chg_pts"]), _sign(und_chg_pct, h["min_underlying_chg_pct"])
    ev = (f"OI {oi_chg_pct:+.2f} %", f"premium {prem_chg_pct:+.2f} %", f"IV {iv_chg_pts:+.2f} pts", f"underlying {und_chg_pct:+.3f} %")
    up = 1 if kind == "CE" else -1           # the underlying direction that lifts this option's premium
    if oi > 0 and p > 0 and iv > 0 and u == up:
        return ("CALL_BUYING" if kind == "CE" else "PUT_BUYING"), ev
    if oi > 0 and p < 0 and iv < 0 and u != up:
        return ("CALL_WRITING" if kind == "CE" else "PUT_WRITING"), ev
    if oi < 0 and p > 0 and iv >= 0 and u == up:
        return "SHORT_COVERING", ev
    if oi < 0 and p < 0 and iv <= 0 and u == -up:
        return "LONG_LIQUIDATION", ev
    return UNCERTAIN, ev + ("pattern not corroborated by all four inputs",)


# ---------------------------------------------------------------- chain snapshot
@dataclass(frozen=True)
class StrikeRow:
    token: int
    kind: str
    strike: float
    oi: int | Unavailable
    oi_change: int | Unavailable
    oi_change_pct: float | Unavailable
    oi_age_s: float | Unavailable
    volume_day: int | Unavailable
    premium: float | Unavailable          # mid, paise
    premium_change_pct: float | Unavailable
    spread_pct: float | Unavailable
    depth_bid_qty: int | Unavailable       # pending quantity in the 5 visible levels
    depth_ask_qty: int | Unavailable
    iv: float | Unavailable
    iv_change_pts: float | Unavailable
    greeks: Greeks | Unavailable
    hypothesis: str
    evidence: tuple
    source: str | None
    exchange_ts_ns: int | None
    receive_ns: int | None
    age_s: float | None


@dataclass(frozen=True)
class ChainSnapshot:
    underlying: str
    expiry: date
    as_of: int
    ref_as_of: int
    atm_strike: float | Unavailable
    underlying_price: float | Unavailable      # paise (the caller's reference: same-expiry future mid or spot LTP)
    underlying_change_pct: float | Unavailable
    rows: tuple
    pcr_oi: float | Unavailable                # sum PE OI / sum CE OI over ATM +/- chain_strikes
    pcr_volume: float | Unavailable
    concentration: dict                        # {CE|PE: (strike, share of the range's OI) | UNAVAILABLE}
    concentration_change: dict                 # {CE|PE: share change in points | UNAVAILABLE}
    iv_coverage: tuple                         # (rows with IV, rows)
    labels: tuple
    config_version: str


def _oi(obs: Mapping, tok: int, as_of: int, cfg):
    """obs: {token: (oi, receive_ns)} -> (oi, age_s) or UNAVAILABLE (missing, after as_of or older than stale_oi_s)."""
    o = obs.get(tok)
    if o is None or o[0] is None:
        return Unavailable("NO_OI")
    if o[1] > as_of:
        return Unavailable("OI_AFTER_DECISION_TIME")
    age = (as_of - o[1]) / S
    return Unavailable(f"OI_STALE ({age:.0f} s > {cfg.get('quality.stale_oi_s')} s)") if age > cfg.get("quality.stale_oi_s") \
        else (o[0], age)


def _range(strikes: list[float], atm: float, n: int) -> set:
    i = strikes.index(atm)
    return set(strikes[max(0, i - n): i + n + 1])


def _conc(rows, kind, rng, field):
    vals = [(r.strike, getattr(r, field)) for r in rows if r.kind == kind and r.strike in rng]
    if not vals or any(_u(v) for _, v in vals):
        return Unavailable(f"{kind} {field} missing at {sum(_u(v) for _, v in vals)} of {len(vals)} strikes")
    tot = sum(v for _, v in vals)
    if not tot:
        return Unavailable(f"{kind} {field} total is 0")
    k, v = max(vals, key=lambda x: (x[1], -x[0]))
    return k, v / tot


def chain_snapshot(underlying: str, expiry: date, contracts, now: Mapping[int, ContractAnalytics],
                   ref: Mapping[int, ContractAnalytics], oi_now: Mapping, oi_ref: Mapping, volume: Mapping,
                   depth: Mapping, und_now, und_ref, as_of: int, cfg) -> ChainSnapshot:
    """contracts: the expiry's CE/PE registry rows; now/ref: analytics at as_of and at as_of - change_window_min;
    oi_now/oi_ref: {token: (oi, receive_ns)}; volume: {token: day volume}; depth: {token: (bid qty, ask qty)};
    und_now/und_ref: underlying reference price (paise) at both times, or UNAVAILABLE."""
    ref_as_of = as_of - cfg.get("options.change_window_min") * MIN
    und_chg = Unavailable("UNDERLYING_PRICE_UNAVAILABLE") if _u(und_now) or _u(und_ref) or not und_ref \
        else (und_now - und_ref) / und_ref * 100
    rows = []
    for c in sorted(contracts, key=lambda c: (float(c.strike), c.instrument_type)):
        a, b = now.get(c.token), ref.get(c.token)
        o_now, o_ref = _oi(oi_now, c.token, as_of, cfg), _oi(oi_ref, c.token, ref_as_of, cfg)
        if _u(o_now) or _u(o_ref):
            d_oi = d_pct = Unavailable(f"OI_CHANGE_UNAVAILABLE: {(o_now if _u(o_now) else o_ref).reason}")
        else:
            d_oi = o_now[0] - o_ref[0]
            d_pct = d_oi / o_ref[0] * 100 if o_ref[0] else Unavailable("OI_ZERO_AT_REFERENCE")
        prem_chg, iv_chg = changes(a, b)
        hyp, ev = hypothesis(c.instrument_type, d_pct, prem_chg, iv_chg, und_chg, cfg)
        na = Unavailable("NO_ANALYTICS")
        dq = depth.get(c.token)
        rows.append(StrikeRow(
            c.token, c.instrument_type, float(c.strike), o_now if _u(o_now) else o_now[0], d_oi, d_pct,
            o_now if _u(o_now) else o_now[1],
            Unavailable("NO_VOLUME") if volume.get(c.token) is None else volume[c.token],
            na if a is None else a.mid, prem_chg, na if a is None else a.spread_pct,
            Unavailable("NO_DEPTH") if dq is None else dq[0], Unavailable("NO_DEPTH") if dq is None else dq[1],
            na if a is None else a.iv, iv_chg, na if a is None else a.greeks, hyp, ev,
            None if a is None else a.source, None if a is None else a.exchange_ts_ns,
            None if a is None else a.receive_ns, None if a is None else a.age_s))
    # SPREAD_OR_HEDGE_SUSPECTED: CE and PE OI both rising at one strike by comparable amounts
    lo, hi = cfg.get("options.hypothesis.hedge_ratio_band")
    m = cfg.get("options.hypothesis.min_oi_chg_pct")
    by = {(r.strike, r.kind): r for r in rows}
    for i, r in enumerate(rows):
        o = by.get((r.strike, "PE" if r.kind == "CE" else "CE"))
        if o and not _u(r.oi_change_pct) and not _u(o.oi_change_pct) and r.oi_change_pct >= m and o.oi_change_pct >= m \
                and o.oi_change and lo <= r.oi_change / o.oi_change <= hi:
            rows[i] = _replace(r, hypothesis=HEDGE, evidence=r.evidence + (
                f"CE and PE OI both rising at {r.strike:g} (ratio {r.oi_change / o.oi_change:.2f} in [{lo}, {hi}])",))
    strikes = sorted({r.strike for r in rows})
    atm = Unavailable("NO_UNDERLYING_PRICE") if _u(und_now) or not strikes else \
        min(strikes, key=lambda k: (abs(k * 100 - und_now), k))
    if _u(atm):
        pcr = pcrv = Unavailable(atm.reason)
        conc = chg = {k: Unavailable(atm.reason) for k in OPTION_KINDS}
    else:
        rng = _range(strikes, atm, cfg.get("options.chain_strikes"))
        ce, pe = _conc(rows, "CE", rng, "oi"), _conc(rows, "PE", rng, "oi")

        def ratio(field):
            s = {k: [getattr(r, field) for r in rows if r.kind == k and r.strike in rng] for k in OPTION_KINDS}
            bad = [f"{k}: {sum(_u(v) for v in vs)} of {len(vs)} strikes missing {field}" for k, vs in s.items()
                   if not vs or any(_u(v) for v in vs)]
            if bad:
                return Unavailable("; ".join(bad))
            return sum(s["PE"]) / sum(s["CE"]) if sum(s["CE"]) else Unavailable(f"CE {field} total is 0")
        pcr, pcrv = ratio("oi"), ratio("volume_day")
        conc = {"CE": ce, "PE": pe}
        ref_rows = [_replace(r, oi=_ref_oi(r, oi_ref, ref_as_of, cfg)) for r in rows]
        chg = {}
        for k in OPTION_KINDS:
            old = _conc(ref_rows, k, rng, "oi")
            chg[k] = Unavailable(f"CONCENTRATION_CHANGE_UNAVAILABLE: {(conc[k] if _u(conc[k]) else old).reason}") \
                if _u(conc[k]) or _u(old) else (conc[k][1] - old[1]) * 100
    return ChainSnapshot(underlying, expiry, as_of, ref_as_of, atm, und_now, und_chg, tuple(rows), pcr, pcrv, conc, chg,
                         (sum(not _u(r.iv) for r in rows), len(rows)), CHAIN_LABELS, cfg.version)


def _ref_oi(r: StrikeRow, oi_ref, ref_as_of, cfg):
    o = _oi(oi_ref, r.token, ref_as_of, cfg)
    return o if _u(o) else o[0]


def atm_iv(snap: ChainSnapshot | None) -> float | Unavailable:
    """Underlying ATM IV: the mean of the ATM CE and PE IVs that are available."""
    if snap is None or _u(snap.atm_strike):
        return Unavailable("NO_ATM: " + ("no chain snapshot" if snap is None else snap.atm_strike.reason))
    ivs = [r.iv for r in snap.rows if r.strike == snap.atm_strike and not _u(r.iv)]
    return sum(ivs) / len(ivs) if ivs else Unavailable(f"ATM_IV_UNAVAILABLE at strike {snap.atm_strike:g}")


def iv_percentile(iv_now, history: Iterable[tuple[date, float]], day: date, cfg) -> float | Unavailable:
    """Percentile of iv_now among the underlying's own recorded ATM IVs of EARLIER sessions (no same-day look-ahead)."""
    if _u(iv_now):
        return Unavailable(f"IV_PERCENTILE_UNAVAILABLE: {iv_now.reason}")
    past = {d: v for d, v in history if d < day}
    need = cfg.get("options.iv_pct_min_sessions")
    if len(past) < need:
        return Unavailable(f"IV_HISTORY_SHORT: {len(past)} recorded sessions < {need} (Q-11-7)")
    return 100 * sum(v <= iv_now for v in past.values()) / len(past)


# ---------------------------------------------------------------- Phase 8 options factor
def options_factor(direction: int, snap: ChainSnapshot | None, cfg) -> tuple[str | Unavailable, float | Unavailable, str]:
    """(state, fraction of the factor weight, explanation). Counts corroborated hypotheses at ATM +/- factor_strikes."""
    if snap is None:
        u = Unavailable("NO_OPTION_CHAIN: no recorded option chain for this underlying at the decision time")
        return u, u, u.reason
    if _u(snap.atm_strike):
        u = Unavailable(f"NO_ATM: {snap.atm_strike.reason}")
        return u, u, u.reason
    strikes = sorted({r.strike for r in snap.rows})
    rng = _range(strikes, snap.atm_strike, cfg.get("options.factor_strikes"))
    rows = [r for r in snap.rows if r.strike in rng]
    bull = [f"{r.kind} {r.strike:g} {r.hypothesis}" for r in rows if (r.kind, r.hypothesis) in BULLISH]
    bear = [f"{r.kind} {r.strike:g} {r.hypothesis}" for r in rows if (r.kind, r.hypothesis) in BEARISH]
    same, opp = (bull, bear) if direction > 0 else (bear, bull)
    n = cfg.get("options.factor_min_labels")
    detail = (f"expiry {snap.expiry}, ATM {snap.atm_strike:g} +/- {cfg.get('options.factor_strikes')}: "
              f"with the trade [{', '.join(same) or 'none'}], against [{', '.join(opp) or 'none'}], "
              f"{sum(r.hypothesis == UNCERTAIN for r in rows)} UNCERTAIN, {sum(r.hypothesis == HEDGE for r in rows)} hedge (hypotheses, not facts)")
    if len(same) >= n and not opp:
        return SUPPORTIVE, 1.0, f"SUPPORTIVE: {detail}"
    if len(opp) >= n and not same:
        return CONTRADICTING, 0.0, f"CONTRADICTING: {detail}"
    return NEUTRAL, 0.0, f"NEUTRAL: {detail}"


# ---------------------------------------------------------------- selector V2 input
@dataclass(frozen=True)
class OptionContext:
    underlying: str
    as_of: int
    analytics: Mapping                  # {token: ContractAnalytics} at as_of
    snapshots: tuple                    # ChainSnapshot per expiry (nearest first)
    atm_iv: float | Unavailable
    iv_percentile: float | Unavailable
    ref: Mapping                        # {token: ContractAnalytics} at the setup's confirmation (Opportunity Age)


# ---------------------------------------------------------------- REST quote -> Quote (pure parse)
def quote_from_rest(token: int, j: Mapping, receive_ns: int) -> Quote:
    """One instrument of a Kite `/quote` response (F-QUOTE-3) -> Quote. Empty levels (price or quantity 0) are dropped."""
    side = lambda k: tuple((round(lv["price"] * 100), lv["quantity"], lv["orders"])  # noqa: E731
                           for lv in (j.get("depth") or {}).get(k, []) if lv.get("price") and lv.get("quantity"))
    ts = j.get("timestamp")
    ex = None if not ts else int(datetime.fromisoformat(str(ts)).replace(tzinfo=IST).timestamp()) * S
    lp = j.get("last_price")
    return Quote(token, side("buy"), side("sell"), True, None if lp is None else round(lp * 100), j.get("volume"),
                 j.get("oi"), ex, receive_ns, "kite.rest.quote")


# ---------------------------------------------------------------- tier C planner
def _nearest(strikes: list[float], px_paise: float) -> float:
    return min(strikes, key=lambda k: (abs(k * 100 - px_paise), k))


def plan_tier_c(underlyings: list[tuple[str, str]], contracts: Mapping[str, list], atm_ref: Mapping[str, float],
                scan: Mapping[int, Quote], first_oi: Mapping[int, int], levels: Mapping[str, list], day: date, cfg):
    """-> (Request list, dropped). underlyings: [(name, priority reason)] in priority order; contracts: {name: CE/PE rows};
    atm_ref: {name: underlying price paise}; scan: REST quotes of the scanned strikes (OI, volume); first_oi: {token: OI at
    the day's first scan}; levels: {name: [price paise]}. The Request count never exceeds tiers.C.max_tokens."""
    P, cap, mode = cfg.get("options.planner"), cfg.get("tiers.C.max_tokens"), cfg.get("tiers.C.mode")
    out, seen, dropped = [], set(), []
    for und, why in underlyings:
        cs = [c for c in contracts.get(und, []) if c.instrument_type in OPTION_KINDS and c.expiry >= day]
        if und not in atm_ref or not cs:
            dropped.append((und, "NO_ATM_REFERENCE" if cs else "NO_OPTIONS_IN_REGISTRY"))
            continue
        by_exp = {}
        for c in cs:
            by_exp.setdefault(c.expiry, {})[(float(c.strike), c.instrument_type)] = c
        expiries, liquid = sorted(by_exp), None
        for e in expiries:
            strikes = sorted({k for k, _ in by_exp[e]})
            atm = _nearest(strikes, atm_ref[und])
            legs = [by_exp[e].get((atm, k)) for k in OPTION_KINDS]
            vol = [None if c is None or c.token not in scan else scan[c.token].volume_day for c in legs]
            if None not in vol and sum(vol) / legs[0].lot_size >= P["liquid_min_volume_lots"]:
                liquid = e
                break
        if liquid is None:
            dropped.append((und, "NO_LIQUID_EXPIRY (scan volume below the minimum or missing)"))
            continue
        picks = []
        for e in expiries[expiries.index(liquid): expiries.index(liquid) + P["expiries"]]:
            strikes = sorted({k for k, _ in by_exp[e]})
            atm = _nearest(strikes, atm_ref[und])
            i = strikes.index(atm)
            near = sorted(strikes[max(0, i - P["atm_strikes"]): i + P["atm_strikes"] + 1], key=lambda k: (abs(k - atm), k))
            picks += [(e, k, t, f"ATM+/-{P['atm_strikes']}") for k in near for t in OPTION_KINDS]
            window = set(strikes[max(0, i - P["level_window_strikes"]): i + P["level_window_strikes"] + 1])
            lv = sorted({_nearest(strikes, x) for x in levels.get(und, [])} & window, key=lambda k: (abs(k - atm), k))
            picks += [(e, k, t, "LEVELMAP (previous session)") for k in lv[:P["level_strikes"]] for t in OPTION_KINDS]
            for t in OPTION_KINDS:
                rows = [c for (k, tt), c in by_exp[e].items() if tt == t and c.token in scan and scan[c.token].oi is not None]
                top = sorted(rows, key=lambda c: (-scan[c.token].oi, float(c.strike)))[:P["top_oi_k"]]
                picks += [(e, float(c.strike), t, "TOP_OI") for c in top]
                chg = [c for c in rows if c.token in first_oi]
                unusual = sorted(chg, key=lambda c: (-abs(scan[c.token].oi - first_oi[c.token]), float(c.strike)))
                picks += [(e, float(c.strike), t, "UNUSUAL_OI_CHANGE") for c in unusual[:P["unusual_oi_k"]]
                          if scan[c.token].oi != first_oi[c.token]]
        for e, k, t, reason in picks:
            c = by_exp[e].get((k, t))
            if c is None or c.token in seen:
                continue
            seen.add(c.token)
            if len(out) >= cap:
                dropped.append((c.tradingsymbol, f"TIER_C_CAP: {cap} option tokens reached (D-51)"))
                continue
            out.append(Request(c.token, "C", mode, t, und, f"tier C {why}: {reason}", len(out)))
    return out, dropped
