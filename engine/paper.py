"""Phase 9: paper broker, live trade monitor, alerts and feedback objects (pure). Advisory and paper-trading only:
nothing here places, modifies or cancels an order; a SIMULATED fill is a computation against a recorded quote.

Pure core: `paper_fill(side, qty, lot, quote, as_of, cfg)`, `Monitor` (a streaming state machine, like the Phase 3
Aggregator and Phase 5 Detector) and `run_trades(trades, events, inputs_at, cfg, realized)` read no clock, disk or
network; time is the event's receive time (stream / replay time). The store and the replay over recorded sessions are
in engine.ledger (edge). Thresholds: config v11 `monitor.*`, `risk.*`, `quality.*`.

Ledgers: SIMULATED (paper fills) and ACTUAL (trades the user took, entered by hand). They are never summed: every
object carries its ledger, and risk_check runs on each ledger's PortfolioState separately (owner, Q-9-2).

Monitor rules (owner Q-9-3 / Q-9-4; the rest ASSUMED Q-9-8 / Q-9-9, docs/questions-ledger.md):
- every tick: price token at or through the current stop ⇒ EXIT_REQUIRED (HARD_STOP_UNDERLYING); a FUTURES contract at
  or through its stop ⇒ EXIT_REQUIRED (HARD_STOP_CONTRACT). An OPTION's contract stop is an APPROXIMATE premium-model
  estimate (Phase 7), so a premium below it is a warning, never an exit: a premium decline without structural
  invalidation must not exit (phase text). T1 on the price token ⇒ PARTIAL_EXIT_CANDIDATE (once).
- every event / timer: at or after `monitor.squareoff_cutoff` ⇒ EXIT_REQUIRED; price or contract older than
  `quality.stale_price_s`, contract book older than `quality.stale_depth_s`, a recorder gap or a disconnect ⇒
  DATA_UNAVAILABLE (left only at the next review with every input fresh); estimated net P&L <= -risk.max_risk_per_trade_inr
  ⇒ EXIT_REQUIRED; the ledger's realized + unrealized net <= -risk.max_daily_loss_inr ⇒ EXIT_REQUIRED for its open trades.
- every `monitor.review_interval_s` and on each fresh OI change of the price token: thesis review. A critical input
  missing ⇒ DATA_UNAVAILABLE; Phase 6 INVALIDATED or a 1m close at or through the stop ⇒ EXIT_REQUIRED; breakeven at
  `monitor.breakeven_at_r` R or a confirmed Phase 5 swing beyond the stop ⇒ TIGHTEN_STOP; otherwise HOLD with warnings
  (opposite positioning, VWAP on the wrong side, exhaustion, wide spread, opposite signals). Warnings never exit.
- EXIT_REQUIRED is terminal for the monitor. Every decision carries its triggering observations (value + timestamps),
  the rule id, gross and estimated net P&L (UNAVAILABLE when the data is), and the config version.
"""

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Protocol

from . import signals as G
from .candles import IST, S, Unavailable, _ns
from .contract_report import quote_from_rows
from .contracts import OPTION_KINDS, Quote, quote_problem
from .costs import fill as walk, require, round_trip
from .risk import REJECTED, PortfolioState, RiskDecision, risk_check

DEFAULT_CONFIG = G.REPO / "config" / "engine" / "v24.yaml"   # Phase 15: risk answers D-61/D-62 apply to the paper ledger too
REQUIRED = ["monitor.squareoff_cutoff", "monitor.review_interval_s", "monitor.breakeven_at_r",
            "monitor.trail_swing_timeframes", "paper.ledger_file", "quality.stale_price_s", "quality.stale_depth_s",
            "risk.max_risk_per_trade_inr", "risk.max_daily_loss_inr", "risk.max_spread_pct"]

SIMULATED, ACTUAL = "SIMULATED", "ACTUAL"
LEDGERS = (SIMULATED, ACTUAL)
HOLD, TIGHTEN_STOP, PARTIAL_EXIT_CANDIDATE, EXIT_REQUIRED, DATA_UNAVAILABLE = (
    "HOLD", "TIGHTEN_STOP", "PARTIAL_EXIT_CANDIDATE", "EXIT_REQUIRED", "DATA_UNAVAILABLE")
