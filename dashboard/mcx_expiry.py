#!/usr/bin/env python3
"""
MCX expiry / devolvement-risk engine (C0.5). MCX options are options ON FUTURES — an ITM
option at expiry can DEVOLVE into a futures position at the strike, turning a small-premium
option into a large futures/tender exposure. This engine treats expiry as an OPERATIONAL RISK
EVENT, not just a theta/P&L event.

It ONLY produces alerts / review states. It NEVER auto-squares-off, sends contrary
instructions, rolls, or hedges. When settlement mode or broker cutoff is unknown/unverified,
it deliberately escalates to HIGH/UNKNOWN and requires manual review (safe degradation).
"""

from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from dashboard import mcx_contract_profiles as profiles


@dataclass
class McxExpiryRisk:
    position_id: str
    option_symbol: str
    option_token: Optional[int]
    option_type: Literal["CE", "PE"]
    side: Literal["LONG", "SHORT"]
    quantity_lots: int
    option_expiry: Optional[str]
    linked_future_symbol: Optional[str]
    linked_future_token: Optional[int]
    linked_future_expiry: Optional[str]
    settlement_mode: Literal["futures_devolvement", "cash_settlement", "unknown"]
    itm_state: Literal["ITM", "ATM", "OTM", "UNKNOWN"]
    estimated_intrinsic_value_per_lot: Optional[float]
    estimated_devolved_future_side: Literal["LONG", "SHORT", "NONE", "UNKNOWN"]
    estimated_devolved_future_lots: Optional[int]
    estimated_devolved_future_notional: Optional[float]
    estimated_margin_requirement: Optional[float]
    contrary_instruction_supported: Optional[bool]
    contrary_instruction_deadline: Optional[str]
    broker_cutoff_deadline: Optional[str]
    expiry_risk_state: Literal["NONE", "WATCH", "HIGH", "CRITICAL", "UNKNOWN"]
    action_required_by: Optional[str]
    warnings: List[str]


def _itm_state(opt_type: str, strike: float, future_price: Optional[float],
               atr: Optional[float], buffer_frac: float) -> str:
    if future_price is None or strike is None:
        return "UNKNOWN"
    buf = (atr or 0) * buffer_frac
    if opt_type == "CE":
        if future_price > strike + buf:
            return "ITM"
        if future_price < strike - buf:
            return "OTM"
        return "ATM"
    else:  # PE
        if future_price < strike - buf:
            return "ITM"
        if future_price > strike + buf:
            return "OTM"
        return "ATM"


def _devolved_side(opt_type: str, side: str, itm: str) -> str:
    """Futures exposure created if the option is exercised/assigned ITM at expiry.
    LONG CE→LONG fut, LONG PE→SHORT fut; SHORT CE→SHORT fut (assigned), SHORT PE→LONG fut."""
    if itm != "ITM":
        return "NONE"
    if opt_type == "CE":
        return "LONG" if side == "LONG" else "SHORT"
    return "SHORT" if side == "LONG" else "LONG"


