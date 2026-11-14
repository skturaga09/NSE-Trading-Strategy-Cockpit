"""Phase 8 signal engine (pure): setup families, eligibility gates, evidence scoring, the recommendation object and its
lifecycle. Advisory and paper-trading only: nothing here places, modifies or cancels an order.

Pure core: `match`, `recommend(inputs, cfg)`, `score`, `gates`, `drive`, `accumulation`, `exhaustion_observation`,
`market_context`, `start` / `advance`, `promotions` read no clock, disk or network. Time is the Phase 6 evaluation's
`as_of`. The edge (`engine.signal_report`) loads Phases 4-7 outputs, recorded quotes and the registry, and stores the
inputs of every recommendation so that `recommend(inputs)` regenerates it identically.

Families (each a pure function -> FamilySetup | None, with evidence and contradictions; owner-accepted Q-8-6):
  A LONG_BUILDUP_BREAKOUT        Phase 6 BREAKOUT_ACCEPTED + primary (index-residual) LONG_BUILDUP + RVOL elevated + above VWAP
  B SHORT_BUILDUP_BREAKDOWN      symmetric on BREAKDOWN_ACCEPTED
  C SHORT_COVERING_MOMENTUM      BREAKOUT_ACCEPTED + SHORT_COVERING + sharp ATR move + supportive RVOL; "covering, not confirmed new buying"
  D LONG_UNWINDING_CONTINUATION  BREAKDOWN_ACCEPTED + LONG_UNWINDING + below VWAP + RVOL supportive in each of N windows
  E BULLISH_SWEEP_REVERSAL       Phase 6 SWEEP_LOW (sweep + reclaim) + rejection RVOL + BOS_UP / CHOCH_UP after the sweep
  F BEARISH_SWEEP_REVERSAL       symmetric on SWEEP_HIGH
  G POSSIBLE_EXHAUSTION          Phase 6 exhaustion flags: a warning on A-F and a standalone observation; never an entry (V1)
Labels describe price, OI and volume data only (DISCLAIMER). Scores are research priorities, not probabilities.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Mapping

from .candles import IST, MIN, S, Unavailable, _ns
from .config import REPO, ConfigError, load_config
from .contracts import ELIGIBLE, OPTION_KINDS, REQUIRED as CONTRACT_KEYS, TradeSetup, limit_reasons, select_contracts
from .options import changes as option_changes, options_factor
from .costs import require
from .opportunity import EXHAUSTED, LATE, REQUIRED as OPP_KEYS, TIMELY, Setup
from .positioning import (DIRECTION, DISCLAIMER as POSITIONING_DISCLAIMER, LONG_BUILDUP, LONG_UNWINDING, NEUTRAL,
                          SHORT_BUILDUP, SHORT_COVERING)
from .profile import depth_part, profile_part
from .risk import APPROVED, Recommendation, risk_check
from .snapshots import jsonable
from .structure import levels_at

DEFAULT_CONFIG = REPO / "config" / "engine" / "v24.yaml"   # D-76 cloud archive; D-72 option coverage; Phase 15: owner risk answers D-61/D-62 (v14 = Phase 11, v10 = Phase 8 record)
WEIGHTS = ("futures_positioning", "volume_vwap", "options", "structure", "profile_depth", "broad_market")
REQUIRED = CONTRACT_KEYS + OPP_KEYS + ["positioning.feature_window_min", "positioning.beta.index_underlying"] + [
    f"signals.{k}" for k in (
        "families.rvol_elevated", "families.rvol_supportive", "families.sharp_move_atr", "families.persistence_windows",
        "families.rejection_rvol", "accumulation.windows", "accumulation.window_min", "covering_fraction", "bands.high",
        "bands.medium", "market.trend_timeframe_min", "market.breadth_min_underlyings", "market.breadth_bullish",
        "market.breadth_bearish", "single_position_mode", "tier_b_ttl_s")] + [f"signals.weights.{w}" for w in WEIGHTS]
DISCLAIMER = POSITIONING_DISCLAIMER + " Scores rank research priority; they are not probabilities of profit."

CONTINUATION, REVERSAL = "CONTINUATION", "REVERSAL"
FAMILIES = {  # letter: (label, kind, direction, Phase 6 source type)
    "A": ("LONG_BUILDUP_BREAKOUT", CONTINUATION, 1, "BREAKOUT_ACCEPTED"),
    "B": ("SHORT_BUILDUP_BREAKDOWN", CONTINUATION, -1, "BREAKDOWN_ACCEPTED"),
    "C": ("SHORT_COVERING_MOMENTUM", CONTINUATION, 1, "BREAKOUT_ACCEPTED"),
    "D": ("LONG_UNWINDING_CONTINUATION", CONTINUATION, -1, "BREAKDOWN_ACCEPTED"),
    "E": ("BULLISH_SWEEP_REVERSAL", REVERSAL, 1, "SWEEP_LOW"),
    "F": ("BEARISH_SWEEP_REVERSAL", REVERSAL, -1, "SWEEP_HIGH"),
}
SOURCES = {v[3] for v in FAMILIES.values()}
# The 12 state labels (Q-8-2, owner accepted the proposed list).
LABELS = tuple(v[0] for v in FAMILIES.values()) + ("POSSIBLE_EXHAUSTION", "SUSPECTED_ACCUMULATION", "SUSPECTED_DISTRIBUTION",
                                                  "CONFLICTING_EVIDENCE", "NO_TRADE", "UNCERTAIN")
# A NEUTRAL view whose reasons are all here was evaluated (no quadrant); any other reason means the evidence is missing.
EVALUATED_NEUTRAL = {"NOT_SIGNIFICANT", "CONFLICTING_WINDOWS", "INDEX_DRIVEN"}
STRONG_CONTRADICTIONS = ("positioning", "structure")

DETECTED, WATCHING, CONFIRMED, ENTRY_ELIGIBLE = "DETECTED", "WATCHING", "CONFIRMED", "ENTRY_ELIGIBLE"
TRIGGERED, ACTIVE, WEAKENING, EXIT_REQUIRED = "TRIGGERED", "ACTIVE", "WEAKENING", "EXIT_REQUIRED"
INVALIDATED, EXPIRED, REJECTED, WAIT_FOR_RETEST = "INVALIDATED", "EXPIRED", "REJECTED", "WAIT_FOR_RETEST"
ALLOWED = {
    None: {DETECTED},
    DETECTED: {WATCHING, INVALIDATED, EXPIRED},
    WATCHING: {CONFIRMED, INVALIDATED, EXPIRED},
    CONFIRMED: {ENTRY_ELIGIBLE, WAIT_FOR_RETEST, REJECTED},
    WAIT_FOR_RETEST: {CONFIRMED, INVALIDATED, EXPIRED},
    ENTRY_ELIGIBLE: {TRIGGERED, INVALIDATED, EXPIRED},
    TRIGGERED: {ACTIVE, INVALIDATED, EXPIRED},      # TRIGGERED onwards need a paper fill (Phase 11, Q-8-3)
    ACTIVE: {WEAKENING, EXIT_REQUIRED},
    WEAKENING: {ACTIVE, EXIT_REQUIRED},
    EXIT_REQUIRED: set(), INVALIDATED: set(), EXPIRED: set(), REJECTED: set(),
}
TERMINAL = {k for k, v in ALLOWED.items() if k and not v}


def load(path=DEFAULT_CONFIG):
    cfg = require(load_config(path), REQUIRED, path)
    if sum(cfg.get(f"signals.weights.{w}") for w in WEIGHTS) != 100:
        raise ConfigError(f"config {path}: signals.weights must sum to 100")
    return cfg


def _u(x) -> bool:
    return isinstance(x, Unavailable)


# ---------------------------------------------------------------- types
@dataclass(frozen=True)
class MarketContext:
    as_of: int
    nifty_trend: int | Unavailable          # +1 / -1 from the index future's latest BOS/CHOCH
    breadth: float | Unavailable            # share of underlyings whose last usable 1m close is above its VWAP
    breadth_n: int
    index_positioning: str | Unavailable    # index primary positioning hypothesis


@dataclass(frozen=True)
class Evidence:
    as_of: int
    positioning: object | None              # Phase 4 PositioningState at as_of, or None
    positioning_history: tuple              # ((ts, PositioningState | None), ...) oldest first, feature-window spacing
    structure: tuple                        # Phase 5 detections of the underlying (filtered by confirmed_ts <= as_of)
    market: MarketContext


@dataclass(frozen=True)
class FamilySetup:
    family: str
    label: str
    kind: str
    direction: int
    setup_id: str
    as_of: int
    evidence: tuple
    contradictions: tuple                   # ((category, text), ...)
    warnings: tuple


@dataclass(frozen=True)
class Observation:
    underlying: str
    ts: int
    label: str                              # POSSIBLE_EXHAUSTION | SUSPECTED_ACCUMULATION | SUSPECTED_DISTRIBUTION
    setup_id: str | None
    reasons: tuple
    note: str
    config_version: str


@dataclass(frozen=True)
class Part:
    name: str
    max_points: float
    points: float | Unavailable
    detail: str


@dataclass(frozen=True)
class Factor:
    name: str
    weight: float
    points: float
    available_max: float
    parts: tuple
    missing: tuple


@dataclass(frozen=True)
class Score:
    direction: int
    kind: str
    points: float
    available_max: float
    max_points: int
    band: str
    summary: str
    factors: tuple
    missing: tuple


@dataclass(frozen=True)
class ScoreSet:
    headline: Score                         # the family's direction and kind
    bullish: Score
    bearish: Score
    continuation: Score
    reversal: Score


@dataclass(frozen=True)
class Gate:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class SignalInputs:
    """Everything `recommend` reads. Stored with each recommendation; replaying it regenerates the object."""
    setup: Setup                            # Phase 6
    evaluation: object                      # Phase 6 Evaluation at the decision time
    evidence: Evidence
    contracts: tuple                        # Phase 2 registry rows of the underlying
    tradable: Mapping                       # {token: (bool, reasons)}
    quotes: Mapping                         # {token: Quote} received at or before as_of
    spot: object | None                     # spot Quote
    bars: Mapping                           # {token: {1m end ns: close}} usable bars (option premium model)
    margins: Mapping                        # {token: INR per lot}
    portfolio: object                       # Phase 7 PortfolioState
    options: object = None                  # Phase 11 engine.options.OptionContext (None => options factor UNAVAILABLE)
    events: object = None                   # Phase 11 engine.events.EventStatus (None => options EVENT_UNVERIFIED)


@dataclass(frozen=True)
class SignalRecommendation:
    signal_id: str                          # = the Phase 6 setup id (one lifecycle per setup)
    recommendation_id: str
    as_of: int                              # decision = processing time (stream / replay ns)
    first_detected_ts: int
    confirmed_ts: int
    underlying: str
    price_token: int
    spot_token: int | None
    contract: str | Unavailable
    token: int | Unavailable
    instrument_type: str | Unavailable
    expiry: str | Unavailable
    strike: float | None | Unavailable
    lot_size: int | Unavailable
    lots: int | None | Unavailable
    quantity: int | None | Unavailable
    direction: str
    side: str | Unavailable
    setup_family: str
    setup_kind: str
    classification: str
    score: ScoreSet
    entry_trigger: int | Unavailable        # paise on the price token: the decision-time 1m close (traded price)
    entry_trigger_rule: str
    entry_range: tuple | Unavailable        # (best executable quote, walked fill) on the contract, paise
    underlying_invalidation: int | Unavailable
    contract_stop_estimate: float | None | Unavailable
    t1: int | Unavailable
    t2: int | Unavailable
    t1_contract: float | Unavailable
    t2_contract: float | Unavailable
    expected_net_rr: float | None | Unavailable
    max_planned_loss_inr: float | None | Unavailable   # incl. round-trip costs and estimated exit slippage
    full_premium_at_risk_inr: float | None | Unavailable
    gap_risk_inr: float | None | Unavailable
    capital_inr: float | None | Unavailable
    capital_method: str | None | Unavailable
    liquidity: dict
    spread_pct: float | None | Unavailable
    spread_vs_move_pct: float | None | Unavailable
    slippage_pct: float | None | Unavailable
    data_freshness: dict
    opportunity_age: dict
    why_selected: tuple
    contradicting_evidence: tuple
    reasons_to_cancel: tuple
    warnings: tuple
    labels: tuple
    gates: tuple
    risk_reasons: tuple
    candidate_tokens: tuple                 # contracts risk_check APPROVED (Tier B promotion)
    status: str                             # ENTRY_ELIGIBLE | WAIT_FOR_RETEST | REJECTED
    reasons: tuple                          # failed gates
    config_version: str
    disclaimer: str
    approval: Recommendation | None         # Phase 7 token-backed object, only when ENTRY_ELIGIBLE (not stored)


def payload(rec: SignalRecommendation) -> dict:
    """The stored / compared form (the approval token is not serializable; whether one exists is)."""
    return {**jsonable(replace(rec, approval=None)), "approval": rec.approval is not None}


# ---------------------------------------------------------------- evidence helpers (pure)
def _hyp(state) -> str | Unavailable:
    """Primary positioning hypothesis, or Unavailable when the view could not be evaluated."""
    if state is None:
        return Unavailable("NO_POSITIONING_STATE: no Phase 4 state at as_of")
    v = state.primary
    if v.positioning_hypothesis == NEUTRAL and not set(v.reasons) <= EVALUATED_NEUTRAL:
        return Unavailable("POSITIONING_UNAVAILABLE: " + ",".join(v.reasons))
    return v.positioning_hypothesis


def _dir(hyp) -> int:
    return 0 if _u(hyp) or hyp == NEUTRAL else (1 if DIRECTION[hyp] == "PRICE_UP" else -1)


def _feature(state, name):
    v = None if state is None else state.feature(name)
    return Unavailable(f"FEATURE_UNAVAILABLE: {name}") if v is None else v


def _vwap(dets, tf: int, t: int) -> int | Unavailable:
    v = [d for d in dets if d.type == "VWAP" and d.timeframe == f"{tf}m" and d.confirmed_ts <= t]
    return max(v, key=lambda d: d.confirmed_ts).level if v else Unavailable(f"INSUFFICIENT_DATA: no {tf}m VWAP")


def _turns(s: Setup, dets, t: int) -> list:
    """BOS / CHOCH on the setup timeframe confirmed after the setup's first detection, up to t."""
    return sorted((d for d in dets if d.type in ("BOS_UP", "BOS_DOWN", "CHOCH_UP", "CHOCH_DOWN")
                   and d.timeframe == f"{s.timeframe}m" and s.first_ts <= d.confirmed_ts <= t), key=lambda d: d.confirmed_ts)


