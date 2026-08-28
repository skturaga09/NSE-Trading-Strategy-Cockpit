#!/usr/bin/env python3
"""
Live ATM option-chain for the Intraday tab: ATM plus 3 strikes above and below,
with LTP, bid/ask/spread, volume, OI and computed IV — pulled from Kite so the
user does not hand-type the chain. Verified lot size and the nearest expiry come
straight from the Kite instruments master (never guessed).

Honest limits: IV is computed (Black-Scholes bisection on the market mid), since
Kite /quote does not return it; change-in-OI is not available from a single quote
and is omitted rather than invented. Everything carries a timestamp and a
live/unavailable flag.
"""

import csv
import io
import math
import threading
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests

from dashboard import app as core

RATE = 0.065  # India risk-free (approx)
# Index underlyings quote under special spot names; stocks quote as NSE:<symbol>.
INDEX_SYM = {
    "NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
    "NIFTYNXT50": "NSE:NIFTY NEXT 50",
}
_INSTR: Dict[str, Any] = {"date": None, "rows": None}
_LOCK = threading.Lock()


def spot_symbol(underlying: str) -> str:
    """Kite spot instrument for an index or an F&O stock."""
    return INDEX_SYM.get(underlying.upper(), f"NSE:{underlying.upper()}")


def _headers() -> Dict[str, str]:
    kc = core.KITE_CONFIG
    return {"Authorization": f"token {kc.get('api_key','')}:{kc.get('access_token','')}", "X-Kite-Version": "3"}


def _connected() -> bool:
    kc = core.KITE_CONFIG
    return bool(kc.get("api_key") and kc.get("access_token"))


# ---- Black-Scholes price + implied-vol (self-contained) ----
def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs(S: float, K: float, T: float, vol: float, is_call: bool) -> float:
    if T <= 0 or vol <= 0:
        return max(0.0, (S - K) if is_call else (K - S))
    d1 = (math.log(S / K) + (RATE + 0.5 * vol * vol) * T) / (vol * math.sqrt(T))
    d2 = d1 - vol * math.sqrt(T)
    if is_call:
        return S * _ncdf(d1) - K * math.exp(-RATE * T) * _ncdf(d2)
    return K * math.exp(-RATE * T) * _ncdf(-d2) - S * _ncdf(-d1)


def _iv(price: float, S: float, K: float, T: float, is_call: bool) -> Optional[float]:
    if not price or price <= 0 or T <= 0:
        return None
    intrinsic = max(0.0, (S - K) if is_call else (K - S))
    if price < intrinsic:  # arbitrage / stale — can't imply a vol
        return None
    lo, hi = 0.001, 5.0
    mid = 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        p = _bs(S, K, T, mid, is_call)
        if abs(p - price) < 0.01:
            break
        if p > price:
            hi = mid
        else:
            lo = mid
    return round(mid * 100.0, 1)


def _instruments() -> List[Dict[str, str]]:
    """Kite NFO instrument master, cached for the day."""
    today = date.today().isoformat()
    with _LOCK:
        if _INSTR["date"] == today and _INSTR["rows"] is not None:
            return _INSTR["rows"]
    r = requests.get("https://api.kite.trade/instruments/NFO", headers=_headers(), timeout=30)
    rows = list(csv.DictReader(io.StringIO(r.text)))
    with _LOCK:
        _INSTR.update({"date": today, "rows": rows})
    return rows


def _spot_ltp(underlying: str) -> Optional[float]:
    sym = spot_symbol(underlying)
    r = requests.get("https://api.kite.trade/quote/ltp", params=[("i", sym)], headers=_headers(), timeout=6)
    j = r.json()
    if j.get("status") == "success":
        return (j["data"].get(sym, {}) or {}).get("last_price")
    return None


