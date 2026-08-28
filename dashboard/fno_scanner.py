#!/usr/bin/env python3
"""
Live intraday F&O stock scanner — surfaces WHERE the action is so the user does
not hand-pick from ~180 F&O names. For every F&O stock it pulls one Kite /quote
and scores objective, verifiable intraday momentum: position vs the day VWAP,
position in the day's range, and % change from the previous close. It then ranks
the strongest long-side and short-side candidates.

This is a SCREEN, not advice: it says "these are moving with conviction right
now," not "buy this." The Intraday discipline gates still decide go/no-go, and no
edge or profit is claimed. Every figure is live and timestamped.
"""

import threading
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests

from dashboard import app as core
from dashboard.option_chain import _instruments, _headers, _connected

_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
_UNIV: Dict[str, Any] = {"date": None, "names": None}
_LOCK = threading.Lock()


def fno_universe() -> List[str]:
    """F&O stock underlyings (names with listed stock futures), minus indices."""
    today = date.today().isoformat()
    with _LOCK:
        if _UNIV["date"] == today and _UNIV["names"] is not None:
            return _UNIV["names"]
    names = sorted({
        r["name"] for r in _instruments()
        if r.get("instrument_type") == "FUT" and r.get("segment") == "NFO-FUT"
        and r.get("name") and r["name"] not in _INDICES
    })
    with _LOCK:
        _UNIV.update({"date": today, "names": names})
    return names


def _chunk(xs: List[str], n: int):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def scan(top: int = 12) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"timestamp": ts, "is_live": False, "source": "unavailable",
                           "universe": 0, "longs": [], "shorts": []}
    if not _connected():
        out["source"] = "Kite not connected — connect on System Check"
        return out
    try:
        names = fno_universe()
        out["universe"] = len(names)
        quotes: Dict[str, Any] = {}
        for group in _chunk([f"NSE:{n}" for n in names], 200):
            r = requests.get("https://api.kite.trade/quote",
                             params=[("i", s) for s in group], headers=_headers(), timeout=10)
            j = r.json()
            if j.get("status") == "success":
                quotes.update(j["data"])

        rows: List[Dict[str, Any]] = []
        for n in names:
            d = quotes.get(f"NSE:{n}")
            if not d:
                continue
            ltp = d.get("last_price")
            ohlc = d.get("ohlc", {}) or {}
            prev_close = ohlc.get("close")
            hi, lo = ohlc.get("high"), ohlc.get("low")
            vwap = d.get("average_price")  # day VWAP from Kite
            vol = d.get("volume")
            if not ltp or not prev_close:
                continue
            pct = (ltp - prev_close) / prev_close * 100.0
            vs_vwap = ((ltp - vwap) / vwap * 100.0) if vwap else None
            rng_pos = ((ltp - lo) / (hi - lo)) if (hi and lo and hi > lo) else None
            gap = ((ohlc.get("open") - prev_close) / prev_close * 100.0) if ohlc.get("open") else None
            # Objective momentum score: today's move + stance vs VWAP + where in range.
            score = pct
            if vs_vwap is not None:
                score += vs_vwap
            if rng_pos is not None:
                score += (rng_pos - 0.5) * 4.0
            rows.append({
                "symbol": n, "ltp": ltp, "pct_change": round(pct, 2),
                "vs_vwap_pct": round(vs_vwap, 2) if vs_vwap is not None else None,
                "range_pos": round(rng_pos, 2) if rng_pos is not None else None,
                "gap_pct": round(gap, 2) if gap is not None else None,
                "volume": vol, "score": round(score, 2),
                "bias": "LONG" if score > 0 else "SHORT",
            })

        longs = sorted([r for r in rows if r["vs_vwap_pct"] is None or r["vs_vwap_pct"] > 0],
                       key=lambda r: r["score"], reverse=True)[:top]
        shorts = sorted([r for r in rows if r["vs_vwap_pct"] is None or r["vs_vwap_pct"] < 0],
                        key=lambda r: r["score"])[:top]
        out.update({"is_live": True, "source": "Zerodha Kite live (/quote day VWAP)",
                    "scanned": len(rows), "longs": longs, "shorts": shorts})
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(scan(), indent=2, default=str))
