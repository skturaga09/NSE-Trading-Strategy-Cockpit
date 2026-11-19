#!/usr/bin/env python3
"""
Target-premium → required-stock-price calculator for open option positions.

Uses as much LIVE market data as possible and models only what the market can't
give directly:
  - live SPOT and live OPTION premium (bid/ask mid) from Kite /quote,
  - your actual TARGET pulled from your pending SELL orders / GTTs (Kite /orders,
    /gtt) — not a number we made up,
  - implied vol CALIBRATED to the live premium (so the model matches the real
    market price), then Black-Scholes solved for the spot at which the option
    would be worth the target.

Delta (the option's sensitivity) is also returned for a quick linear read. The
required-spot assumes the move happens soon — time decay/IV shifts mean a slower
move needs the stock a bit higher.
"""

import math
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests

from dashboard import app as core
from dashboard.option_chain import _headers, _connected, _instruments

RATE = 0.065
_UND_RE = re.compile(r"^([A-Z&-]+?)\d{2}[A-Z]{3}(\d+)(CE|PE)$")


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs(S: float, K: float, T: float, vol: float, is_call: bool) -> float:
    if T <= 0 or vol <= 0 or S <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    d1 = (math.log(S / K) + (RATE + 0.5 * vol * vol) * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    return S * _ncdf(d1) - K * math.exp(-RATE * T) * _ncdf(d2) if is_call else \
        K * math.exp(-RATE * T) * _ncdf(-d2) - S * _ncdf(-d1)


def _delta(S: float, K: float, T: float, vol: float, is_call: bool) -> float:
    if T <= 0 or vol <= 0 or S <= 0:
        return (1.0 if S > K else 0.0) if is_call else (-1.0 if S < K else 0.0)
    d1 = (math.log(S / K) + (RATE + 0.5 * vol * vol) * T) / (vol * math.sqrt(T))
    return _ncdf(d1) if is_call else _ncdf(d1) - 1.0


def _implied_vol(price: float, S: float, K: float, T: float, is_call: bool) -> Optional[float]:
    if not price or price <= 0 or T <= 0:
        return None
    lo, hi, v = 0.01, 5.0, 0.3
    for _ in range(60):
        v = (lo + hi) / 2
        if _bs(S, K, T, v, is_call) > price:
            hi = v
        else:
            lo = v
    return v


def _solve_spot(target: float, S0: float, K: float, T: float, vol: float, is_call: bool) -> Optional[float]:
    """Spot at which the option is worth `target`, at the calibrated vol."""
    if not target or target <= 0 or not vol:
        return None
    lo, hi = S0 * 0.2, S0 * 3.0
    S = S0
    for _ in range(90):
        S = (lo + hi) / 2
        val = _bs(S, K, T, vol, is_call)
        if (val < target) == is_call:
            lo = S
        else:
            hi = S
    return S


def _pending_targets() -> Dict[str, float]:
    """Map option tradingsymbol → target SELL price from pending orders + GTTs."""
    out: Dict[str, float] = {}
    try:
        j = requests.get("https://api.kite.trade/orders", headers=_headers(), timeout=10).json()
        # Any SELL order that isn't terminal (covers OPEN, TRIGGER PENDING, AMO
        # REQ RECEIVED, etc.). Latest such order per symbol wins.
        DONE = {"COMPLETE", "CANCELLED", "REJECTED"}
        for o in (j.get("data", []) if j.get("status") == "success" else []):
            if o.get("transaction_type") == "SELL" and o.get("status") not in DONE and o.get("price"):
                out[o["tradingsymbol"]] = float(o["price"])
    except Exception:
        pass
    try:
        g = requests.get("https://api.kite.trade/gtt", headers=_headers(), timeout=10).json()
        for t in (g.get("data", []) if g.get("status") == "success" else []):
            if t.get("status") != "active":
                continue
            cond = t.get("condition", {}) or {}
            sym = cond.get("tradingsymbol")
            orders = t.get("orders", []) or []
            trig = cond.get("trigger_values") or []
            if sym and orders and orders[0].get("transaction_type") == "SELL" and trig:
                out.setdefault(sym, float(trig[0]))
    except Exception:
        pass
    return out


def compute() -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"timestamp": ts, "is_live": False, "source": "unavailable", "positions": []}
    if not _connected():
        out["source"] = "Kite not connected"
        return out
    try:
        pj = requests.get("https://api.kite.trade/portfolio/positions", headers=_headers(), timeout=10).json()
        net = pj.get("data", {}).get("net", []) if pj.get("status") == "success" else []
        opts = [p for p in net if p.get("quantity") and (p["tradingsymbol"].endswith("CE") or p["tradingsymbol"].endswith("PE"))]
        if not opts:
            out.update({"is_live": True, "source": "Zerodha Kite live", "positions": []})
            return out

        # expiry lookup
        exp_by_sym = {r["tradingsymbol"]: r.get("expiry") for r in _instruments()}
        targets = _pending_targets()

        # batch quote: underlyings + options
        insts = set()
        parsed: Dict[str, Any] = {}
        for p in opts:
            sym = p["tradingsymbol"]
            m = _UND_RE.match(sym)
            if not m:
                continue
            und, K, typ = m.group(1), float(m.group(2)), m.group(3)
            parsed[sym] = {"und": und, "K": K, "is_call": typ == "CE"}
            insts.add(f"NSE:{und}")
            insts.add(f"NFO:{sym}")
        q = requests.get("https://api.kite.trade/quote", params=[("i", s) for s in insts],
                         headers=_headers(), timeout=10).json().get("data", {})

        rows: List[Dict[str, Any]] = []
        for p in opts:
            sym = p["tradingsymbol"]
            pr = parsed.get(sym)
            if not pr:
                continue
            und, K, is_call = pr["und"], pr["K"], pr["is_call"]
            spot = (q.get(f"NSE:{und}", {}) or {}).get("last_price")
            oq = q.get(f"NFO:{sym}", {}) or {}
            ltp = oq.get("last_price")
            depth = oq.get("depth", {}) or {}
            bid = (depth.get("buy") or [{}])[0].get("price")
            ask = (depth.get("sell") or [{}])[0].get("price")
            mid = (bid + ask) / 2 if (bid and ask) else ltp
            exp = exp_by_sym.get(sym)
            T = max((datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days, 1) / 365 if exp else 20 / 365
            if not spot or not mid:
                continue
            iv = _implied_vol(mid, spot, K, T, is_call)
            dlt = _delta(spot, K, T, iv, is_call) if iv else None
            tgt = targets.get(sym)
            req_spot = _solve_spot(tgt, spot, K, T, iv, is_call) if (tgt and iv) else None
            rows.append({
                "symbol": sym, "underlying": und, "strike": K,
                "direction": "CALL" if is_call else "PUT",
                "spot": round(spot, 2), "premium": round(mid, 2),
                "ltp": ltp, "bid": bid, "ask": ask,
                "iv_pct": round(iv * 100, 1) if iv else None,
                "delta": round(dlt, 3) if dlt is not None else None,
                "days": round(T * 365),
                "target": tgt,
                "required_spot": round(req_spot, 1) if req_spot else None,
                "pct_move": round((req_spot / spot - 1) * 100, 2) if req_spot else None,
            })
        out.update({"is_live": True, "source": "Zerodha Kite live (/quote + your orders)", "positions": rows})
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(compute(), indent=2, default=str))