def _contradictions(s: Setup, ev, x: Evidence, d: int) -> tuple:
    out = []
    if x.positioning is not None:
        for name in ("primary", "raw", "near_month"):
            h = getattr(x.positioning, name).positioning_hypothesis
            if _dir(h) == -d:
                out.append(("positioning", f"{name} positioning hypothesis {h} opposes the trade"))
    out += [("structure", f"{t.type} at {t.level / 100:.2f} after the setup") for t in _turns(s, x.structure, ev.as_of)
            if (1 if t.type.endswith("_UP") else -1) == -d]
    m = x.market
    if not _u(m.nifty_trend) and m.nifty_trend == -d:
        out.append(("market", "index trend opposes the trade"))
    if not _u(m.index_positioning) and _dir(m.index_positioning) == -d:
        out.append(("market", f"index positioning {m.index_positioning} opposes the trade"))
    return tuple(out)


def _warnings(ev) -> tuple:
    if ev.exhaustion_flags:
        return tuple(f"POSSIBLE_EXHAUSTION: {f}" for f in ev.exhaustion_flags)
    return ()


# ---------------------------------------------------------------- families (pure)
def _build(letter: str, s: Setup, ev, x: Evidence, evidence: list, warnings=()) -> FamilySetup:
    label, kind, d, _ = FAMILIES[letter]
    return FamilySetup(letter, label, kind, d, s.id, ev.as_of, tuple(evidence), _contradictions(s, ev, x, d),
                       tuple(warnings) + _warnings(ev))


