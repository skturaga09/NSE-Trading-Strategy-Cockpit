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