ALWAYS_ALERT = {TIGHTEN_STOP, PARTIAL_EXIT_CANDIDATE, EXIT_REQUIRED}
POSITIONING_FAMILIES = {"A", "B", "C", "D"}        # their evidence is the positioning hypothesis (Q-8-9)
DISCONNECTS = {"close", "error", "stall", "shutdown"}
BEHAVED = ("yes", "no", "partly")


def load(path=DEFAULT_CONFIG):
    return require(G.load(path), REQUIRED, path)


def _u(x) -> bool:
    return isinstance(x, Unavailable)


def _iso(ns: int | None) -> str:
    return "—" if ns is None else datetime.fromtimestamp(ns / S, IST).isoformat(timespec="milliseconds")


# ---------------------------------------------------------------- types
@dataclass(frozen=True)
class Obs:
    """One triggering observation, exactly as received."""
    field: str                      # ltp | bid | ask | oi | close_1m | gap | disconnect | clock | ledger_day_pnl_net
    token: int                      # -1 = not an instrument
    value: Any
    exchange_ts_ns: int | None      # None = the source carries no exchange time
    receive_ns: int | None
    source: str


@dataclass(frozen=True)
class PaperFill:
    side: str                       # BUY at the ask side, SELL at the bid side
    qty_requested: int
    qty_filled: int                 # whole lots that the visible book holds
    avg_price: float                # paise per unit
    mid: float
    slippage_per_unit: float        # avg vs mid, paise, signed against us
    method: str                     # DEPTH_5_LEVELS | ESTIMATED_SPREAD_MULTIPLE (touch only)
    partial: bool
    quote: dict                     # the quote snapshot used, as received
    as_of: int
    label: str = SIMULATED
    trade_id: str = ""


@dataclass(frozen=True)
class Trade:
    id: str
    ledger: str                     # SIMULATED | ACTUAL
    recommendation_id: str
    signal_id: str
    underlying: str
    family: str                     # Phase 8 family letter
    direction: int                  # +1 long the underlying, -1 short
    day: Any                        # date
    price_token: int                # the instrument the levels are on (near-month future)
    contract_token: int
    kind: str                       # FUT | CE | PE
    side: str                       # BUY | SELL (options: BUY only)
    qty: int                        # units filled at entry
    lot_size: int
    entry_price: float              # contract, paise per unit
    entry_ns: int
    underlying_entry: int           # paise on price_token
    underlying_stop: int            # structural stop on price_token, paise
    contract_stop: float | None     # FUT: hard; options: APPROXIMATE estimate (warning only)
    t1: int | None                  # price_token, paise
    t1_contract: float | None
    config_version: str

    def __post_init__(self):
        if self.ledger not in LEDGERS:
            raise ValueError(f"ledger must be one of {LEDGERS}, not {self.ledger!r}")


@dataclass(frozen=True)
class ReviewInputs:
    as_of: int
    setup_state: str | Unavailable          # Phase 6 ACTIVE | INVALIDATED | RETEST_EXPIRED
    close_1m: Obs | Unavailable             # last usable 1m close of the price token (Phase 6 price)
    classification: str | None | Unavailable  # Phase 6 TIMELY | VALID_BUT_LATE | EXHAUSTED | UNKNOWN
    exhaustion_flags: tuple
    positioning: str | Unavailable          # primary Phase 4 hypothesis of the underlying
    vwap: int | Unavailable                 # setup-timeframe session VWAP, paise
    swings: tuple                           # ((type, timeframe, level, confirmed_ts, id), ...) Phase 5
    opposite_signals: tuple                 # recommendation ids in the other direction, as_of <= review time


@dataclass(frozen=True)
class Decision:
    trade_id: str
    ledger: str
    as_of: int
    decision: str
    rule_id: str
    stop: int                               # current stop on the price token after this decision
    observations: tuple
    pnl_gross_inr: float | Unavailable
    pnl_net_inr: float | Unavailable        # estimated: gross minus round-trip charges at the executable mark
    warnings: tuple
    config_version: str


@dataclass(frozen=True)
class Alert:
    trade_id: str
    ledger: str
    as_of: int
    decision: str
    previous: str | None
    rule_id: str
    observations: tuple
    message: str
    config_version: str