def _positioning_family(letter: str, want: str, s: Setup, ev, x: Evidence, cfg):
    """A-D: shared shape. Every input must be available; any miss => None."""
    F = lambda k: cfg.get(f"signals.families.{k}")  # noqa: E731
    _, _, d, src = FAMILIES[letter]
    fw = cfg.get("positioning.feature_window_min")
    if s.source_type != src or s.direction != d or _u(ev.price) or s.broken_level is None:
        return None
    hyp, vw = _hyp(x.positioning), _vwap(x.structure, s.timeframe, ev.as_of)
    rvol, move = _feature(x.positioning, f"rvol_{fw}m"), _feature(x.positioning, f"atr_move_{fw}m")
    if hyp != want or _u(vw) or _u(rvol) or (ev.price - s.broken_level) * d < 0 or (ev.price - vw) * d <= 0:
        return None
    ev_list = [f"Phase 5 {src} through {s.broken_level / 100:.2f}; price {ev.price / 100:.2f} still beyond it",
               f"primary positioning hypothesis {hyp} (index-residual price x combined futures OI)",
               f"price {'above' if d > 0 else 'below'} the {s.timeframe}m VWAP {vw / 100:.2f}"]
    warn = []
    if letter in ("A", "B"):
        if rvol < F("rvol_elevated"):
            return None
        ev_list.append(f"RVOL {rvol:.2f} >= {F('rvol_elevated')} (elevated)")
    elif letter == "C":
        if _u(move) or move * d < F("sharp_move_atr") or rvol < F("rvol_supportive"):
            return None
        ev_list += [f"price up {move:.2f} ATR over {fw}m >= {F('sharp_move_atr')} (sharp)",
                    f"RVOL {rvol:.2f} >= {F('rvol_supportive')} (supportive)"]
        warn = ["covering, not confirmed new buying",
                "EXHAUSTION_CHECK: " + ("; ".join(ev.exhaustion_flags) or "no flag")
                + (f" (not checked: {'; '.join(ev.exhaustion_notes)})" if ev.exhaustion_notes else "")]
    else:  # D: volume persistent across the windows
        n, hist = F("persistence_windows"), x.positioning_history[-F("persistence_windows"):]
        rv = [_feature(st, f"rvol_{fw}m") for _, st in hist]
        if len(rv) < n or any(_u(v) or v < F("rvol_supportive") for v in rv):
            return None
        ev_list.append(f"RVOL {[round(v, 2) for v in rv]} >= {F('rvol_supportive')} in each of {n} x {fw}m windows (persistent)")
    return _build(letter, s, ev, x, ev_list, warn)


