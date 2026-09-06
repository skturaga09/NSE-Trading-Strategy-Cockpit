#!/usr/bin/env python3
"""
Position probability push — a live, sample-free statistical read on your OPEN option
positions, delivered to your phone.

For each open option in the Exits book it joins the live option chain (real Kite spot +
ATM/leg IV) and computes, purely mechanically:
  - expected move by expiry: ±1SD = spot × IV × √(T)
  - probability the position is PROFITABLE held to expiry: P(underlying beyond breakeven)
  - probability it merely finishes in-the-money: P(underlying beyond strike)
Breakeven = strike + premium (calls) / strike − premium (puts). Probabilities use the
standard lognormal model with the risk-free drift already baked into option_chain._bs
(risk-neutral d2), so they line up with the chain's own IV. Measured, NOT advice.

Isolated + read-only: no orders, reuses the same helpers the Intraday tab already uses.
Market-hours only (bails cheaply when closed, so a weekday-morning launchd tick is safe).
"""

import json
import math
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from dashboard import app as core
from dashboard import option_chain as oc
from dashboard import exit_monitor

# ADANIGREEN26SEP1300CE -> underlying / strike / CE|PE (monthly stock-option format).
_SYM = re.compile(r"^(?P<u>[A-Z&]+?)(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<strike>\d+)(?P<t>CE|PE)$")


def _ist_today() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).date()
    except Exception:
        return date.today()


def _d2(S: float, K: float, T: float, sigma: float) -> Optional[float]:
    """d2 with ZERO drift = [ln(S/K) − ½σ²T] / (σ√T). This is a probability-of-profit
    read, not option pricing, so we deliberately drop the risk-free drift that
    option_chain._bs carries — the neutral, more conservative convention (and it keeps
    these odds consistent with a hand ±1SD calc). Add oc.RATE*T to the numerator if you
    ever want the risk-neutral version instead."""
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None
    return (math.log(S / K) - 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))


def _leg_iv(chain: Dict[str, Any], sym: str, strike: int, is_call: bool) -> Optional[float]:
    """IV for this exact leg from the chain if it's in the ±3 window; else fall back to the
    ATM leg's IV (same expiry) so a far strike still gets a sane vol."""
    atm_iv = None
    for row in chain.get("rows", []):
        leg = row.get("call") if is_call else row.get("put")
        if leg and leg.get("symbol") == sym and leg.get("iv"):
            return leg["iv"]
        if row.get("atm"):
            side = row.get("call") if is_call else row.get("put")
            if side and side.get("iv"):
                atm_iv = side["iv"]
    return atm_iv


def analyze() -> Dict[str, Any]:
    sess = core.ZerodhaPlumbingInspector.market_session()
    if not sess.get("is_open"):
        return {"skipped": "market closed", "session": sess.get("session"), "positions": []}

    ev = exit_monitor.evaluate()
    today = _ist_today()
    chains: Dict[str, Dict[str, Any]] = {}   # underlying -> chain (fetched once each)
    out: List[Dict[str, Any]] = []

    for p in ev.get("positions", []):
        if not p.get("is_option"):
            continue
        sym = p["symbol"]
        m = _SYM.match(sym)
        if not m:
            continue
        underlying = m.group("u")
        strike = int(m.group("strike"))
        is_call = m.group("t") == "CE"
        entry = p.get("entry")
        if not entry:
            continue

        chain = chains.get(underlying)
        if chain is None:
            try:
                chain = oc.chain(underlying)
            except Exception as e:
                chain = {"error": str(e)}
            chains[underlying] = chain
        spot, expiry = chain.get("spot"), chain.get("expiry")
        if not spot or not expiry:
            continue

        try:
            T = max((datetime.strptime(expiry, "%Y-%m-%d").date() - today).days, 0) / 365.0
        except Exception:
            continue
        iv = _leg_iv(chain, sym, strike, is_call)
        if not iv or T <= 0:
            continue
        sigma = iv / 100.0

        breakeven = strike + entry if is_call else strike - entry
        one_sd = spot * sigma * math.sqrt(T)
        d2_be = _d2(spot, breakeven, T, sigma) if breakeven > 0 else None
        d2_k = _d2(spot, strike, T, sigma)
        # profit if underlying ends beyond breakeven in the option's direction; ITM if beyond strike
        p_profit = (oc._ncdf(d2_be) if is_call else oc._ncdf(-d2_be)) if d2_be is not None else (1.0 if is_call else 0.0)
        p_itm = (oc._ncdf(d2_k) if is_call else oc._ncdf(-d2_k)) if d2_k is not None else None

        out.append({
            "symbol": sym, "underlying": underlying, "strike": strike,
            "side": "CALL" if is_call else "PUT", "entry": round(entry, 2), "ltp": p.get("ltp"),
            "spot": spot, "iv_pct": round(iv, 1), "days": round(T * 365),
            "expiry": expiry, "one_sd": round(one_sd, 1),
            "band_low": round(spot - one_sd, 1), "band_high": round(spot + one_sd, 1),
            "breakeven": round(breakeven, 2),
            "p_profit_pct": round(p_profit * 100, 1),
            "p_itm_pct": round(p_itm * 100, 1) if p_itm is not None else None,
            "signal": p.get("signal"), "reason": p.get("reason"),
        })

    return {"timestamp": ev.get("timestamp"), "session": sess.get("session"), "positions": out}


def push() -> Dict[str, Any]:
    """One combined phone card covering every open option position. Sample-free but honest:
    it's a lognormal probability from live IV, not a promise — theta and gaps are real."""
    r = analyze()
    ps = r.get("positions", [])
    if r.get("skipped"):
        return {"skipped": r["skipped"], "alerts": 0}
    if not ps:
        return {"alerts": 0, "note": "no open option positions"}
    lines: List[str] = []
    for x in ps:
        arrow = "▲" if x["side"] == "CALL" else "▼"
        lines.append(
            f"{arrow} {x['underlying']} {x['strike']}{'CE' if x['side']=='CALL' else 'PE'} "
            f"· {x['days']}d · IV {x['iv_pct']}%\n"
            f"  spot {x['spot']} · ±1SD ₹{x['one_sd']:.0f} ({x['band_low']:.0f}–{x['band_high']:.0f})\n"
            f"  BE {x['breakeven']} · P(profit@exp) {x['p_profit_pct']}% · P(ITM) {x['p_itm_pct']}%\n"
            f"  entry {x['entry']} · now {x['ltp']} · {x['signal']}"
        )
    body = "\n".join(lines) + "\n— lognormal from live IV. Measured, not advice."
    return exit_monitor.notify(f"📐 Position odds · {len(ps)} open", body, tags=["triangular_ruler"], priority=3)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "push":
        print(json.dumps(push()))
    else:
        print(json.dumps(analyze(), indent=2, default=str))