def estimate(spot: float, target: float, K: float, T: float, premium: float, is_call: bool, lot: int,
             stop_line: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Premium if the stock moves to `target` soon, at the volatility implied by today's live premium; plus, when a
    stop line is given, the premium there and the reward : risk in rupees per lot. None if no volatility fits the price."""
    iv = _implied_vol(premium, spot, K, T, is_call)
    if iv is None:
        return None
    at_target = _bs(target, K, T, iv, is_call)
    out = {"iv_pct": round(iv * 100, 1), "delta": round(_delta(spot, K, T, iv, is_call), 2),
           "est_premium": round(at_target, 2), "gain_per_lot": round((at_target - premium) * lot),
           "at_expiry": round(max(0.0, (target - K) if is_call else (K - target)), 2)}
    if stop_line:
        at_stop = _bs(stop_line, K, T, iv, is_call)
        loss = (premium - at_stop) * lot
        out.update({"premium_at_stop": round(at_stop, 2), "loss_per_lot": round(loss),
                    "reward_risk": round(out["gain_per_lot"] / loss, 1) if loss > 0 else None})
    return out


def position_figures(premium: float, est: Dict[str, Any], qty: int, avg: float) -> Dict[str, Any]:
    """Your own P&L in rupees (qty as Kite reports it, so a short position works too): now, at the target, at the stop."""
    out = {"pnl_now": round((premium - avg) * qty), "pnl_at_target": round((est["est_premium"] - avg) * qty)}
    if "premium_at_stop" in est:
        out["pnl_at_stop"] = round((est["premium_at_stop"] - avg) * qty)
    return out


def _quote(key: str) -> Dict[str, Any]:
    return (requests.get("https://api.kite.trade/quote", params=[("i", key)], headers=_headers(), timeout=10).json()
            .get("data") or {}).get(key) or {}


def forward(symbol: str, target: float) -> Dict[str, Any]:
    """Stock target -> option premium, live Kite prices. Which option (owner 2026-11-14: "show MY option"):
    an option name typed in -> that option; a stock you hold an option on -> your option, with your buy price and qty;
    otherwise the one the Supertrend rules would buy for that direction (1 strike in the money, nearest expiry).
    Stop line from the last Supertrend scan when the option is on the side of the 5-minute trend."""
    from dashboard.fno_scanner import fno_universe
    from dashboard.option_chain import INDEX_SYM
    from dashboard.supertrend import board
    from dashboard.supertrend_trades import pick_option
    symbol = symbol.strip().upper()
    if not target or target <= 0:
        return {"error": "enter a target price above 0"}
    nfo = _instruments()
    by_ts = {r["tradingsymbol"]: r for r in nfo if r.get("instrument_type") in ("CE", "PE")}
    opt = by_ts.get(symbol)
    und = opt["name"] if opt else symbol
    if und not in fno_universe() and und not in INDEX_SYM:
        return {"error": f"{symbol} is not an F&O stock, index or option"}
    if not _connected():
        return {"error": "Kite not connected: connect on System Check"}
    spot_key = INDEX_SYM.get(und, f"NSE:{und}")
    spot = _quote(spot_key).get("last_price")
    if not spot:
        return {"error": f"no live price for {und}"}
    pj = requests.get("https://api.kite.trade/portfolio/positions", headers=_headers(), timeout=10).json()
    held = [p for p in ((pj.get("data") or {}).get("net") or []) if p.get("quantity")
            and p.get("tradingsymbol") in by_ts and by_ts[p["tradingsymbol"]]["name"] == und]
    if opt is None and held:
        opt = by_ts[held[0]["tradingsymbol"]]
    if opt is None:
        opt = pick_option(nfo, und, "CE" if target > spot else "PE", spot, date.today().isoformat())
        if opt is None:
            return {"error": f"no 1-strike-in-the-money option listed for {und}"}
    pos = next((p for p in held if p["tradingsymbol"] == opt["tradingsymbol"]), None)
    oq = _quote(f"NFO:{opt['tradingsymbol']}")
    depth = oq.get("depth") or {}
    bid, ask = ((depth.get(x) or [{}])[0].get("price") for x in ("buy", "sell"))
    premium = (bid + ask) / 2 if bid and ask else oq.get("last_price")
    if not premium:
        return {"error": f"no live price for {opt['tradingsymbol']}"}
    is_call = opt["instrument_type"] == "CE"
    K, lot = float(opt["strike"]), int(opt["lot_size"])
    T = max((date.fromisoformat(str(opt["expiry"])) - date.today()).days, 1) / 365
    row = next((r for r in board().get("rows", []) if r["symbol"] == und), None)
    with_trend = row is not None and row["trend"] == ("UP" if is_call else "DOWN")
    est = estimate(spot, target, K, T, premium, is_call, lot, row["line"] if with_trend else None)
    if est is None:
        return {"error": f"could not fit a volatility to the live premium ₹{premium}"}
    out = {"symbol": und, "spot": spot, "target": target, "move_pct": round((target / spot - 1) * 100, 2),
           "option": opt["tradingsymbol"], "which": "yours" if pos else "typed" if symbol == opt["tradingsymbol"] else "rules",
           "kind": opt["instrument_type"], "strike": K, "expiry": str(opt["expiry"]), "days": round(T * 365), "lot": lot,
           "premium": round(premium, 2), "bid": bid or None, "ask": ask or None,
           "quote_at": str(oq.get("last_trade_time") or oq.get("timestamp") or ""),
           "trend": row["trend"] if row else None, "with_trend": with_trend,
           "stop_line": row["line"] if with_trend else None, **est}
    if pos:
        qty, avg = int(pos["quantity"]), float(pos.get("average_price") or 0.0)
        out.update({"qty": qty, "avg": avg, **position_figures(premium, est, qty, avg)})
    return out