def chain(underlying: str = "NIFTY") -> Dict[str, Any]:
    underlying = underlying.upper()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"underlying": underlying, "timestamp": ts, "is_live": False,
                           "source": "unavailable", "spot": None, "atm": None,
                           "expiry": None, "lot_size": None, "rows": []}
    if not _connected():
        out["source"] = "Kite not connected — connect on System Check"
        return out
    try:
        spot = _spot_ltp(underlying)
        if not spot:
            out["source"] = f"Could not fetch spot for {underlying} (is it an F&O name?)"
            return out

        # Nearest expiry >= today for this underlying's options, from the master.
        instr = [r for r in _instruments()
                 if r.get("name") == underlying and r.get("instrument_type") in ("CE", "PE")
                 and r.get("segment") == "NFO-OPT"]
        if not instr:
            out["source"] = f"{underlying} has no listed options (not an F&O stock/index?)"
            return out
        today = date.today()
        expiries = sorted({r["expiry"] for r in instr if r.get("expiry")})
        nearest = next((e for e in expiries if e >= today.isoformat()), expiries[0] if expiries else None)
        if not nearest:
            out["source"] = "No option expiries found"
            return out
        exp_date = datetime.strptime(nearest, "%Y-%m-%d").date()
        T = max((exp_date - today).days, 0) / 365.0
        lot = None

        # Map (strike, type) -> tradingsymbol for the nearest expiry.
        by_key: Dict[Any, Dict[str, str]] = {}
        for r in instr:
            if r.get("expiry") != nearest:
                continue
            try:
                k = int(float(r["strike"]))
            except Exception:
                continue
            by_key[(k, r["instrument_type"])] = r
            if lot is None and r.get("lot_size"):
                lot = int(float(r["lot_size"]))

        # ATM = nearest ACTUALLY-LISTED strike to spot; take 3 listed strikes each side.
        # (Robust for any per-stock strike interval — no hard-coded step.)
        listed = sorted({k for (k, _t) in by_key})
        if not listed:
            out["source"] = "No strikes for the nearest expiry"
            return out
        ai = min(range(len(listed)), key=lambda i: abs(listed[i] - spot))
        atm = listed[ai]
        strikes = listed[max(0, ai - 3): ai + 4]
        want: List[str] = []
        for k in strikes:
            for typ in ("CE", "PE"):
                row = by_key.get((int(k), typ))
                if row:
                    want.append(f"NFO:{row['tradingsymbol']}")
        if not want:
            out["source"] = "No strikes matched around ATM"
            return out

        # Batch quote (LTP, OI, volume, depth for bid/ask).
        q = requests.get("https://api.kite.trade/quote",
                         params=[("i", s) for s in want], headers=_headers(), timeout=8).json()
        qd = q.get("data", {}) if q.get("status") == "success" else {}

        def leg(k: int, typ: str) -> Optional[Dict[str, Any]]:
            row = by_key.get((k, typ))
            if not row:
                return None
            d = qd.get(f"NFO:{row['tradingsymbol']}", {})
            ltp = d.get("last_price")
            depth = d.get("depth", {}) or {}
            buy = (depth.get("buy") or [{}])[0]
            sell = (depth.get("sell") or [{}])[0]
            bid = buy.get("price") or None
            ask = sell.get("price") or None
            spread = round(ask - bid, 2) if (bid and ask) else None
            mid = (bid + ask) / 2 if (bid and ask) else ltp
            iv = _iv(mid, spot, k, T, typ == "CE")
            return {"symbol": row["tradingsymbol"], "ltp": ltp, "bid": bid, "ask": ask,
                    "spread": spread, "volume": d.get("volume"), "oi": d.get("oi"), "iv": iv}

        rows = []
        for k in strikes:
            rows.append({"strike": int(k), "atm": int(k) == int(atm),
                         "call": leg(int(k), "CE"), "put": leg(int(k), "PE")})

        out.update({"is_live": True, "source": "Zerodha Kite live (/quote + instruments)",
                    "spot": spot, "atm": int(atm), "expiry": nearest, "lot_size": lot, "rows": rows})
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(chain("NIFTY"), indent=2, default=str))