def _sweep_family(letter: str, s: Setup, ev, x: Evidence, cfg):
    _, _, d, src = FAMILIES[letter]
    if s.source_type != src or s.direction != d:
        return None
    sw = next((t for t in x.structure if t.id == s.id), None)
    rv = None if sw is None else sw.attrs.get("rejection_rvol")
    conf = [t for t in _turns(s, x.structure, ev.as_of) if (1 if t.type.endswith("_UP") else -1) == d]
    if rv is None or rv < cfg.get("signals.families.rejection_rvol") or not conf:
        return None
    return _build(letter, s, ev, x, [
        f"Phase 5 {src}: swept {sw.attrs.get('swept_type')} {s.broken_level / 100:.2f}, extreme {sw.attrs.get('extreme', 0) / 100:.2f}, "
        f"reclaimed in {sw.attrs.get('reclaim_bars')} bar(s)",
        f"rejection RVOL {rv:.2f} >= {cfg.get('signals.families.rejection_rvol')}",
        f"structure confirmation {conf[-1].type} at {conf[-1].level / 100:.2f} ({conf[-1].label or 'rule'})"])


def match(s: Setup, ev, x: Evidence, cfg) -> FamilySetup | None:
    """The family A-F the setup belongs to at this evaluation, or None. At most one can match (disjoint hypotheses)."""
    for letter, want in (("A", LONG_BUILDUP), ("B", SHORT_BUILDUP), ("C", SHORT_COVERING), ("D", LONG_UNWINDING)):
        fs = _positioning_family(letter, want, s, ev, x, cfg)
        if fs:
            return fs
    return _sweep_family("E", s, ev, x, cfg) or _sweep_family("F", s, ev, x, cfg)


def exhaustion_observation(s: Setup, ev, cfg) -> Observation | None:
    """G: Phase 6 POSSIBLE_EXHAUSTION as a standalone observation (never an entry in V1)."""
    if ev.exhaustion != "POSSIBLE_EXHAUSTION":
        return None
    return Observation(s.underlying, ev.as_of, "POSSIBLE_EXHAUSTION", s.id, tuple(ev.exhaustion_flags),
                       "observation only: never an entry by itself in V1; not a reversal call", cfg.version)


def accumulation(und: str, history: tuple, dets, as_of: int, cfg) -> Observation | None:
    """Persistent primary LONG_BUILDUP (SHORT_BUILDUP) over N windows with no accepted breakout (breakdown) in the span."""
    n, w = cfg.get("signals.accumulation.windows"), cfg.get("signals.accumulation.window_min")
    want = [as_of - (n - 1 - i) * w * MIN for i in range(n)]
    got = dict(history)
    hyps = {_hyp(got.get(t)) for t in want}
    if len(hyps) != 1 or next(iter(hyps)) not in (LONG_BUILDUP, SHORT_BUILDUP):
        return None
    hyp = next(iter(hyps))
    brk = "BREAKOUT_ACCEPTED" if hyp == LONG_BUILDUP else "BREAKDOWN_ACCEPTED"
    if any(d.type == brk and want[0] <= d.confirmed_ts <= as_of for d in dets):
        return None
    label = "SUSPECTED_ACCUMULATION" if hyp == LONG_BUILDUP else "SUSPECTED_DISTRIBUTION"
    return Observation(und, as_of, label, None, (
        f"primary hypothesis {hyp} at each of {n} x {w}m windows without a {brk}",
        "a persistent price/OI pattern, not evidence of institutional accumulation or distribution"), DISCLAIMER, cfg.version)