@dataclass(frozen=True)
class LifecycleRow:
    ledger: str
    trade_id: str
    signal_id: str
    ts: int
    from_state: str
    to_state: str
    cause: str


@dataclass(frozen=True)
class NoFill:
    trade_id: str
    as_of: int
    side: str
    qty: int
    reason: str


@dataclass(frozen=True)
class Result:
    decisions: list
    alerts: list
    fills: list                             # SIMULATED exit fills only
    no_fills: list
    lifecycle: list
    trades: list = field(default_factory=list)


@dataclass(frozen=True)
class Feedback:
    """Stored only: no weight, threshold or config changes anywhere (phase text)."""
    ledger: str
    trade_id: str | None
    recommendation_id: str
    taken: bool
    skip_reason: str | None
    actual_entry: float | None              # paise
    actual_exit: float | None
    slippage: float | None                  # paise per unit
    execution_quality: str | None
    behaved_as_expected: str | None         # yes | no | partly (None only when skipped)
    notes: str

    def __post_init__(self):
        if self.ledger not in LEDGERS:
            raise ValueError(f"ledger must be one of {LEDGERS}")
        if self.behaved_as_expected not in BEHAVED and not (self.behaved_as_expected is None and not self.taken):
            raise ValueError(f"behaved_as_expected must be one of {BEHAVED}")


@dataclass(frozen=True)
class RiskPair:
    simulated: RiskDecision
    actual: RiskDecision

    @property
    def approved(self) -> bool:
        return self.simulated.status != REJECTED and self.actual.status != REJECTED


class AlertSink(Protocol):
    def send(self, alert: Alert) -> None: ...


def deliver(alerts: Iterable[Alert], sink: AlertSink) -> None:
    """In-app delivery is the ledger's `alerts` table (engine.ledger.InAppSink); later channels implement AlertSink."""
    for a in alerts:
        sink.send(a)


# ---------------------------------------------------------------- risk on both ledgers (Q-9-2)
def risk_both(c, sim: PortfolioState | Unavailable, act: PortfolioState | Unavailable, cfg) -> RiskPair:
    """risk_check once per ledger, never on a summed state. An unknown state rejects (fewer trades)."""
    def one(p, name):
        if _u(p):
            return RiskDecision(c.id, REJECTED, (f"PORTFOLIO_STATE: {name} UNAVAILABLE ({p.reason})",), (), None, None,
                                None, c.as_of, cfg.version, None)
        return risk_check(c, p, cfg)
    return RiskPair(one(sim, SIMULATED), one(act, ACTUAL))


# ---------------------------------------------------------------- paper broker
def paper_fill(side: str, qty: int, lot: int, q: Quote | None, as_of: int, cfg) -> PaperFill | Unavailable:
    """BUY walks the asks, SELL the bids, up to whole lots the visible book holds; nothing visible ⇒ no fill."""
    if not isinstance(qty, int) or not isinstance(lot, int) or qty <= 0 or lot <= 0:
        return Unavailable(f"NO_FILL: no sized quantity (qty {qty!r}, lot {lot!r})")
    why = quote_problem(q, as_of, cfg.get("quality.stale_depth_s"))
    if why:
        return Unavailable(f"NO_FILL: {why}")
    book = q.asks if side == "BUY" else q.bids
    visible = sum(level[1] for level in (book if q.depth else book[:1]))
    filled = min(qty, visible) // lot * lot
    if filled <= 0:
        return Unavailable(f"NO_FILL: visible {'depth' if q.depth else 'touch'} {visible} < one lot of {lot}")
    f = walk(q.bids, q.asks, q.depth, side, filled, cfg)
    snap = {**asdict(q), "bids": [list(x) for x in q.bids], "asks": [list(x) for x in q.asks]}
    return PaperFill(side, qty, filled, f.avg_price, f.mid, (1 if side == "BUY" else -1) * (f.avg_price - f.mid),
                     f.method, filled < qty, snap, as_of)


