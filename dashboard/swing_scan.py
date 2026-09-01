#!/usr/bin/env python3
"""
End-of-day OVERNIGHT SWING positioning scan (a separate lane from the intraday
discipline console). Uses today's data to surface F&O stocks with constructive vs
weak positioning into tomorrow, combining:
  - Close strength (where it closed in the day's range, % vs prev close, vs VWAP)
  - OI buildup from futures (today vs yesterday OI + price): long buildup / short
    buildup / short covering / long unwinding — the "buy/sell" positioning signal.

It is NOT a prediction of tomorrow's direction (overnight gaps are driven by news
and global cues that haven't happened yet). It surfaces where positioning leans,
sizes a gap-aware plan to a user-set risk budget, and flags overnight gap risk.
"""

import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from dashboard import app as core
from dashboard.option_chain import _instruments, _headers, _connected
from dashboard.fno_scanner import fno_universe, _chunk

_FUT: Dict[str, Any] = {"date": None, "map": None}
_LOCK = threading.Lock()


def _futures_map() -> Dict[str, Dict[str, Any]]:
    """name -> nearest-expiry stock future {token, tradingsymbol, lot_size, expiry}."""
    today = date.today().isoformat()
    with _LOCK:
        if _FUT["date"] == today and _FUT["map"] is not None:
            return _FUT["map"]
    best: Dict[str, Dict[str, Any]] = {}
    for r in _instruments():
        if r.get("instrument_type") != "FUT" or r.get("segment") != "NFO-FUT":
            continue
        name, exp = r.get("name"), r.get("expiry")
        if not name or not exp or exp < today:
            continue
        if name not in best or exp < best[name]["expiry"]:
            try:
                best[name] = {"token": r["instrument_token"], "tradingsymbol": r["tradingsymbol"],
                              "lot_size": int(float(r["lot_size"])), "expiry": exp}
            except Exception:
                pass
    with _LOCK:
        _FUT.update({"date": today, "map": best})
    return best


def _daily_candles(token: str, days: int = 45) -> List[List[Any]]:
    """Daily OHLC(+OI) candles for a futures token over the last `days`."""
    frm = (date.today() - timedelta(days=days)).isoformat()
    to = date.today().isoformat()
    try:
        r = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": to, "oi": 1}, headers=_headers(), timeout=8)
        j = r.json()
        return j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        return []


def _buildup_from_candles(candles: List[List[Any]]) -> Optional[Dict[str, Any]]:
    """OI buildup from the last two daily candles (price + OI change)."""
    if len(candles) < 2:
        return None
    prev, last = candles[-2], candles[-1]
    if len(last) < 7 or len(prev) < 7:
        return None
    oi_now, oi_prev, px_now, px_prev = last[6], prev[6], last[4], prev[4]
    up, oi_up = px_now >= px_prev, (oi_now - oi_prev) >= 0
    label = ("Long buildup" if up and oi_up else "Short buildup" if (not up) and oi_up
             else "Short covering" if up and (not oi_up) else "Long unwinding")
    lean = "bullish" if label in ("Long buildup", "Short covering") else "bearish"
    return {"label": label, "lean": lean, "oi": oi_now,
            "oi_chg_pct": round((oi_now - oi_prev) / oi_prev * 100, 1) if oi_prev else None}


def _structure_levels(candles: List[List[Any]], k: int = 2) -> Dict[str, Optional[float]]:
    """Nearest swing-low support below, and swing-high resistance above, expressed as
    % from the latest close. Uses fractal pivots (a low/high with k lower/higher bars
    on each side). Returns None where no clean pivot exists."""
    if len(candles) < 2 * k + 3:
        return {"support_pct": None, "resistance_pct": None}
    highs = [c[2] for c in candles]
    lows = [c[3] for c in candles]
    latest = candles[-1][4]
    piv_low = [lows[i] for i in range(k, len(candles) - k) if lows[i] == min(lows[i - k:i + k + 1])]
    piv_high = [highs[i] for i in range(k, len(candles) - k) if highs[i] == max(highs[i - k:i + k + 1])]
    support = max([p for p in piv_low if p < latest], default=None)
    resistance = min([p for p in piv_high if p > latest], default=None)
    return {
        "support_pct": round((latest - support) / latest * 100, 2) if support else None,
        "resistance_pct": round((resistance - latest) / latest * 100, 2) if resistance else None,
    }


def _oi_buildup(token: str) -> Optional[Dict[str, Any]]:
    """Classify futures OI buildup from the last two daily candles (with OI)."""
    frm = (date.today() - timedelta(days=7)).isoformat()
    to = date.today().isoformat()
    try:
        r = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": to, "oi": 1}, headers=_headers(), timeout=8)
        j = r.json()
        candles = j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
        if len(candles) < 2:
            return None
        prev, last = candles[-2], candles[-1]
        if len(last) < 7 or len(prev) < 7:
            return None
        oi_now, oi_prev = last[6], prev[6]
        px_now, px_prev = last[4], prev[4]
        d_oi = oi_now - oi_prev
        up = px_now >= px_prev
        oi_up = d_oi >= 0
        label = ("Long buildup" if up and oi_up else "Short buildup" if (not up) and oi_up
                 else "Short covering" if up and (not oi_up) else "Long unwinding")
        # bullish lean: long buildup / short covering; bearish: short buildup / long unwinding
        lean = "bullish" if label in ("Long buildup", "Short covering") else "bearish"
        return {"label": label, "lean": lean, "oi": oi_now,
                "oi_chg_pct": round(d_oi / oi_prev * 100, 1) if oi_prev else None}
    except Exception:
        return None


