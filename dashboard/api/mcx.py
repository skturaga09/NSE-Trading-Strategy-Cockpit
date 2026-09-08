#!/usr/bin/env python3
"""Isolated MCX API router. All endpoints return the data-quality envelope and controlled
error/deferred states — never an unhandled exception. Mounted under /api/mcx in api_server."""

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from dashboard import mcx, mcx_expiry, mcx_config
from dashboard import mcx_contract_profiles as profiles

router = APIRouter(prefix="/api/mcx", tags=["mcx"])


def _deferred(phase: str, detail: str) -> Dict[str, Any]:
    """Controlled 'not yet implemented' payload (still carries the envelope)."""
    return {**mcx.envelope(mcx.market_state(), {}), "deferred": phase, "detail": detail, "rows": []}


@router.get("/health")
def health() -> Dict[str, Any]:
    rows = mcx.instruments()
    cfg = mcx_config.get()
    src = {"mcx_master": {"age_seconds": 0 if rows else None,
                          "stale_after": cfg.get("mcx_instrument_master_ttl_seconds", 21600),
                          "ts": None}}
    return {
        **mcx.envelope(mcx.market_state(), src),
        "mcx_enabled": cfg.get("mcx_enabled"),
        "instruments_loaded": len(rows),
        "futures_roots": sorted(mcx.futures_map(rows).keys())[:40],
        "registry": profiles.registry_diagnostics(),
        "auto_actions_disabled": {
            "squareoff": not cfg.get("mcx_auto_squareoff_enabled"),
            "contrary_instruction": not cfg.get("mcx_auto_contrary_instruction_enabled"),
            "roll": not cfg.get("mcx_auto_roll_enabled"),
        },
    }


@router.get("/watchlist")
def watchlist(roots: Optional[str] = None) -> Dict[str, Any]:
    try:
        rlist = [r.strip().upper() for r in roots.split(",")] if roots else None
        return mcx.watchlist(rlist)
    except Exception as e:
        return {**mcx.envelope("UNKNOWN", {}, [f"watchlist error: {e}"]), "rows": []}


@router.get("/contracts/{root}")
def contracts(root: str) -> Dict[str, Any]:
    root = root.upper()
    rows = mcx.instruments()
    futs = mcx.futures_map(rows).get(root, [])
    opts = [o for o in mcx._opts(rows) if o["name"] == root]
    exps = sorted({o["expiry"] for o in opts})
    return {
        **mcx.envelope(mcx.market_state(), {}),
        "root": root, "economic_root": mcx.economic_root(root),
        "futures": [{"symbol": f["tradingsymbol"], "expiry": f["expiry"].isoformat(),
                     "lot_size": f["lot_size"], "tick_size": f["tick_size"], "token": f["token"]} for f in futs],
        "option_expiries": [e.isoformat() for e in exps],
        "profile_verified": profiles.is_verified(mcx.economic_root(root)),
    }


@router.get("/roll-state/{root}")
def roll_state(root: str) -> Dict[str, Any]:
    from dataclasses import asdict
    rows = mcx.instruments()
    fn = mcx.front_next_future(root, rows)
    syms = [f["tradingsymbol"] for f in (fn["front"], fn["next"]) if f]
    q = mcx.quote(syms) if syms else {}
    return {**mcx.envelope(mcx.market_state(), {}), "root": root.upper(),
            "roll": asdict(mcx.roll_state(root, q, rows))}


@router.get("/positions")
def positions() -> Dict[str, Any]:
    """Open MCX OPTION positions with contract link + expiry/devolvement risk."""
    cfg = mcx_config.get()
    try:
        from dashboard.exit_monitor import _positions
        raw = _positions()
    except Exception as e:
        return {**mcx.envelope("UNKNOWN", {}, [f"positions unavailable: {e}"]), "positions": []}
    rows = mcx.instruments()
    by_sym = {o["tradingsymbol"]: o for o in mcx._opts(rows)}
    out: List[Dict[str, Any]] = []
    for p in raw:
        if (p.get("exchange") or "").upper() != "MCX":
            continue
        sym = p.get("tradingsymbol")
        opt = by_sym.get(sym)
        if not opt:      # MCX future position (not an option) or unmapped — surface minimally
            out.append({"option_symbol": sym, "note": "MCX position not an option or not in master"})
            continue
        link = mcx.contract_link(opt, rows)
        qty = p.get("quantity", 0)
        lot = opt["lot_size"] or 1
        lots = int(abs(qty) / lot) if lot else abs(qty)
        fprice = None
        if link.underlying_future_symbol:
            fq = mcx.quote([link.underlying_future_symbol]).get(f"MCX:{link.underlying_future_symbol}") or {}
            fprice = fq.get("last_price")
        a = mcx.atr(link.underlying_future_token) if link.underlying_future_token else None
        pos = {"position_id": sym, "option_symbol": sym, "option_token": opt["token"],
               "option_type": opt["instrument_type"], "side": "LONG" if qty > 0 else "SHORT",
               "quantity_lots": lots, "option_root": opt["name"]}
        risk = mcx_expiry.evaluate(pos, link, future_price=fprice, strike=opt["strike"],
                                   lot_size=lot, atr=a, cfg=cfg)
        from dataclasses import asdict
        out.append({"position": pos, "contract_link": asdict(link), "expiry_risk": mcx_expiry.as_dict(risk)})
    return {**mcx.envelope(mcx.market_state(), {}), "positions": out}


