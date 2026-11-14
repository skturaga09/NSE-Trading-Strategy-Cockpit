"""Phase 7 centralized risk engine (pure, server-side). Advisory and paper-trading only: nothing here places orders.

`risk_check(candidate, portfolio, cfg) -> RiskDecision` is the single entry point. Every check has a name and returns a
reason; the decision records the config version. Time is the candidate's `as_of` (never the wall clock).

Risk measures:
- long options: planned_risk = (entry - premium at stop) x qty + costs (sizes the position);
  full_premium_at_risk = entry x qty + costs is also reported, because stop execution is not guaranteed.
  The capital check uses the full premium.
- futures: planned_risk = |entry - stop| x qty + costs; gap_risk = planned_risk + risk.gap_risk_atr_multiple x ATR x qty.

Enforcement: a `Recommendation` can only be built with an `ApprovalToken` for that candidate, and only `risk_check`
can create a token (and only for an APPROVED decision).
"""

from dataclasses import dataclass
from datetime import date, datetime

from .candles import IST, MIN, S, _ns
from .contracts import ELIGIBLE, OPTION_KINDS, Candidate, limit_reasons

APPROVED, REJECTED = "APPROVED", "REJECTED"
_MINT = object()   # module-private: only risk_check passes it


@dataclass(frozen=True)
class PortfolioState:
    as_of: int                      # ns; the state the caller holds at the decision time
    day: date
    realized_pnl_inr: float
    unrealized_pnl_inr: float
    worst_day_pnl_inr: float        # lowest realized + unrealized seen so far today (caller-tracked): a breach latches
    open_underlyings: tuple         # one entry per open position
    capital_in_use_inr: float
    trades_today: int
    consecutive_losses: int
    last_loss_ns: int | None


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


class ApprovalToken:
    """Proof that risk_check approved `candidate_id` under `config_version` at `as_of`. Not constructible elsewhere."""
    __slots__ = ("candidate_id", "config_version", "as_of")

    def __init__(self, mint, candidate_id: str, config_version: str, as_of: int):
        if mint is not _MINT:
            raise PermissionError("an ApprovalToken can only be created by engine.risk.risk_check")
        for k, v in (("candidate_id", candidate_id), ("config_version", config_version), ("as_of", as_of)):
            object.__setattr__(self, k, v)

    def __setattr__(self, *_):
        raise AttributeError("ApprovalToken is immutable")


@dataclass(frozen=True)
class RiskDecision:
    candidate_id: str
    status: str                     # APPROVED | REJECTED
    reasons: tuple                  # failed checks, named
    checks: tuple                   # every Check run
    planned_risk_inr: float | None
    full_premium_at_risk_inr: float | None
    gap_risk_inr: float | None
    as_of: int
    config_version: str
    token: ApprovalToken | None     # only when APPROVED


@dataclass(frozen=True)
class Recommendation:
    candidate: Candidate
    approval: ApprovalToken

    def __post_init__(self):
        if not isinstance(self.approval, ApprovalToken):
            raise PermissionError("a Recommendation needs an ApprovalToken from risk_check")
        if self.approval.candidate_id != self.candidate.id or self.approval.as_of != self.candidate.as_of \
                or self.approval.config_version != self.candidate.config_version:
            raise PermissionError(f"the ApprovalToken is for {self.approval.candidate_id}, not {self.candidate.id}")