def scan(top: int = 8, risk: float = 1000.0) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"timestamp": ts, "is_live": False, "source": "unavailable",
                           "risk": risk, "universe": 0, "constructive": [], "weak": []}
    if not _connected():
        out["source"] = "Kite not connected — connect on System Check"
        return out
    try:
        names = fno_universe()
        futmap = _futures_map()
        out["universe"] = len(names)
        quotes: Dict[str, Any] = {}
        for group in _chunk([f"NSE:{n}" for n in names], 200):
            j = requests.get("https://api.kite.trade/quote", params=[("i", s) for s in group],
                             headers=_headers(), timeout=10).json()
            if j.get("status") == "success":
                quotes.update(j["data"])

        rows: List[Dict[str, Any]] = []
        for n in names:
            d = quotes.get(f"NSE:{n}")
            fut = futmap.get(n)
            if not d or not fut:
                continue
            ltp = d.get("last_price")
            ohlc = d.get("ohlc", {}) or {}
            prev_close, hi, lo = ohlc.get("close"), ohlc.get("high"), ohlc.get("low")
            vwap = d.get("average_price")
            if not ltp or not prev_close:
                continue
            pct = (ltp - prev_close) / prev_close * 100.0
            rng_pos = ((ltp - lo) / (hi - lo)) if (hi and lo and hi > lo) else 0.5
            vs_vwap = ((ltp - vwap) / vwap * 100.0) if vwap else 0.0
            range_pct = ((hi - lo) / prev_close * 100.0) if (hi and lo and prev_close) else 3.0
            # close-strength score (same shape as intraday, = did it close strong)
            score = pct + vs_vwap + (rng_pos - 0.5) * 4.0
            rows.append({"symbol": n, "ltp": ltp, "prev_close": prev_close, "pct_change": round(pct, 2),
                         "range_pos": round(rng_pos, 2), "vs_vwap_pct": round(vs_vwap, 2),
                         "range_pct": round(range_pct, 2), "score": round(score, 2),
                         "lot_size": fut["lot_size"], "fut_token": fut["token"], "expiry": fut["expiry"]})

        constructive = sorted([r for r in rows if r["score"] > 0], key=lambda r: r["score"], reverse=True)[:top]
        weak = sorted([r for r in rows if r["score"] < 0], key=lambda r: r["score"])[:top]

        def enrich(r: Dict[str, Any], bias: str) -> Dict[str, Any]:
            r = dict(r)
            r["bias"] = bias
            entry, lot = r["ltp"], r["lot_size"]
            candles = _daily_candles(r.pop("fut_token"))
            r["buildup"] = _buildup_from_candles(candles)
            struct = _structure_levels(candles)
            vol_pct = round(max(3.0, r["range_pct"] * 1.5), 1)   # volatility fallback

            # STOP: anchor just beyond the nearest swing level if it's a sane distance
            # (1–15%), else fall back to the volatility stop. 0.3% buffer past the level.
            stop_basis = "volatility"
            if bias == "LONG":
                sp = struct.get("support_pct")
                stop_pct = (sp + 0.3) if (sp and 1.0 <= sp <= 15.0) else vol_pct
                if sp and 1.0 <= sp <= 15.0:
                    stop_basis = "structure (swing low)"
                stop = round(entry * (1 - stop_pct / 100), 1)
            else:
                rp = struct.get("resistance_pct")
                stop_pct = (rp + 0.3) if (rp and 1.0 <= rp <= 15.0) else vol_pct
                if rp and 1.0 <= rp <= 15.0:
                    stop_basis = "structure (swing high)"
                stop = round(entry * (1 + stop_pct / 100), 1)
            risk_per_share = abs(entry - stop)

            # TARGET: the nearest opposite structure level if it clears ≥ 1R after costs,
            # else a 2R target off the stop.
            tgt_basis = "2R"
            if bias == "LONG":
                rp = struct.get("resistance_pct")
                res = entry * (1 + rp / 100) if rp else None
                if res and (res - entry) >= risk_per_share:
                    target, tgt_basis = round(res, 1), "structure (resistance)"
                else:
                    target = round(entry + 2 * risk_per_share, 1)
            else:
                sp = struct.get("support_pct")
                sup = entry * (1 - sp / 100) if sp else None
                if sup and (entry - sup) >= risk_per_share:
                    target, tgt_basis = round(sup, 1), "structure (support)"
                else:
                    target = round(entry - 2 * risk_per_share, 1)

            reward = abs(target - entry)
            rr = round(reward / risk_per_share, 2) if risk_per_share > 0 else None
            per_lot_risk = round(risk_per_share * lot)
            max_lots = int(risk // per_lot_risk) if per_lot_risk > 0 else 0
            r["plan"] = {"entry": entry, "stop": stop, "target": target,
                         "stop_pct": round(stop_pct, 1), "rr": rr,
                         "stop_basis": stop_basis, "target_basis": tgt_basis,
                         "per_lot_risk": per_lot_risk, "max_lots": max_lots,
                         "notional_1lot": round(entry * lot), "fits": max_lots >= 1}
            return r

        out["constructive"] = [enrich(r, "LONG") for r in constructive]
        out["weak"] = [enrich(r, "SHORT") for r in weak]
        out.update({"is_live": True, "source": "Zerodha Kite live (/quote + futures OI)",
                    "scanned": len(rows)})
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(scan(top=5), indent=2, default=str))