def market_context(as_of: int, index_dets, index_state, breadth_points, cfg) -> MarketContext:
    """index_dets: Phase 5 detections of the index future; breadth_points: ((close, vwap), ...) per usable underlying."""
    tf = cfg.get("signals.market.trend_timeframe_min")
    turns = [d for d in index_dets if d.type in ("BOS_UP", "BOS_DOWN", "CHOCH_UP", "CHOCH_DOWN")
             and d.timeframe == f"{tf}m" and d.confirmed_ts <= as_of]
    trend = Unavailable(f"INSUFFICIENT_DATA: no index {tf}m BOS/CHOCH yet") if not turns else \
        (1 if max(turns, key=lambda d: d.confirmed_ts).type.endswith("_UP") else -1)
    n, need = len(breadth_points), cfg.get("signals.market.breadth_min_underlyings")
    breadth = Unavailable(f"INSUFFICIENT_DATA: {n} usable underlyings < {need}") if n < need else \
        sum(c > v for c, v in breadth_points) / n
    return MarketContext(as_of, trend, breadth, n, _hyp(index_state))


# ---------------------------------------------------------------- score (pure)
def _factor(name: str, cfg, parts: list[tuple], shares=None) -> Factor:
    """parts: (name, points-or-Unavailable as a fraction of the part, detail); the weight is split equally, or by
    `shares` {part: fraction of the weight} (v17 `signals.part_shares`)."""
    w = cfg.get(f"signals.weights.{name}")
    k = (lambda n: w / len(parts)) if shares is None else (lambda n: w * shares[n])  # noqa: E731
    ps = tuple(Part(n, k(n), p if _u(p) else round(p * k(n), 4), det) for n, p, det in parts)
    ok = [p for p in ps if not _u(p.points)]
    return Factor(name, w, round(sum(p.points for p in ok), 4), round(sum(p.max_points for p in ok), 4), ps,
                  tuple(p.points.reason for p in ps if _u(p.points)))


def _agree(v, d: int, what: str):
    if _u(v):
        return v, f"{what}: {v.reason}"
    return (1.0 if v == d else 0.0), f"{what}: {'agrees' if v == d else 'does not agree'} ({v:+d})"


def score(d: int, kind: str, s: Setup, ev, x: Evidence, candidate, cfg, options=None) -> Score:
    F = lambda k: cfg.get(f"signals.{k}")  # noqa: E731
    fw = cfg.get("positioning.feature_window_min")
    hyp = _hyp(x.positioning)
    pos = hyp if _u(hyp) else (1.0 if hyp in (LONG_BUILDUP, SHORT_BUILDUP) and _dir(hyp) == d else
                               F("covering_fraction") if _dir(hyp) == d else 0.0)
    if kind == REVERSAL:
        sw = next((t for t in x.structure if t.id == s.id), None)
        rv = None if sw is None else sw.attrs.get("rejection_rvol")
        vol = Unavailable("NO_REJECTION_RVOL: Phase 5 sweep has none") if rv is None else rv
        vol_det, vol_min = "sweep rejection RVOL", F("families.rejection_rvol")
    else:
        vol, vol_det, vol_min = _feature(x.positioning, f"rvol_{fw}m"), f"RVOL {fw}m", F("families.rvol_elevated")
    vw = _vwap(x.structure, s.timeframe, ev.as_of)
    side = vw if _u(vw) else ev.price if _u(ev.price) else (1 if ev.price > vw else -1 if ev.price < vw else 0)
    turns = [t for t in _turns(s, x.structure, ev.as_of) if (1 if t.type.endswith("_UP") else -1) == d]
    m = x.market
    br = m.breadth if _u(m.breadth) else (1 if m.breadth >= F("market.breadth_bullish") else
                                         -1 if m.breadth <= F("market.breadth_bearish") else 0)
    ip = m.index_positioning if _u(m.index_positioning) else _dir(m.index_positioning)
    liq = Unavailable("NO_CANDIDATE: no priced contract for this direction") if candidate is None or \
        candidate.liquidity_score is None else candidate.liquidity_score
    try:
        shares = cfg.get("signals.part_shares.profile_depth")
    except KeyError:
        shares = None
    factors = (
        _factor("futures_positioning", cfg, [("primary_hypothesis", pos,
                f"primary positioning hypothesis: {hyp.reason if _u(hyp) else hyp}"
                f" (buildup in the trade direction = full, covering/unwinding = {F('covering_fraction')})")]),
        _factor("volume_vwap", cfg, [
            ("volume", vol if _u(vol) else float(vol >= vol_min),
             f"{vol_det}: {vol.reason if _u(vol) else f'{vol:.2f} vs {vol_min}'}"),
            ("vwap_side", *_agree(side, d, f"price vs {s.timeframe}m VWAP"))]),
        _factor("options", cfg, [("option_chain", *options_factor(
            d, None if options is None or not options.snapshots else options.snapshots[0], cfg)[1:])]),
        _factor("structure", cfg, [
            ("setup_structure", float(s.direction == d), f"Phase 5 {s.source_type} ({'with' if s.direction == d else 'against'} the trade)"),
            ("confirmation", float(bool(turns)), "BOS/CHOCH in the trade direction after the setup: "
             + (", ".join(t.type for t in turns) or "none"))]),
        _factor("profile_depth", cfg, [
            ("volume_profile", Unavailable("NO_VOLUME_PROFILE: not built (a candle-based profile would be APPROXIMATE)"),
             "volume profile: UNAVAILABLE"),
            ("visible_depth", liq, "liquidity score from 5-level visible depth (pending orders, not a full book) and spread: "
             + (liq.reason if _u(liq) else f"{liq:.2f}"))]) if shares is None else
        _factor("profile_depth", cfg, [                             # Phase 13 (v17): parts at weight 0 (Q-13-6)
            ("volume_profile", *profile_part(d, ev.price, x.structure, ev.as_of)),
            ("depth_behaviour", *depth_part(d, x.structure, ev.as_of)),
            ("visible_depth", liq, "liquidity score from 5-level visible depth (pending orders, not a full book) and spread: "
             + (liq.reason if _u(liq) else f"{liq:.2f}"))], shares),
        _factor("broad_market", cfg, [
            ("index_trend", *_agree(m.nifty_trend, d, "index trend")),
            ("breadth", *_agree(br, d, f"breadth above VWAP ({'n/a' if _u(m.breadth) else f'{m.breadth:.0%}'} of {m.breadth_n})")),
            ("index_positioning", *_agree(ip, d, "index positioning")) if not _u(ip) else
            ("index_positioning", ip, f"index positioning: {ip.reason}")]),
    )
    pts, avail = round(sum(f.points for f in factors), 2), round(sum(f.available_max for f in factors), 2)
    band = "RESEARCH_PRIORITY_HIGH" if pts >= F("bands.high") else "RESEARCH_PRIORITY_MEDIUM" if pts >= F("bands.medium") \
        else "RESEARCH_PRIORITY_LOW"
    return Score(d, kind, pts, avail, 100, band, f"{pts:g}/{avail:g} available (of 100); not a probability", factors,
                 tuple(f"{f.name}: {r}" for f in factors for r in f.missing))