def evaluate(position: Dict[str, Any], link, *, future_price: Optional[float],
             strike: Optional[float], lot_size: Optional[int], atr: Optional[float],
             cfg: Dict[str, Any], today: Optional[date] = None,
             acknowledged: bool = False) -> McxExpiryRisk:
    """position: {position_id, option_symbol, option_token, option_type CE|PE, side LONG|SHORT,
    quantity_lots}. link: McxContractLink (for linked future + economic root)."""
    today = today or date.today()
    warnings: List[str] = []
    econ = getattr(link, "economic_root", None) or (position.get("option_root") or "").upper()
    opt_type = position.get("option_type")
    side = position.get("side", "LONG")
    lots = int(position.get("quantity_lots") or 0)

    smode = profiles.settlement_mode(econ)          # 'unknown' unless a VERIFIED profile says otherwise
    prof = profiles.profile_for(econ)
    if not prof:
        warnings.append(f"no contract profile for {econ} — settlement semantics unknown")
    elif prof.get("verified") is not True:
        warnings.append(f"{econ} profile is UNVERIFIED — treat settlement/tender as unknown until verified")
    if not profiles.broker_cutoff_known():
        warnings.append("broker contrary-instruction / square-off cutoff is UNKNOWN — verify with your broker")

    opt_exp = None
    dte = None
    if link and getattr(link, "option_expiry", None):
        try:
            opt_exp = date.fromisoformat(link.option_expiry)
            dte = (opt_exp - today).days
        except Exception:
            pass

    buffer_frac = float(cfg.get("mcx_expiry_itm_buffer_atr_fraction", 0.15))
    itm = _itm_state(opt_type, strike, future_price, atr, buffer_frac)
    dev_side = _devolved_side(opt_type, side, itm) if smode == "futures_devolvement" else \
        ("UNKNOWN" if smode == "unknown" else "NONE")
    intrinsic = None
    if strike is not None and future_price is not None:
        intrinsic_pts = max(0.0, (future_price - strike) if opt_type == "CE" else (strike - future_price))
        intrinsic = round(intrinsic_pts * (lot_size or 0), 2) if lot_size else None
    notional = round(future_price * (lot_size or 0) * lots, 2) if (future_price and lot_size) else None

    # Risk state
    warn_dte = int(cfg.get("mcx_expiry_warning_dte_days", 5))
    crit_dte = int(cfg.get("mcx_expiry_critical_dte_days", 1))
    if smode == "unknown":
        state = "UNKNOWN"           # can't reason about settlement → force manual review
        warnings.append("settlement mode unknown → cannot assess devolvement; manual review required")
    elif dte is None:
        state = "UNKNOWN"
    elif dte < 0:
        state = "CRITICAL"; warnings.append("option expiry has passed — verify settlement outcome immediately")
    elif dte <= crit_dte and itm in ("ITM", "ATM"):
        state = "HIGH" if acknowledged else "CRITICAL"
    elif dte <= crit_dte:
        state = "HIGH"
    elif dte <= warn_dte:
        state = "WATCH"
    else:
        state = "NONE"
    if smode == "futures_devolvement" and itm == "ITM" and state in ("WATCH", "NONE"):
        state = "WATCH"  # devolvement-capable + ITM never below WATCH even if DTE is comfortable
        warnings.append("ITM and devolvement-capable — a futures position may be created at expiry")

    action_by = opt_exp.isoformat() if opt_exp else None
    return McxExpiryRisk(
        position_id=str(position.get("position_id") or position.get("option_symbol")),
        option_symbol=position.get("option_symbol"), option_token=position.get("option_token"),
        option_type=opt_type, side=side, quantity_lots=lots,
        option_expiry=link.option_expiry if link else None,
        linked_future_symbol=getattr(link, "underlying_future_symbol", None),
        linked_future_token=getattr(link, "underlying_future_token", None),
        linked_future_expiry=getattr(link, "underlying_future_expiry", None),
        settlement_mode=smode, itm_state=itm,
        estimated_intrinsic_value_per_lot=intrinsic,
        estimated_devolved_future_side=dev_side,
        estimated_devolved_future_lots=lots if dev_side in ("LONG", "SHORT") else (0 if dev_side == "NONE" else None),
        estimated_devolved_future_notional=notional if dev_side in ("LONG", "SHORT") else None,
        estimated_margin_requirement=None,   # needs broker margin policy (unknown) — left None by design
        contrary_instruction_supported=(prof or {}).get("contrary_instruction_supported"),
        contrary_instruction_deadline=None,
        broker_cutoff_deadline=None,
        expiry_risk_state=state, action_required_by=action_by, warnings=warnings,
    )


def as_dict(risk: McxExpiryRisk) -> Dict[str, Any]:
    return asdict(risk)
