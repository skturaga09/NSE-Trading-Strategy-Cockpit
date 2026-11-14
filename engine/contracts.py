"""Phase 7 contract selector V1 (pure): an underlying setup -> ranked, risk-sized contract alternatives, or NO_TRADE.

`select_contracts(setup, contracts, tradable, quotes, spot, bars, margins, cfg) -> Selection` reads no clock, disk or
network; time is `setup.as_of`. The edge supplies the registry rows (Phase 2 `Registry.get_contracts`), `is_tradable`
answers, recorded quotes, 1m bars and (when fetched) margins.

Candidates, each evaluated on its own:
- Futures: the near month; the next month when the near month is within `positioning.rollover_days` of expiry.
- Long call (bullish) / long put (bearish): ATM (nearest strike to spot; a tie goes to the ITM side) and one strike ITM,
  on the nearest expiry with >= contracts.min_dte_days, and on the next expiry as the alternative. Strikes and expiries
  come only from the registry. Short options are never generated, and a Candidate that would be one raises.
Prices are paise (exchange integers, F-WS-9); money is INR. Quantities are units (F-QTY-1).

Option premium at stop / target: EMPIRICAL_DELTA_OLS, the option's 1m close changes regressed (through the origin) on the
setup instrument's over the last usable bars, then premium(level) = mid + delta x (level - entry). APPROXIMATE: linear,
ignores gamma, theta and IV change. No defensible estimate => the option is NO_TRADE with NO_PREMIUM_MODEL. No
Black-Scholes delta: IV is not reliably computable here (no verified rate / dividend inputs, no recorded option data).
Futures at a level: mid + (level - entry); for a month other than the setup instrument, the basis is assumed constant.

Ranking: net R:R x liquidity score (descending), ties by lower required capital. Premium level is never a factor.

Selector V2 (Phase 11, owner-approved additive interface D-52): keyword-only `chain` (engine.options.OptionContext) and
`events` (engine.events.EventStatus). Adds a nearby OTM alternative (one strike OTM) on each expiry; when the chain has
Black-76 Greeks for a contract, its premium at stop / target = delta-gamma-theta estimate (BLACK76_DELTA_GAMMA_THETA,
APPROXIMATE: second order in the move, IV unchanged, theta over options.holding_min), else the V1 empirical model.
Reports IV, Greeks, theta cost over the holding time and expiry-day sensitivity. Long options are EXCLUDED with
EVENT_UNVERIFIED (no / stale calendar), EVENT_IV_RISK (board meeting in the window), IV_PERCENTILE_UNAVAILABLE or
IV_PERCENTILE_TOO_HIGH; risk_check then REJECTS them (CANDIDATE_ELIGIBLE). Futures get event findings as labels only.
Pending quantities / 5-level depth are not executed volume and not a full book (F-QUOTE-5/7).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from .candles import MIN, S, Unavailable, _ns
from .config import load_config
from .costs import DEFAULT_CONFIG, REQUIRED as COST_KEYS, CostEstimate, Fill, fill, require, round_trip

ELIGIBLE, EXCLUDED, NO_TRADE = "ELIGIBLE", "EXCLUDED", "NO_TRADE"
OPTION_KINDS = ("CE", "PE")
REQUIRED = COST_KEYS + ["quality.stale_depth_s", "quality.stale_price_s", "positioning.rollover_days"] + [
    f"contracts.{k}" for k in ("min_dte_days", "premium_model.bars", "premium_model.min_pairs", "premium_model.min_r2",
                               "futures_margin.method", "futures_margin.fraction", "liquidity_depth_target")] + [
    f"risk.{k}" for k in ("capital_inr", "capital_reserve_pct", "max_capital_per_trade_inr", "max_risk_per_trade_inr",
                          "max_daily_loss_inr", "max_open_positions", "max_daily_trades", "max_consecutive_losses",
                          "cooldown_min", "max_spread_pct", "max_spread_move_pct", "min_rr_net", "max_slippage_pct",
                          "min_volume_lots", "min_oi_lots", "min_depth_coverage", "block_expiry_day", "event_days",
                          "intraday_cutoff", "single_position_per_underlying", "gap_risk_atr_multiple")]


def load(path=DEFAULT_CONFIG):
    return require(load_config(path), REQUIRED, path)


# ---------------------------------------------------------------- types
@dataclass(frozen=True)
class TradeSetup:
    id: str
    underlying: str
    direction: int              # +1 bullish, -1 bearish
    day: date
    as_of: int                  # decision time, ns (stream / replay time)
    price_token: int            # the instrument the levels are measured on (Phase 5/6: the near-month future)
    entry: int                  # entry trigger on price_token, paise
    stop: int                   # structural stop on price_token, paise
    targets: tuple              # on price_token, paise; target 1 first
    atr: float                  # setup-timeframe ATR on price_token, paise (futures gap risk)


@dataclass(frozen=True)
class Quote:
    token: int
    bids: tuple                 # ((price_paise, qty, orders), ...) best first: PENDING orders, 5 levels max
    asks: tuple
    depth: bool                 # False => only the touch is known
    last_price: int | None
    volume_day: int | None      # units (F-QTY-1)
    oi: int | None
    exchange_ts_ns: int | None
    receive_ns: int
    source: str


@dataclass(frozen=True)
class PremiumModel:
    method: str
    delta: float
    pairs: int
    r2: float


@dataclass(frozen=True)
class Candidate:
    id: str
    setup_id: str
    underlying: str
    kind: str                   # FUT | CE | PE
    side: str                   # BUY | SELL (SELL only for a bearish future)
    token: int
    tradingsymbol: str
    expiry: date
    strike: float | None
    dte: int
    lot_size: int
    status: str                 # ELIGIBLE | EXCLUDED | NO_TRADE
    reasons: tuple
    labels: tuple               # APPROXIMATE_PREMIUM_MODEL, MARGIN_ESTIMATED, ESTIMATED_SLIPPAGE, UNVERIFIED_COSTS, ...
    as_of: int
    config_version: str
    lots: int | None = None
    quantity: int | None = None
    bid: int | None = None
    ask: int | None = None
    mid: float | None = None
    entry: float | None = None  # executable estimate: the walked fill (ask side for a buy), paise
    spread_pct: float | None = None
    spread_vs_move_pct: float | None = None
    top_bid_qty: int | None = None
    top_ask_qty: int | None = None
    depth_bid_qty: int | None = None
    depth_ask_qty: int | None = None
    volume_day: int | None = None
    oi: int | None = None
    entry_fill: Fill | None = None
    exit_fill: Fill | None = None   # estimated from the same book (the exit-time book is unknown)
    slippage_pct: float | None = None
    stop: float | None = None       # contract price at the structural stop, paise
    targets: tuple = ()             # contract prices at the targets, paise
    premium_model: PremiumModel | None = None
    required_capital_inr: float | None = None
    capital_method: str | None = None   # PREMIUM | MARGIN_API | MARGIN_ESTIMATED
    planned_risk_inr: float | None = None
    full_premium_at_risk_inr: float | None = None   # options: stop execution is not guaranteed
    gap_risk_inr: float | None = None               # futures: planned risk + ATR multiple beyond the stop
    reward_t1_inr: float | None = None
    costs_at_stop: CostEstimate | None = None
    costs_at_target: CostEstimate | None = None
    rr_net: float | None = None
    liquidity_score: float | None = None
    score: float | None = None
    source: str | None = None
    exchange_ts_ns: int | None = None
    receive_ns: int | None = None
    processed_ns: int | None = None  # = as_of: the decision time is the processing time
    age_s: float | None = None
    role: str | None = None          # V2: FUT | ATM | ITM | OTM
    iv: object = None                # V2: Black-76 IV (decimal) or Unavailable
    greeks: object = None            # V2: engine.options.Greeks or Unavailable
    iv_percentile: object = None     # V2: underlying ATM IV percentile or Unavailable
    premium_method: str | None = None
    theta_cost_inr: float | None = None   # V2: -theta x holding days x quantity (premium decay over the holding time)
    expiry_sensitivity: dict | None = None

    def __post_init__(self):
        if self.kind in OPTION_KINDS and self.side != "BUY":
            raise ValueError(f"{self.tradingsymbol}: short options are not supported")
        if self.kind not in OPTION_KINDS + ("FUT",):
            raise ValueError(f"{self.tradingsymbol}: unsupported instrument type {self.kind}")


@dataclass(frozen=True)
class Selection:
    setup: TradeSetup
    decision: str               # CANDIDATES | NO_TRADE
    candidates: tuple           # eligible ranked first, then the excluded / NO_TRADE ones
    notes: tuple
    config_version: str = field(default="")


# ---------------------------------------------------------------- pure helpers
def premium_model(opt: Mapping[int, int], und: Mapping[int, int], as_of: int, kind: str, cfg) -> PremiumModel | Unavailable:
    """opt / und: {1m bar end ns: close paise}, usable bars only. Changes over contiguous 1m pairs ending <= as_of."""
    m = cfg.get("contracts.premium_model")
    ends = sorted(t for t in opt if t in und and t <= as_of)[-(m["bars"] + 1):]
    pairs = [(und[b] - und[a], opt[b] - opt[a]) for a, b in zip(ends, ends[1:]) if b - a == MIN]
    if len(pairs) < m["min_pairs"]:
        return Unavailable(f"NO_PREMIUM_MODEL: {len(pairs)} contiguous paired 1m bars < {m['min_pairs']}")
    sxx = sum(du * du for du, _ in pairs)
    syy = sum(do * do for _, do in pairs)
    if not sxx or not syy:
        return Unavailable("NO_PREMIUM_MODEL: no movement in the paired bars")
    delta = sum(du * do for du, do in pairs) / sxx
    r2 = 1 - sum((do - delta * du) ** 2 for du, do in pairs) / syy
    if not (0 < delta <= 1 if kind == "CE" else -1 <= delta < 0):
        return Unavailable(f"NO_PREMIUM_MODEL: empirical delta {delta:.3f} outside the range of a long {kind}")
    if r2 < m["min_r2"]:
        return Unavailable(f"NO_PREMIUM_MODEL: fit R2 {r2:.2f} < {m['min_r2']}")
    return PremiumModel("EMPIRICAL_DELTA_OLS_1M (APPROXIMATE: linear; ignores gamma, theta, IV)", delta, len(pairs), r2)


def quote_problem(q: Quote | None, as_of: int, max_age_s: float) -> str | None:
    if q is None:
        return "NO_QUOTE"
    if q.receive_ns > as_of:
        return "QUOTE_AFTER_DECISION_TIME"
    if (as_of - q.receive_ns) / S > max_age_s:
        return f"STALE_QUOTE ({(as_of - q.receive_ns) / S:.1f} s > {max_age_s} s)"
    if not q.bids or not q.asks or q.bids[0][0] <= 0 or q.asks[0][0] <= 0:
        return "NO_TWO_SIDED_BOOK"
    if q.bids[0][0] >= q.asks[0][0]:
        return "CROSSED_OR_LOCKED_BOOK"
    return None


def limit_reasons(c: Candidate, cfg) -> list[str]:
    """Per-contract limits shared by the selector (exclusion) and risk_check (rejection): one definition."""
    R, cls = (lambda k: cfg.get("risk." + k)), ("OPT" if c.kind in OPTION_KINDS else "FUT")
    out = []
    if c.spread_pct is not None and c.spread_pct > R("max_spread_pct")[cls]:
        out.append(f"SPREAD_TOO_WIDE ({c.spread_pct:.3f} % > {R('max_spread_pct')[cls]} %)")
    if c.spread_vs_move_pct is not None and c.spread_vs_move_pct > R("max_spread_move_pct"):
        out.append(f"SPREAD_VS_MOVE_TOO_WIDE ({c.spread_vs_move_pct:.1f} % of the move to T1 > {R('max_spread_move_pct')} %)")
    for name, v, lim in (("VOLUME", c.volume_day, R("min_volume_lots")[cls]), ("OI", c.oi, R("min_oi_lots")[cls])):
        if v is None:
            out.append(f"ILLIQUID:{name}_UNAVAILABLE")
        elif v / c.lot_size < lim:
            out.append(f"ILLIQUID:{name} ({v / c.lot_size:.0f} lots < {lim})")
    if c.quantity:
        exec_depth = c.depth_ask_qty if c.side == "BUY" else c.depth_bid_qty
        if exec_depth is None or exec_depth < R("min_depth_coverage") * c.quantity:
            out.append(f"ILLIQUID:DEPTH ({exec_depth} visible < {R('min_depth_coverage')} x {c.quantity})")
    cap = c.full_premium_at_risk_inr if c.kind in OPTION_KINDS else c.required_capital_inr   # options: premium + costs
    if cap is not None and cap > R("max_capital_per_trade_inr"):
        out.append(f"CAPITAL_ABOVE_LIMIT ({cap:,.0f} > {R('max_capital_per_trade_inr'):,} INR)")
    return out


def _v2_gates(s: TradeSetup, c, chain, events, cfg) -> tuple[list, list]:
    from .events import gate
    rej, warn = gate(s.underlying, c.family, c.instrument_type, s.day, events, cfg)
    reasons, labels = ([rej] if rej else []), ([warn] if warn else [])
    if c.instrument_type in OPTION_KINDS:
        pct = Unavailable("no option context supplied") if chain is None else chain.iv_percentile
        if isinstance(pct, Unavailable):
            # owner D-70 (v20+): too little IV history is a warning until enough sessions exist; a missing current IV
            # (no fresh two-sided book) still rejects. Configs before v20 have no key and reject both.
            if pct.reason.startswith("IV_HISTORY_SHORT") and cfg.values.get("options", {}).get("iv_history_short") == "WARN":
                labels.append(f"IV_HISTORY_NOT_READY: {pct.reason}")
            else:
                reasons.append(f"IV_PERCENTILE_UNAVAILABLE: {pct.reason}")
        elif pct > cfg.get("options.iv_pct_max_long"):
            reasons.append(f"IV_PERCENTILE_TOO_HIGH ({pct:.0f} > {cfg.get('options.iv_pct_max_long')})")
    return reasons, labels


def _evaluate(s: TradeSetup, c, tradable, q: Quote | None, bars, margins, cfg, reasons=(), *, role=None, chain=None,
              events=None, und_expiry=None) -> Candidate:
    opt = c.instrument_type in OPTION_KINDS
    side = "BUY" if opt or s.direction > 0 else "SELL"
    pos, product = (1 if side == "BUY" else -1), ("OPT" if opt else "FUT")
    gate_reasons, labels = _v2_gates(s, c, chain, events, cfg)
    reasons = list(reasons) + gate_reasons
    ok, why = tradable.get(c.token, (False, ["NOT_CHECKED"]))
    if not ok:
        reasons.append("RESTRICTED:" + ",".join(why))
    base = dict(id=f"{s.id}:{c.tradingsymbol}", setup_id=s.id, underlying=s.underlying, kind=c.instrument_type, side=side,
                token=c.token, tradingsymbol=c.tradingsymbol, expiry=c.expiry,
                strike=float(c.strike) if c.strike is not None else None, dte=(c.expiry - s.day).days,
                lot_size=c.lot_size, as_of=s.as_of, config_version=cfg.version, processed_ns=s.as_of, role=role)
    an = None if chain is None else chain.analytics.get(c.token)
    if opt:
        base.update(iv=Unavailable("no option context") if an is None else an.iv,
                    greeks=Unavailable("no option context") if an is None else an.greeks,
                    iv_percentile=Unavailable("no option context") if chain is None else chain.iv_percentile)
    g = None if an is None or isinstance(an.greeks, Unavailable) else an.greeks
    if q is not None:
        base.update(source=q.source, exchange_ts_ns=q.exchange_ts_ns, receive_ns=q.receive_ns,
                    age_s=(s.as_of - q.receive_ns) / S, volume_day=q.volume_day, oi=q.oi)
    bad_quote = quote_problem(q, s.as_of, cfg.get("quality.stale_depth_s"))
    model = None
    if opt and g is not None:
        hold = cfg.get("options.holding_min") * MIN / (_ns(s.day, cfg.get("sessions.fno.close")) - _ns(s.day, cfg.get("sessions.fno.open")))
        base.update(premium_method="BLACK76_DELTA_GAMMA_THETA (APPROXIMATE: second order in the move, IV unchanged, "
                                   f"theta over {cfg.get('options.holding_min')} min)")
        labels.append("APPROXIMATE_PREMIUM_MODEL")
        if und_expiry is not None and c.expiry != und_expiry:
            labels.append("BASIS_ASSUMED_CONSTANT")
    elif opt:
        model = premium_model(bars.get(c.token, {}), bars.get(s.price_token, {}), s.as_of, c.instrument_type, cfg)
        if isinstance(model, Unavailable):
            reasons.append(model.reason)
            model = None
        else:
            base["premium_method"] = model.method
            labels.append("APPROXIMATE_PREMIUM_MODEL")
    elif c.token != s.price_token:
        labels.append("BASIS_ASSUMED_CONSTANT")
    if bad_quote:
        reasons.append("DATA_NOT_OK:" + bad_quote)
    if bad_quote or (opt and model is None and g is None):
        status = NO_TRADE if any(r.startswith("NO_PREMIUM_MODEL") for r in reasons) else EXCLUDED
        return Candidate(**base, status=status, reasons=tuple(reasons), labels=tuple(labels), premium_model=model)

    bid, ask = q.bids[0][0], q.asks[0][0]
    mid = (bid + ask) / 2
    if opt and g is not None:
        from .options import premium_at
        at = lambda level: premium_at(mid, g, level - s.entry, hold)  # noqa: E731
    else:
        delta = model.delta if opt else 1.0
        at = lambda level: mid + delta * (level - s.entry)  # noqa: E731  contract price with the setup instrument at `level`
    stop_c, tgts = at(s.stop), tuple(at(t) for t in s.targets)
    if opt and stop_c < 0:
        stop_c = 0.0
        labels.append("PREMIUM_AT_STOP_FLOORED_AT_ZERO")
    base.update(bid=bid, ask=ask, mid=mid, top_bid_qty=q.bids[0][1], top_ask_qty=q.asks[0][1],
                depth_bid_qty=sum(lv[1] for lv in q.bids), depth_ask_qty=sum(lv[1] for lv in q.asks),
                stop=stop_c, targets=tgts, premium_model=model,
                spread_pct=(ask - bid) / mid * 100)
    if not q.depth:
        labels.append("ESTIMATED_SLIPPAGE")
    if not tgts or pos * (tgts[0] - mid) <= 0 or pos * (mid - stop_c) <= 0:
        reasons.append("BAD_GEOMETRY: stop / target 1 not on the expected sides of the contract price")
        return Candidate(**base, status=EXCLUDED, reasons=tuple(reasons), labels=tuple(labels))
    base["spread_vs_move_pct"] = (ask - bid) / abs(tgts[0] - mid) * 100

    def plan(lots: int):
        qty = lots * c.lot_size
        f_in, f_out = fill(q.bids, q.asks, q.depth, side, qty, cfg), fill(q.bids, q.asks, q.depth,
                                                                          "SELL" if side == "BUY" else "BUY", qty, cfg)
        if f_in.avg_price is None or f_out.per_unit is None:
            return None
        x_stop, x_tgt = max(stop_c - pos * f_out.per_unit, 0.0), tgts[0] - pos * f_out.per_unit
        c_stop = round_trip(cfg, product, side, f_in.avg_price / 100, x_stop / 100, qty, s.day)
        c_tgt = round_trip(cfg, product, side, f_in.avg_price / 100, x_tgt / 100, qty, s.day)
        return dict(lots=lots, quantity=qty, entry=f_in.avg_price, entry_fill=f_in, exit_fill=f_out,
                    costs_at_stop=c_stop, costs_at_target=c_tgt,
                    planned_risk_inr=pos * (f_in.avg_price - x_stop) * qty / 100 + c_stop.total_inr,
                    reward_t1_inr=pos * (x_tgt - f_in.avg_price) * qty / 100 - c_tgt.total_inr)

    max_risk = cfg.get("risk.max_risk_per_trade_inr")
    p = plan(1)
    if p is None:
        reasons.append(f"ILLIQUID:DEPTH (5 visible levels do not hold one lot of {c.lot_size})")
        return Candidate(**base, status=EXCLUDED, reasons=tuple(reasons), labels=tuple(labels))
    n = int(max_risk // p["planned_risk_inr"]) if p["planned_risk_inr"] > 0 else 0
    if not n:
        reasons.append(f"RISK_PER_LOT_ABOVE_MAX ({p['planned_risk_inr']:,.0f} > {max_risk:,} INR for one lot)")
    while n > 1:
        pn = plan(n)
        if pn is not None and pn["planned_risk_inr"] <= max_risk:
            p = pn
            break
        n -= 1
    base.update(p)
    qty, entry = p["quantity"], p["entry"]
    if opt and g is not None:
        theta_pct = -g.theta / (mid / 100) * 100
        sens = theta_pct >= cfg.get("options.expiry_sensitive_theta_pct") or base["dte"] == 0
        base.update(theta_cost_inr=-g.theta * hold * qty,
                    expiry_sensitivity={"dte": base["dte"], "theta_pct_of_premium_per_day": theta_pct,
                                        "gamma": g.gamma, "expiry_sensitive": sens})
        if sens:
            labels.append(f"EXPIRY_SENSITIVE (theta {theta_pct:.1f} % of premium per trading day, dte {base['dte']})")
    base["slippage_pct"] = p["entry_fill"].per_unit / mid * 100
    if opt:
        base.update(required_capital_inr=entry * qty / 100, capital_method="PREMIUM",
                    full_premium_at_risk_inr=entry * qty / 100 + p["costs_at_stop"].total_inr)
    else:
        if c.token in margins:
            base.update(required_capital_inr=margins[c.token] * p["lots"], capital_method="MARGIN_API")
        else:
            base.update(required_capital_inr=cfg.get("contracts.futures_margin.fraction") * entry * qty / 100,
                        capital_method="MARGIN_ESTIMATED")
            labels.append("MARGIN_ESTIMATED")
        base["gap_risk_inr"] = p["planned_risk_inr"] + cfg.get("risk.gap_risk_atr_multiple") * s.atr * qty / 100
    if "UNVERIFIED" in (p["costs_at_stop"].status, p["costs_at_target"].status):
        labels.append("UNVERIFIED_COSTS")
    base["rr_net"] = p["reward_t1_inr"] / p["planned_risk_inr"]
    exec_depth = base["depth_ask_qty"] if side == "BUY" else base["depth_bid_qty"]
    base["liquidity_score"] = (min(1.0, exec_depth / (cfg.get("contracts.liquidity_depth_target") * qty))
                               * max(0.0, 1 - base["spread_pct"] / cfg.get("risk.max_spread_pct")[product]))
    probe = Candidate(**base, status=EXCLUDED, reasons=(), labels=())
    reasons += limit_reasons(probe, cfg)
    status = EXCLUDED if reasons else ELIGIBLE
    score = base["rr_net"] * base["liquidity_score"] if status == ELIGIBLE else None
    return Candidate(**{**base, "score": score}, status=status, reasons=tuple(reasons), labels=tuple(labels))


def select_contracts(setup: TradeSetup, contracts, tradable: Mapping[int, tuple], quotes: Mapping[int, Quote],
                     spot: Quote | None, bars: Mapping[int, Mapping[int, int]], margins: Mapping[int, float], cfg, *,
                     chain=None, events=None) -> Selection:
    """contracts: the underlying's registry rows (engine.universe.Contract); tradable: {token: (bool, reasons)};
    quotes: {token: Quote} at or before setup.as_of; spot: the underlying's spot quote (ATM reference);
    bars: {token: {1m end ns: close}} usable bars; margins: {token: INR per lot} from a margin quote (may be empty);
    chain: engine.options.OptionContext (V2) or None; events: engine.events.EventStatus or None (=> EVENT_UNVERIFIED)."""
    d, notes, out = setup.day, [], []
    v2 = dict(chain=chain, events=events)
    und_expiry = next((c.expiry for c in contracts if c.token == setup.price_token), None)
    roll, min_dte = cfg.get("positioning.rollover_days"), cfg.get("contracts.min_dte_days")
    futs = sorted((c for c in contracts if c.instrument_type == "FUT" and c.expiry >= d), key=lambda c: c.expiry)
    # owner D-69 (v20+): `contracts.instrument_kinds` lists what may be traded; configs before v20 consider all
    if "FUT" not in cfg.values.get("contracts", {}).get("instrument_kinds", ["FUT", "CE", "PE"]):
        notes.append("FUT: not considered (contracts.instrument_kinds: options only, owner D-69)")
    elif futs:
        near = futs[0]
        if (near.expiry - d).days <= roll and len(futs) > 1:
            notes.append(f"FUT {near.tradingsymbol}: rollover window (dte {(near.expiry - d).days} <= {roll}); next month used")
            out.append(_evaluate(setup, futs[1], tradable, quotes.get(futs[1].token), bars, margins, cfg, role="FUT", **v2))
        else:
            why = [f"EXPIRY_TOO_CLOSE (rollover window, dte {(near.expiry - d).days})"] if (near.expiry - d).days <= roll else []
            out.append(_evaluate(setup, near, tradable, quotes.get(near.token), bars, margins, cfg, why, role="FUT", **v2))
    else:
        notes.append("FUT: no active future in the registry")

    kind = "CE" if setup.direction > 0 else "PE"
    opts = [c for c in contracts if c.instrument_type == kind and c.expiry >= d]
    expiries = sorted({c.expiry for c in opts})
    notes += [f"{kind} expiry {e}: EXPIRY_TOO_CLOSE (dte {(e - d).days} < {min_dte})" for e in expiries if (e - d).days < min_dte]
    usable = [e for e in expiries if (e - d).days >= min_dte][:2]
    spot_bad, max_age = None, cfg.get("quality.stale_price_s")
    if spot is None or spot.last_price is None:
        spot_bad = "NO_SPOT_QUOTE"
    elif spot.receive_ns > setup.as_of:
        spot_bad = "SPOT_AFTER_DECISION_TIME"
    elif (setup.as_of - spot.receive_ns) / S > max_age:
        spot_bad = f"STALE_SPOT ({(setup.as_of - spot.receive_ns) / S:.1f} s > {max_age} s)"
    if not usable:
        notes.append(f"{kind}: no expiry with dte >= {min_dte} in the registry")
    elif spot_bad:
        notes.append(f"{kind}: OPTIONS_NOT_EVALUATED (no ATM reference: {spot_bad})")
    else:
        for e in usable:
            strikes = sorted((c for c in opts if c.expiry == e), key=lambda c: c.strike)
            sign = 1 if kind == "CE" else -1     # ITM side: lower strikes for calls, higher for puts
            atm = min(strikes, key=lambda c: (abs(float(c.strike) * 100 - spot.last_price), sign * c.strike))
            itm = [c for c in strikes if sign * (c.strike - atm.strike) < 0]
            itm = (itm[-1] if kind == "CE" else itm[0]) if itm else None
            otm = [c for c in strikes if sign * (c.strike - atm.strike) > 0]
            otm = (otm[0] if kind == "CE" else otm[-1]) if otm else None
            for name, c in (("ITM", itm), ("OTM", otm)):
                if c is None:
                    notes.append(f"{kind} {e}: no strike {name} of the ATM {atm.strike}")
            for role, c in (("ATM", atm), ("ITM", itm), ("OTM", otm)):
                if c is not None:
                    out.append(_evaluate(setup, c, tradable, quotes.get(c.token), bars, margins, cfg, role=role,
                                         und_expiry=und_expiry, **v2))

    elig = sorted((c for c in out if c.status == ELIGIBLE), key=lambda c: (-c.score, c.required_capital_inr))
    rest = [c for c in out if c.status != ELIGIBLE]
    return Selection(setup, "CANDIDATES" if elig else "NO_TRADE", tuple(elig + rest), tuple(notes), cfg.version)