def risk_check(c: Candidate, p: PortfolioState, cfg) -> RiskDecision:
    R = lambda k: cfg.get("risk." + k)  # noqa: E731
    cls = "OPT" if c.kind in OPTION_KINDS else "FUT"
    day_pnl = p.realized_pnl_inr + p.unrealized_pnl_inr
    worst = min(day_pnl, p.worst_day_pnl_inr)
    limits = limit_reasons(c, cfg)
    cap_left = R("capital_inr") * (1 - R("capital_reserve_pct") / 100) - p.capital_in_use_inr
    cap = c.full_premium_at_risk_inr if c.kind in OPTION_KINDS else c.required_capital_inr   # options: full premium
    cday = datetime.fromtimestamp(c.as_of / S, IST).date()
    cooling = (p.consecutive_losses >= R("max_consecutive_losses")
               and (p.last_loss_ns is None or c.as_of < p.last_loss_ns + R("cooldown_min") * MIN))
    costs_ok = c.costs_at_stop is not None and "UNVERIFIED" not in (c.costs_at_stop.status, c.costs_at_target.status)
    checks = [
        Check("CANDIDATE_ELIGIBLE", c.status == ELIGIBLE, f"{c.status}: {'; '.join(c.reasons) or 'ok'}"),
        Check("CONFIG_VERSION", c.config_version == cfg.version, f"candidate {c.config_version}, risk {cfg.version}"),
        Check("PORTFOLIO_STATE", p.day == cday and p.as_of <= c.as_of,
              f"portfolio state for {p.day} as of {p.as_of}; decision {cday} at {c.as_of}"),
        Check("CAPITAL_ABOVE_LIMIT", cap is not None and not any(r.startswith("CAPITAL_ABOVE_LIMIT") for r in limits),
              f"capital {cap} INR ({c.capital_method}{', full premium + costs' if c.kind in OPTION_KINDS else ''})"),
        Check("CAPITAL_RESERVE", cap is not None and cap <= cap_left,
              f"capital {cap} vs {cap_left:,.0f} INR left above the {R('capital_reserve_pct')} % reserve"),
        Check("MAX_RISK_PER_TRADE", c.planned_risk_inr is not None and c.planned_risk_inr <= R("max_risk_per_trade_inr"),
              f"planned risk {c.planned_risk_inr} vs {R('max_risk_per_trade_inr')} INR"),
        Check("DAILY_LOSS_LIMIT", worst > -R("max_daily_loss_inr"),
              f"day P&L {day_pnl:,.0f}, worst today {worst:,.0f} vs -{R('max_daily_loss_inr'):,} INR"),
        Check("MAX_OPEN_POSITIONS", len(p.open_underlyings) < R("max_open_positions"),
              f"{len(p.open_underlyings)} open vs {R('max_open_positions')}"),
        Check("MAX_DAILY_TRADES", p.trades_today < R("max_daily_trades"), f"{p.trades_today} today vs {R('max_daily_trades')}"),
        Check("CONSECUTIVE_LOSSES_COOLDOWN", not cooling,
              f"{p.consecutive_losses} consecutive losses (max {R('max_consecutive_losses')}, cooldown {R('cooldown_min')} min)"),
        Check("SPREAD_TOO_WIDE", c.spread_pct is not None and not any(r.startswith("SPREAD_") for r in limits),
              f"spread {c.spread_pct} %, {c.spread_vs_move_pct} % of the move to T1"),
        Check("MIN_NET_RR", c.rr_net is not None and c.rr_net >= R("min_rr_net"), f"net R:R {c.rr_net} vs {R('min_rr_net')}"),
        Check("NET_RR_VERIFIED", costs_ok, "cost estimate VERIFIED" if costs_ok else "cost estimate UNVERIFIED or missing"),
        Check("MAX_SLIPPAGE", c.slippage_pct is not None and c.slippage_pct <= R("max_slippage_pct")[cls],
              f"entry slippage {c.slippage_pct} % vs {R('max_slippage_pct')[cls]} %"),
        Check("MIN_LIQUIDITY", not any(r.startswith("ILLIQUID") for r in limits), "; ".join(
            r for r in limits if r.startswith("ILLIQUID")) or "volume, OI and visible depth above the minimums"),
        Check("EXPIRY_DAY", not (R("block_expiry_day") and c.expiry == cday), f"contract expiry {c.expiry}"),
        Check("EVENT_DAY", cday not in R("event_days"), f"{cday} {'is' if cday in R('event_days') else 'is not'} in risk.event_days"),
        Check("INTRADAY_CUTOFF", c.as_of < _ns(cday, R("intraday_cutoff")), f"decision time vs cutoff {R('intraday_cutoff')} IST"),
        Check("SINGLE_POSITION_PER_UNDERLYING",
              not (R("single_position_per_underlying") and c.underlying in p.open_underlyings),
              f"{c.underlying} {'already open' if c.underlying in p.open_underlyings else 'not open'}"),
    ]
    reasons = tuple(f"{k.name}: {k.detail}" for k in checks if not k.passed)
    status = REJECTED if reasons else APPROVED
    return RiskDecision(c.id, status, reasons, tuple(checks), c.planned_risk_inr, c.full_premium_at_risk_inr,
                        c.gap_risk_inr, c.as_of, cfg.version,
                        ApprovalToken(_MINT, c.id, c.config_version, c.as_of) if status == APPROVED else None)