# ---------------------------------------------------------------- gates and the recommendation (pure)
def _day(t: int):
    return datetime.fromtimestamp(t / S, IST).date()


def _next_level(dets, as_of: int, t1: int, d: int) -> int | Unavailable:
    beyond = sorted(lv for _, _, lv, _ in levels_at(list(dets), as_of) if (lv - t1) * d > 0)
    return (beyond[0] if d > 0 else beyond[-1]) if beyond else Unavailable("NO_LEVEL_BEYOND_T1: no known level beyond target 1")


def gates(s: Setup, ev, chosen, decision, inp: SignalInputs, has_plan: bool, cfg) -> tuple:
    stale = cfg.get("quality.stale_price_s")
    lim = [] if chosen is None else limit_reasons(chosen, cfg)
    checks = {} if decision is None else {c.name: c for c in decision.checks}
    no = "no priced candidate"
    trad = [t for t in (s.token, None if chosen is None else chosen.token) if t is not None and not inp.tradable.get(t, (False,))[0]]
    data = list(ev.missing) + ([f"price age {ev.price_age_s} s > {stale} s"] if ev.price_age_s is None or ev.price_age_s > stale else []) \
        + ([] if chosen is None else [r for r in chosen.reasons if r.startswith(("DATA_NOT_OK", "NO_PREMIUM_MODEL"))])
    p = inp.portfolio
    open_ = p.open_underlyings if cfg.get("signals.single_position_mode") else \
        tuple(u for u in p.open_underlyings if u == s.underlying)
    daily = [n for n in ("DAILY_LOSS_LIMIT", "MAX_DAILY_TRADES", "MAX_OPEN_POSITIONS", "CONSECUTIVE_LOSSES_COOLDOWN")
             if n not in checks or not checks[n].passed]
    geo = None if chosen is None else next((r for r in chosen.reasons if r.startswith("BAD_GEOMETRY")), None)
    return (
        Gate("INSTRUMENT_TRADABLE", chosen is not None and not trad,
             no if chosen is None else "; ".join(f"{t}: {','.join(inp.tradable.get(t, (False, ['NOT_CHECKED']))[1])}"
                                                   for t in trad) or "price instrument and contract tradable"),
        Gate("DATA_QUALITY", not data, "; ".join(data) or f"price age {ev.price_age_s} s; quote OK"),
        Gate("LIQUIDITY_MINIMUM", chosen is not None and chosen.quantity is not None and not any(r.startswith("ILLIQUID") for r in lim),
             no if chosen is None else "; ".join(r for r in chosen.reasons if r.startswith("ILLIQUID"))
             or ("not sized: " + "; ".join(chosen.reasons) if chosen.quantity is None else "volume, OI, depth OK")),
        Gate("SPREAD_ACCEPTABLE", chosen is not None and chosen.spread_pct is not None and not any(r.startswith("SPREAD_") for r in lim),
             no if chosen is None else "; ".join(r for r in lim if r.startswith("SPREAD_")) or f"spread {chosen.spread_pct} %"),
        Gate("RISK_CHECK_APPROVED", decision is not None and decision.status == APPROVED,
             "no risk decision" if decision is None else decision.status),
        Gate("VALID_ENTRY_STOP", has_plan and geo is None and not _u(ev.current_rr) and ev.current_rr > 0,
             geo or ("structural stop, entry and target 1 defined" if has_plan else
                     "no defensible stop / target / R:R: " + "; ".join(ev.missing))),
        Gate("TIMELINESS", ev.classification == TIMELY, f"Phase 6 {ev.classification} ({ev.reason})"),
        Gate("NO_CONFLICTING_POSITION", not open_, f"open: {', '.join(open_)}" if open_ else "no conflicting open position"),
        Gate("DAILY_LIMITS", not daily, "no risk decision" if decision is None else
             "failed: " + ", ".join(daily) if daily else "within daily limits"),
        Gate("COST_MODEL_VERIFIED", "NET_RR_VERIFIED" in checks and checks["NET_RR_VERIFIED"].passed,
             checks["NET_RR_VERIFIED"].detail if "NET_RR_VERIFIED" in checks else "no risk decision"),
    )