# ---------------------------------------------------------------- monitor (one trade)
class Monitor:
    def __init__(self, t: Trade, cfg):
        self.t, self.cfg = t, cfg
        self.d = t.direction
        self.cd = 1 if t.side == "BUY" else -1             # contract direction
        self.stop = t.underlying_stop
        self.R = self.d * (t.underlying_entry - t.underlying_stop)
        self.rv = cfg.get("monitor.review_interval_s") * S
        self.next_review = t.entry_ns + self.rv
        self.cutoff = _ns(t.day, cfg.get("monitor.squareoff_cutoff"))
        self.price = self.cprice = self.quote = None
        self.ticks: dict[int, dict] = {}
        self.oi, self.oi_change = None, None
        self.t1_done = self.closed = False
        self.last: str | None = None
        self.notes: list[str] = []
        self.out: list[Decision] = []

    # ---- P&L at the executable mark (bid for a long contract, ask for a short)
    def pnl(self, now: int):
        why = quote_problem(self.quote, now, self.cfg.get("quality.stale_depth_s"))
        if why:
            u = Unavailable(f"PNL_UNAVAILABLE: contract quote {why}")
            return u, u
        t, mark = self.t, (self.quote.bids[0][0] if self.cd > 0 else self.quote.asks[0][0])
        gross = self.cd * (mark - t.entry_price) * t.qty / 100
        c = round_trip(self.cfg, "OPT" if t.kind in OPTION_KINDS else "FUT", t.side, t.entry_price / 100, mark / 100,
                       t.qty, t.day)
        return round(gross, 2), round(gross - c.total_inr, 2)

    def _quote_obs(self) -> tuple:
        q = self.quote
        if q is None:
            return ()
        src = q.source
        return (Obs("bid", q.token, q.bids[0][0] if q.bids else None, q.exchange_ts_ns, q.receive_ns, src),
                Obs("ask", q.token, q.asks[0][0] if q.asks else None, q.exchange_ts_ns, q.receive_ns, src))

    def emit(self, now: int, decision: str, rule: str, obs: tuple, warnings: tuple = ()) -> None:
        if decision == DATA_UNAVAILABLE:
            u = Unavailable("DATA_UNAVAILABLE: nothing inferred")
            gross, net = u, u
        else:
            gross, net = self.pnl(now)
        self.out.append(Decision(self.t.id, self.t.ledger, now, decision, rule, self.stop, tuple(obs), gross, net,
                                 tuple(warnings), self.cfg.version))
        self.last = decision
        self.closed = decision == EXIT_REQUIRED

    # ---- freshness of the inputs the hard rules need
    def stale(self, now: int) -> tuple[str, tuple] | None:
        lim, t = self.cfg.get("quality.stale_price_s") * S, self.t
        clock = Obs("clock", -1, _iso(now), None, now, "stream time")
        for rule, o, tok in (("STALE_PRICE", self.price, t.price_token), ("STALE_CONTRACT_PRICE", self.cprice, t.contract_token)):
            if now - (o.receive_ns if o else t.entry_ns) > lim:
                return rule, ((o,) if o else (Obs("ltp", tok, "NONE_SINCE_ENTRY", None, t.entry_ns, "stream"),)) + (clock,)
        if self.quote is None:
            if now - t.entry_ns > self.cfg.get("quality.stale_depth_s") * S:
                return "STALE_QUOTE", (Obs("book", t.contract_token, "NONE_SINCE_ENTRY", None, t.entry_ns, "stream"), clock)
        elif (why := quote_problem(self.quote, now, self.cfg.get("quality.stale_depth_s"))):
            return "STALE_QUOTE", self._quote_obs() + (Obs("quote_problem", t.contract_token, why, None, now, "derived"),)
        return None

    # ---- events
    def on_event(self, e) -> None:
        if self.closed:
            return
        now, t = e.receive_ns, self.t
        if e.kind == "gap":
            g = dict(e.data)
            self.emit(now, DATA_UNAVAILABLE, "FEED_GAP", (Obs("gap", -1, g, None, now, "recorder gaps"),),
                      (f"FEED_GAP: {g.get('kind')} {_iso(g.get('start_ns'))} → {_iso(g.get('end_ns'))}: {g.get('reason')}",))
        elif e.kind == "conn" and dict(e.data).get("event") in DISCONNECTS:
            c = dict(e.data)
            self.emit(now, DATA_UNAVAILABLE, "FEED_DISCONNECT", (Obs("disconnect", -1, c, None, now, "recorder events"),))
        elif e.kind == "tick" and e.token in (t.price_token, t.contract_token):
            self.ticks[e.token] = dict(e.data)
            self._tick(e.token, dict(e.data), now, e.exchange_ts)
        elif e.kind == "depth" and e.token == t.contract_token:
            d = {**dict(e.data), "exchange_ts": e.exchange_ts, "receive_ns": now}
            self.quote = quote_from_rows(e.token, d, self.ticks.get(e.token))
        self.clock(now)

    def _tick(self, tok: int, d: dict, now: int, ex) -> None:
        ltp, t = d.get("ltp"), self.t
        if ltp is None:
            return
        o = Obs("ltp", tok, ltp, ex * S if ex else None, now, "kite.ws tick")
        if tok == t.price_token:
            self.price = o
            if self.d * (ltp - self.stop) <= 0:
                return self.emit(now, EXIT_REQUIRED, "HARD_STOP_UNDERLYING",
                                 (o, Obs("stop", tok, self.stop, None, None, "trade stop")))
            if not self.t1_done and t.t1 is not None and self.d * (ltp - t.t1) >= 0:
                self.t1_done = True
                self.emit(now, PARTIAL_EXIT_CANDIDATE, "T1_REACHED", (o, Obs("t1", tok, t.t1, None, None, "Phase 8 T1")))
            oi = d.get("oi")
            if oi is not None:
                if self.oi is not None and oi != self.oi:
                    self.oi_change = Obs("oi", tok, oi, o.exchange_ts_ns, now, "kite.ws tick")
                self.oi = oi
        if tok == t.contract_token:
            self.cprice = o
            if t.contract_stop is not None and self.cd * (ltp - t.contract_stop) <= 0:
                if t.kind == "FUT":
                    return self.emit(now, EXIT_REQUIRED, "HARD_STOP_CONTRACT",
                                     (o, Obs("contract_stop", tok, t.contract_stop, None, None, "Phase 7 contract stop")))
                if not any(n.startswith("CONTRACT_BELOW_STOP_ESTIMATE") for n in self.notes):
                    self.notes.append(f"CONTRACT_BELOW_STOP_ESTIMATE: premium {ltp} at {_iso(o.exchange_ts_ns or now)} vs "
                                      f"{t.contract_stop:.0f} (APPROXIMATE premium model); no structural invalidation")

    def clock(self, now: int) -> None:
        if self.closed:
            return
        if now >= self.cutoff:
            return self.emit(now, EXIT_REQUIRED, "SQUAREOFF_CUTOFF",
                             (Obs("clock", -1, _iso(now), None, now, f"stream time vs cutoff {self.cfg.get('monitor.squareoff_cutoff')} IST"),))
        st = self.stale(now)
        if st:
            if self.last != DATA_UNAVAILABLE:
                self.emit(now, DATA_UNAVAILABLE, st[0], st[1])
            return
        _, net = self.pnl(now)
        if not _u(net) and net <= -self.cfg.get("risk.max_risk_per_trade_inr"):
            self.emit(now, EXIT_REQUIRED, "MAX_LOSS_PER_TRADE", self._quote_obs() + (
                Obs("pnl_net_inr", -1, net, None, now, "derived: gross − round-trip charges at the executable mark"),))

    def review_due(self, now: int) -> bool:
        return not self.closed and (now >= self.next_review or self.oi_change is not None)

    def review(self, inp: ReviewInputs, now: int) -> None:
        self.next_review, oi_obs, self.oi_change = now + self.rv, self.oi_change, None
        notes, self.notes = self.notes, []
        if self.closed:
            return
        t, d = self.t, self.d
        missing = []
        st = self.stale(now)
        if st:
            missing.append(st[0])
        if _u(inp.setup_state):
            missing.append(f"SETUP_STATE: {inp.setup_state.reason}")
        c = inp.close_1m
        if _u(c):
            missing.append(f"CLOSE_1M: {c.reason}")
        elif now - c.receive_ns > self.rv:
            missing.append(f"CLOSE_1M: {(now - c.receive_ns) / S:.0f} s old > review interval")
        if t.family in POSITIONING_FAMILIES and _u(inp.positioning):
            missing.append(f"POSITIONING: {inp.positioning.reason}")
        obs = tuple(o for o in (self.price, c if not _u(c) else None, oi_obs) if o) + self._quote_obs()
        if missing:
            return self.emit(now, DATA_UNAVAILABLE, "THESIS_INPUT_UNAVAILABLE", obs, tuple(missing))
        if inp.setup_state == "INVALIDATED" or d * (c.value - self.stop) <= 0:
            return self.emit(now, EXIT_REQUIRED, "STRUCTURAL_INVALIDATION",
                             (c, Obs("stop", t.price_token, self.stop, None, None, "trade stop"), Obs(
                                 "setup_state", t.price_token, inp.setup_state, None, inp.as_of, "Phase 6 evaluation")))
        px = self.price.value
        cands = []
        if px is not None and d * (px - t.underlying_entry) >= self.cfg.get("monitor.breakeven_at_r") * self.R \
                and d * (t.underlying_entry - self.stop) > 0:
            cands.append((t.underlying_entry, "BREAKEVEN_AT_1R", None))
        want = "SWING_LOW" if d > 0 else "SWING_HIGH"
        for typ, tf, level, conf, sid in inp.swings:
            if typ == want and tf in self.cfg.get("monitor.trail_swing_timeframes") and t.entry_ns < conf <= now \
                    and d * (level - self.stop) > 0 and d * (px - level) > 0:
                cands.append((level, "TRAIL_CONFIRMED_SWING", Obs("swing", t.price_token, level, conf, None,  # no receive time (Q-6-2)
                                                                   f"Phase 5 {typ} {tf} {sid} (confirmed_ts)")))
        warnings = self._warnings(inp, px) + tuple(notes)
        if cands:
            level, rule, sw = max(cands, key=lambda x: d * x[0])
            self.stop = level
            return self.emit(now, TIGHTEN_STOP, rule, obs + ((sw,) if sw else ()), warnings)
        self.emit(now, HOLD, "NO_EXIT_RULE", obs, warnings)

    def _warnings(self, inp: ReviewInputs, px) -> tuple:
        d, w, cfg = self.d, [], self.cfg
        if _u(inp.positioning):
            w.append(f"POSITIONING_UNAVAILABLE: {inp.positioning.reason}")
        elif G._dir(inp.positioning) == -d:
            w.append(f"OPPOSITE_POSITIONING: {inp.positioning} (a positioning hypothesis, not an exit rule)")
        if not _u(inp.vwap) and d * (px - inp.vwap) < 0:
            w.append(f"VWAP_WRONG_SIDE: price {px} vs VWAP {inp.vwap}")
        if inp.classification == "EXHAUSTED" or inp.exhaustion_flags:
            w.append(f"EXHAUSTION: {inp.classification} {','.join(inp.exhaustion_flags)}")
        q = self.quote
        if q is not None and q.bids and q.asks:
            mid = (q.bids[0][0] + q.asks[0][0]) / 2
            pct, lim = (q.asks[0][0] - q.bids[0][0]) / mid * 100, cfg.get("risk.max_spread_pct")["OPT" if self.t.kind in OPTION_KINDS else "FUT"]
            if pct > lim:
                w.append(f"SPREAD_WIDE: {pct:.3f} % > {lim} %")
        if inp.opposite_signals:
            w.append(f"OPPOSITE_SIGNAL: {','.join(inp.opposite_signals)}")
        return tuple(w)