@router.get("/event-risk")
def event_risk() -> Dict[str, Any]:
    """Expiry/devolvement risk on open MCX options is live (C0.5). Macro/EIA event guard is C4."""
    base = positions()
    base["event_calendar"] = {"deferred": "C4", "detail": "timezone-aware macro/EIA event guard not yet implemented"}
    return base


@router.get("/events")
def events() -> Dict[str, Any]:
    return _deferred("C4", "timezone-aware event calendar (EIA/FOMC/CPI/NFP/OPEC) not yet implemented")


@router.get("/context")
def context() -> Dict[str, Any]:
    """Inter-market context (C1b): DXY / USDINR / US10y + per-root global attribution.
    Context-only (delayed, different session). Never blocks MCX monitoring on its own failure."""
    try:
        from dashboard import mcx_context
        return mcx_context.context()
    except Exception as e:
        return {**mcx.envelope(mcx.market_state(), {}, [f"context unavailable: {e}"]),
                "macro": {}, "roots": {}}


@router.get("/context/{root}")
def context_root(root: str) -> Dict[str, Any]:
    try:
        from dashboard import mcx_context
        return mcx_context.context_for_root(root)
    except Exception as e:
        return {**mcx.envelope(mcx.market_state(), {}, [f"context unavailable: {e}"]), "root": root.upper()}


@router.get("/chain/{root}")
def chain(root: str) -> Dict[str, Any]:
    """Basic ATM chain (quotes + liquidity). Black-76 IV/probability analytics land in C3."""
    root = root.upper()
    rows = mcx.instruments()
    fn = mcx.front_next_future(root, rows)
    front = fn["front"]
    if not front:
        return {**mcx.envelope("UNKNOWN", {}, [f"no future for {root}"]), "root": root, "rows": []}
    fq = mcx.quote([front["tradingsymbol"]]).get(f"MCX:{front['tradingsymbol']}") or {}
    fprice = fq.get("last_price")
    opts = [o for o in mcx._opts(rows) if o["name"] == root and o["expiry"] and o["expiry"] >= date.today()]
    out_rows = []
    if opts and fprice:
        exp0 = min(o["expiry"] for o in opts)
        strikes = sorted({o["strike"] for o in opts if o["expiry"] == exp0 and o["strike"]})
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - fprice)) if strikes else 0
        window = strikes[max(0, atm_i - 3): atm_i + 4]
        mx = mcx_config.get().get("mcx_max_option_spread_pct", {}).get(root, 8.0)
        for k in window:
            leg = {}
            for typ in ("CE", "PE"):
                o = next((x for x in opts if x["expiry"] == exp0 and x["strike"] == k and x["instrument_type"] == typ), None)
                if not o:
                    continue
                oq = mcx.quote([o["tradingsymbol"]]).get(f"MCX:{o['tradingsymbol']}") or {}
                depth = oq.get("depth") or {}
                bid = (depth.get("buy") or [{}])[0].get("price")
                ask = (depth.get("sell") or [{}])[0].get("price")
                leg[typ] = {"symbol": o["tradingsymbol"], "ltp": oq.get("last_price"), "bid": bid, "ask": ask,
                            "oi": oq.get("oi"), "volume": oq.get("volume"),
                            "liquidity": mcx.liquidity_grade(bid, ask, oq.get("last_price"), oi=oq.get("oi"),
                                                             volume=oq.get("volume"), max_spread_pct=mx)}
            out_rows.append({"strike": k, "atm": k == strikes[atm_i], **leg})
        out_env_exp = exp0.isoformat()
    else:
        out_env_exp = None
    return {**mcx.envelope(mcx.market_state(), {}), "root": root, "future": front["tradingsymbol"],
            "future_price": fprice, "option_expiry": out_env_exp, "rows": out_rows,
            "analytics_deferred": "C3 (Black-76 IV bands, expected move, probability)"}


@router.get("/position-probability")
def position_probability() -> Dict[str, Any]:
    return _deferred("C3", "Black-76 option probability for MCX positions not yet implemented")