def recommend(inp: SignalInputs, cfg) -> SignalRecommendation:
    s, ev, x = inp.setup, inp.evaluation, inp.evidence
    fs = match(s, ev, x, cfg)
    if fs is None:
        raise ValueError(f"{s.id}: no family matches these inputs; nothing to recommend")
    d, day = fs.direction, _day(ev.as_of)
    t1 = Unavailable("NO_TARGET: no obstacle in the trade direction") if ev.obstacle is None else ev.obstacle[2]
    t2 = t1 if _u(t1) else _next_level(x.structure, ev.as_of, t1, d)
    has_plan = not any(_u(v) for v in (ev.price, s.structural_stop, ev.atr, t1))
    chosen = decision = None
    approved = []
    if has_plan:
        ts = TradeSetup(f"{s.id}@{ev.as_of}", s.underlying, d, day, ev.as_of, s.token, ev.price, s.structural_stop,
                        (t1,) + (() if _u(t2) else (t2,)), ev.atr)
        sel = select_contracts(ts, list(inp.contracts), inp.tradable, inp.quotes, inp.spot, inp.bars, inp.margins, cfg,
                               chain=inp.options, events=inp.events)
        decisions = [(c, risk_check(c, inp.portfolio, cfg)) for c in sel.candidates]
        approved = [(c, r) for c, r in decisions if r.status == APPROVED]
        chosen, decision = (approved or decisions or [(None, None)])[0]
    gs = gates(s, ev, chosen, decision, inp, has_plan, cfg)
    failed = tuple(g.name for g in gs if not g.passed)
    status = ENTRY_ELIGIBLE if not failed else \
        WAIT_FOR_RETEST if failed == ("TIMELINESS",) and ev.classification == LATE else REJECTED
    strong = [t for c, t in fs.contradictions if c in STRONG_CONTRADICTIONS]
    cls = "NO_TRADE" if "VALID_ENTRY_STOP" in failed else "UNCERTAIN" if "DATA_QUALITY" in failed else \
        "CONFLICTING_EVIDENCE" if strong else fs.label
    sc = lambda dd, k: score(dd, k, s, ev, x, chosen if dd == fs.direction else None, cfg, inp.options)  # noqa: E731
    if chosen is not None and chosen.kind in OPTION_KINDS and inp.options is not None:
        prem, ivc = option_changes(inp.options.analytics.get(chosen.token), inp.options.ref.get(chosen.token))
    else:
        why = ("NO_CANDIDATE" if chosen is None else "NOT_AN_OPTION: the selected contract is a future" if
               chosen.kind not in OPTION_KINDS else "NO_OPTION_CONTEXT: no recorded option chain")
        prem = ivc = Unavailable(why)
    ev = replace(ev, option_premium_change=prem, option_iv_change=ivc)   # Phase 6 fields, filled here (D-52)
    scores = ScoreSet(sc(d, fs.kind), sc(1, fs.kind), sc(-1, fs.kind), sc(d, CONTINUATION), sc(d, REVERSAL))
    na = Unavailable("NO_CANDIDATE: " + ("no contract was priced" if has_plan else "no defensible stop / target"))
    c = lambda a: na if chosen is None else getattr(chosen, a)  # noqa: E731
    exe = None if chosen is None or chosen.bid is None else (chosen.ask if chosen.side == "BUY" else chosen.bid)
    plan = ev.retest_plan
    cutoff = cfg.get("risk.intraday_cutoff")
    return SignalRecommendation(
        signal_id=s.id, recommendation_id=f"{s.id}@{ev.as_of}", as_of=ev.as_of, first_detected_ts=s.first_ts,
        confirmed_ts=s.confirmed_ts, underlying=s.underlying, price_token=s.token,
        spot_token=None if inp.spot is None else inp.spot.token,
        contract=c("tradingsymbol"), token=c("token"), instrument_type=c("kind"),
        expiry=na if chosen is None else chosen.expiry.isoformat(), strike=c("strike"), lot_size=c("lot_size"),
        lots=c("lots"), quantity=c("quantity"), direction="LONG" if d > 0 else "SHORT", side=c("side"),
        setup_family=fs.family, setup_kind=fs.kind, classification=cls, score=scores,
        entry_trigger=ev.price, entry_trigger_rule="near-month future 1m close at the decision time (a traded price); "
                                                   "act only on an executable quote inside entry_range",
        entry_range=na if exe is None else (exe, chosen.entry), underlying_invalidation=s.structural_stop,
        contract_stop_estimate=c("stop"), t1=t1, t2=t2,
        t1_contract=na if chosen is None or not chosen.targets else chosen.targets[0],
        t2_contract=t2 if _u(t2) else na if chosen is None or len(chosen.targets) < 2 else chosen.targets[1],
        expected_net_rr=c("rr_net"), max_planned_loss_inr=c("planned_risk_inr"),
        full_premium_at_risk_inr=c("full_premium_at_risk_inr"), gap_risk_inr=c("gap_risk_inr"),
        capital_inr=c("required_capital_inr"), capital_method=c("capital_method"),
        liquidity={} if chosen is None else {
            "volume_lots": None if chosen.volume_day is None else chosen.volume_day / chosen.lot_size,
            "oi_lots": None if chosen.oi is None else chosen.oi / chosen.lot_size,
            "visible_depth_bid_ask": (chosen.depth_bid_qty, chosen.depth_ask_qty), "liquidity_score": chosen.liquidity_score,
            "note": "pending quantities in 5 visible levels: not executed volume and not a full order book"},
        spread_pct=c("spread_pct"), spread_vs_move_pct=c("spread_vs_move_pct"), slippage_pct=c("slippage_pct"),
        data_freshness={"price_ts": ev.price_ts, "price_receive_ns": ev.price_receive_ns, "price_age_s": ev.price_age_s,
                        "quote_source": c("source"), "quote_exchange_ts_ns": c("exchange_ts_ns"),
                        "quote_receive_ns": c("receive_ns"), "quote_age_s": c("age_s"), "processed_ns": ev.as_of,
                        "positioning_ts": None if x.positioning is None else x.positioning.ts_ns},
        opportunity_age={k: getattr(ev, k) for k in (
            "classification", "reason", "failed_rules", "age_first_s", "age_confirmed_s", "extension_atr",
            "extension_confirmed_atr", "obstacle_distance_atr", "stop_distance_atr", "current_rr", "pre_signal_move_atr",
            "exhaustion", "exhaustion_flags", "option_premium_change", "option_iv_change")},
        why_selected=fs.evidence, contradicting_evidence=tuple(f"{c_}: {t}" for c_, t in fs.contradictions),
        reasons_to_cancel=("no structural stop" if _u(s.structural_stop) else
                           f"a 1m close at or through the structural stop {s.structural_stop / 100:.2f}",
                           "the Phase 6 evaluation is no longer TIMELY", f"intraday cutoff {cutoff} IST",
                           "an exhaustion flag appears") + ((f"retest plan expires at ns {plan.expires_ts}",) if plan else ()),
        warnings=fs.warnings, labels=() if chosen is None else chosen.labels, gates=gs,
        risk_reasons=() if decision is None else decision.reasons,
        candidate_tokens=tuple(a.token for a, _ in approved), status=status, reasons=failed, config_version=cfg.version,
        disclaimer=DISCLAIMER,
        approval=Recommendation(chosen, decision.token) if status == ENTRY_ELIGIBLE else None)