# ---------------------------------------------------------------- driver
def _alerts(decisions: list[Decision]) -> list[Alert]:
    out, prev = [], {}
    for x in decisions:
        p = prev.get(x.trade_id)
        if x.decision != p or x.decision in ALWAYS_ALERT:
            obs = "; ".join(f"{o.field}={o.value} @ {_iso(o.exchange_ts_ns or o.receive_ns)}" for o in x.observations)
            tail = " — DATA_UNAVAILABLE: cannot reassess, nothing inferred, P&L unavailable" if x.decision == DATA_UNAVAILABLE else ""
            out.append(Alert(x.trade_id, x.ledger, x.as_of, x.decision, p, x.rule_id, x.observations,
                             f"[{x.ledger}] {x.decision} ({x.rule_id}) — {obs}{tail}", x.config_version))
        prev[x.trade_id] = x.decision
    return out


def _transition(t: Trade, ts: int, a: str, b: str, cause: str) -> LifecycleRow:
    if b not in G.ALLOWED.get(a, set()):
        raise G.IllegalTransition(f"{t.signal_id}: {a} -> {b} is not allowed")
    return LifecycleRow(t.ledger, t.id, t.signal_id, ts, a, b, cause)


def run_trades(trades: list[Trade], events: Iterable, inputs_at: Callable[[str, int], ReviewInputs], cfg,
               realized: Mapping[str, float] | None = None, until: int | None = None) -> Result:
    """events: Event stream in arrival order. inputs_at(trade_id, ns) -> ReviewInputs (pure lookup).
    realized: {ledger: realized net INR today before these trades}. Timers (reviews, cutoff) fire at their exact due time."""
    mons = [Monitor(t, cfg) for t in trades]
    real = {k: float((realized or {}).get(k, 0.0)) for k in LEDGERS}
    life = [r for t in trades for r in (_transition(t, t.entry_ns, G.ENTRY_ELIGIBLE, G.TRIGGERED, f"{t.ledger} entry fill"),
                                        _transition(t, t.entry_ns, G.TRIGGERED, G.ACTIVE, "position open"))]
    fills, no_fills, pending, done = [], [], {}, set()

    cut_fired: set = set()

    def timers(upto: int) -> None:
        for m in mons:
            while not m.closed:                     # each due time fires once; the loop always advances
                cut = m.cutoff if m.t.id not in cut_fired and m.cutoff >= m.t.entry_ns else None
                due = min(m.next_review, cut) if cut is not None else m.next_review
                if due > upto:
                    break
                if due == cut:
                    cut_fired.add(m.t.id)
                m.clock(due)
                if due == m.next_review and not m.closed:
                    m.review(inputs_at(m.t.id, due), due)

    def settle(m: Monitor, now: int) -> None:
        t = m.t
        if m.closed and t.id not in done:
            done.add(t.id)
            life.append(_transition(t, now, G.ACTIVE, G.EXIT_REQUIRED, m.out[-1].rule_id))
            if t.ledger == SIMULATED:
                pending[t.id] = t.qty
        if pending.get(t.id):
            f = paper_fill("SELL" if t.side == "BUY" else "BUY", pending[t.id], t.lot_size, m.quote, now, cfg)
            if _u(f):
                if not no_fills or no_fills[-1].reason != f.reason or no_fills[-1].trade_id != t.id:
                    no_fills.append(NoFill(t.id, now, "exit", pending[t.id], f.reason))
                return
            fills.append(replace(f, trade_id=t.id))
            pending[t.id] -= f.qty_filled
            real[t.ledger] += m.cd * (f.avg_price - t.entry_price) * f.qty_filled / 100 - round_trip(
                cfg, "OPT" if t.kind in OPTION_KINDS else "FUT", t.side, t.entry_price / 100, f.avg_price / 100,
                f.qty_filled, t.day).total_inr

    for e in events:
        now = e.receive_ns
        timers(now)
        for m in mons:
            if now >= m.t.entry_ns:
                m.on_event(e)
                if m.review_due(now) and m.oi_change is not None:
                    m.review(inputs_at(m.t.id, now), now)
        for led in LEDGERS:                        # daily loss per ledger, never summed across ledgers
            open_ = [m for m in mons if m.t.ledger == led and not m.closed and now >= m.t.entry_ns]
            nets = [m.pnl(now)[1] for m in open_]
            if open_ and not any(map(_u, nets)) and real[led] + sum(nets) <= -cfg.get("risk.max_daily_loss_inr"):
                total = round(real[led] + sum(nets), 2)
                for m in open_:
                    m.emit(now, EXIT_REQUIRED, "DAILY_LOSS_LIMIT", m._quote_obs() + (Obs(
                        "ledger_day_pnl_net", -1, total, None, now, f"derived: {led} realized + unrealized net"),))
        for m in mons:
            settle(m, now)
    if until is not None:
        timers(until)
        for m in mons:
            settle(m, until)
    decisions = sorted((x for m in mons for x in m.out), key=lambda x: (x.as_of, x.trade_id))
    return Result(decisions, _alerts(decisions), fills, no_fills, life, list(trades))