# ---------------------------------------------------------------- lifecycle (pure)
class IllegalTransition(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    signal_id: str
    seq: int
    ts: int
    from_state: str | None
    to_state: str
    cause: str


@dataclass(frozen=True)
class Lifecycle:
    signal_id: str
    rows: tuple

    @property
    def state(self) -> str | None:
        return self.rows[-1].to_state if self.rows else None


def advance(lc: Lifecycle, to: str, ts: int, cause: str) -> Lifecycle:
    cur = lc.state
    if to not in ALLOWED.get(cur, set()):
        raise IllegalTransition(f"{lc.signal_id}: {cur} -> {to} is not allowed")
    if lc.rows and ts < lc.rows[-1].ts:
        raise IllegalTransition(f"{lc.signal_id}: {to} at {ts} is before the last transition at {lc.rows[-1].ts}")
    return Lifecycle(lc.signal_id, lc.rows + (Transition(lc.signal_id, len(lc.rows), ts, cur, to, cause),))


def start(signal_id: str, ts: int, cause: str) -> Lifecycle:
    return advance(Lifecycle(signal_id, ()), DETECTED, ts, cause)


def drive(s: Setup, evaluations, evidence_at: Callable, inputs_at: Callable, close_ns: int, cfg):
    """One Phase 6 setup through the lifecycle over its evaluations (owner-accepted Q-8-3: never past ENTRY_ELIGIBLE).
    evidence_at(setup, as_of) -> Evidence; inputs_at(setup, evaluation, evidence) -> SignalInputs.
    -> (Lifecycle | None, [(SignalRecommendation, SignalInputs)]). Setups no family can come from -> (None, [])."""
    evs = list(evaluations)
    if s.source_type not in SOURCES or not evs:
        return None, []
    lc = start(s.id, s.first_ts, f"Phase 5 {s.source_type} first detected")
    lc = advance(lc, WATCHING, s.confirmed_ts, "Phase 5 confirmation; Phase 6 evaluations start")
    cutoff, out = _ns(_day(s.confirmed_ts), cfg.get("risk.intraday_cutoff")), []
    for ev in evs:
        st = lc.state
        if ev.state == "INVALIDATED":
            lc = advance(lc, INVALIDATED, ev.as_of, f"Phase 6 {ev.reason}")
        elif ev.state == "RETEST_EXPIRED":
            lc = advance(lc, EXPIRED, ev.as_of, f"Phase 6 {ev.reason}")
        elif ev.as_of >= cutoff:
            lc = advance(lc, EXPIRED, ev.as_of, f"INTRADAY_CUTOFF {cfg.get('risk.intraday_cutoff')}")
        elif st == ENTRY_ELIGIBLE:
            if ev.classification != TIMELY:
                lc = advance(lc, EXPIRED, ev.as_of, f"NO_LONGER_TIMELY: Phase 6 {ev.classification}")
            continue
        elif st == WAIT_FOR_RETEST and ev.classification != TIMELY:
            continue
        else:
            x = evidence_at(s, ev.as_of)
            fs = match(s, ev, x, cfg)
            if fs is None:
                continue
            lc = advance(lc, CONFIRMED, ev.as_of, f"{fs.family} {fs.label}: " + "; ".join(fs.evidence))
            inp = inputs_at(s, ev, x)
            rec = recommend(inp, cfg)
            out.append((rec, inp))
            lc = advance(lc, rec.status, ev.as_of, "failed gates: " + ", ".join(rec.reasons) if rec.reasons else
                         "every gate passed")
        if lc.state in TERMINAL:
            break
    if lc.state not in TERMINAL and evs[-1].as_of >= close_ns:
        lc = advance(lc, EXPIRED, evs[-1].as_of, "SESSION_CLOSE")
    return lc, out


# ---------------------------------------------------------------- Tier B promotion
def promotions(recs, cfg) -> list[tuple[int, str, float]]:
    """(token, reason, ttl_s) for the underlying (price instrument + spot) and approved contracts of ENTRY_ELIGIBLE signals."""
    out, ttl = {}, cfg.get("signals.tier_b_ttl_s")
    for r in recs:
        if r.status == ENTRY_ELIGIBLE:
            for t in (r.price_token, r.spot_token, *r.candidate_tokens):
                if t is not None:
                    out.setdefault(t, (t, f"Phase 8 ENTRY_ELIGIBLE {r.signal_id} {r.setup_family}", ttl))
    return list(out.values())


def promote(book, reqs) -> None:
    """Apply promotions through the Phase 3 API (TierBook.promote). Not wired into the live recorder (Q-8-4)."""
    for token, reason, ttl in reqs:
        book.promote(token, reason, ttl)
