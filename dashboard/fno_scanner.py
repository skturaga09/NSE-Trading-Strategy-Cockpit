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
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

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


_DAILY: Dict[Any, Any] = {}  # instrument_token -> (date_iso, candles) — ~70 sessions


def _daily(token: Any) -> List[Any]:
    """Recent daily candles for a token, cached per day. ~100 calendar days (~68 sessions)
    — enough for both ADR(14) and the 50-DMA. Only called for the handful of RANKED names
    shown, so the live scan stays cheap (no 200-name history sweep)."""
    today = date.today().isoformat()
    hit = _DAILY.get(token)
    if hit and hit[0] == today:
        return hit[1]
    frm = (date.today() - timedelta(days=100)).isoformat()
    cs: List[Any] = []
    try:
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": today}, headers=_headers(), timeout=8).json()
        if j.get("status") == "success":
            cs = j.get("data", {}).get("candles", []) or []
    except Exception:
        cs = []
    if cs:
        _DAILY[token] = (today, cs)
    return cs


def _adr_pct(token: Any, days: int = 14) -> Optional[float]:
    """Average Daily Range % = mean of (high-low)/prev_close over the last `days` sessions."""
    cs = _daily(token)[-(days + 1):]
    ranges = [(cs[i][2] - cs[i][3]) / cs[i - 1][4] * 100 for i in range(1, len(cs)) if cs[i - 1][4]]
    return round(sum(ranges) / len(ranges), 2) if ranges else None


def _dma50(token: Any, n: int = 50) -> Optional[Dict[str, Any]]:
    """50-day moving average CONTEXT (not a signal): is price above or below it, and by how
    much. Above = buyers in control / don't-fight-the-trend; below = sellers. A filter, not
    an edge (our backtests: the cross alone is ~breakeven)."""
    cs = _daily(token)
    if len(cs) < n:
        return None
    closes = [c[4] for c in cs]
    dma = sum(closes[-n:]) / n
    last = closes[-1]
    if not dma:
        return None
    return {"state": "ABOVE" if last >= dma else "BELOW", "dist_pct": round((last / dma - 1) * 100, 2)}


def _attach_headroom(rows: List[Dict[str, Any]]) -> None:
    """For each ranked row, attach ADR-remaining headroom: how much of its TYPICAL daily
    range is still unused, sized to a lot. This is forward (room left), not hindsight —
    a floor near 0 means 'already ran its usual range today → chasing'. Not a forecast:
    the day can over- or under-run its average; it's a context gauge for the entry.
    Also attaches the 50-DMA trend context (above/below), from the same daily fetch."""
    for r in rows:
        tok, used, ltp, lot = r.get("instrument_token"), r.get("range_used_pct"), r.get("ltp"), r.get("lot_size")
        adr = _adr_pct(tok) if tok else None
        dma = _dma50(tok) if tok else None
        r["adr_pct"] = adr
        r["dma50_state"] = dma["state"] if dma else None
        r["dma50_dist_pct"] = dma["dist_pct"] if dma else None
        if adr is None or used is None or not ltp or not lot:
            r["headroom_pct"] = None
            r["headroom_per_lot"] = None
            continue
        remaining = max(0.0, adr - used)
        r["headroom_pct"] = round(remaining, 2)
        r["headroom_per_lot"] = round(remaining / 100.0 * ltp * lot)


# Validated magnitude lift: a big pre-open gap (|gap|≥GAP_MIN_FOR_LIFT%) day runs ~1.29× the
# average day's range out-of-sample (see premarket_gap_backtest.py). The lift is validated
# ONLY for real gaps, so a near-flat name gets plain ADR (lift 1.0), not an inflated range.
# Used only to size the "expected range" context — NOT a directional claim.
GAP_RANGE_LIFT = 1.29
GAP_MIN_FOR_LIFT = 1.0


def _universe_quotes() -> tuple:
    """(names, lot_map, quotes) for the F&O universe — one batched /quote sweep.
    Shared by the momentum scan and the pre-open gap scan so they can't drift apart."""
    names = fno_universe()
    lot_map: Dict[str, int] = {}
    for r in _instruments():
        if r.get("instrument_type") == "FUT" and r.get("segment") == "NFO-FUT" and r.get("name"):
            try:
                lot_map[r["name"]] = int(float(r["lot_size"]))
            except Exception:
                pass
    quotes: Dict[str, Any] = {}
    for group in _chunk([f"NSE:{n}" for n in names], 200):
        r = requests.get("https://api.kite.trade/quote",
                         params=[("i", s) for s in group], headers=_headers(), timeout=10)
        j = r.json()
        if j.get("status") != "success":   # e.g. expired token — surface it, don't show an empty "live" scan
            raise RuntimeError(f"{j.get('error_type', 'Kite')}: {j.get('message', 'quote failed')}")
        quotes.update(j["data"])
    return names, lot_map, quotes


def _attach_expected_range(rows: List[Dict[str, Any]]) -> None:
    """Attach the validated 'expected range today' for a gapped name: its ADR scaled by
    the big-gap lift, as % and ₹/lot. This is a MAGNITUDE estimate (how wide a day),
    not a direction — a gapped name tends to run ~1.29× its normal range."""
    for r in rows:
        tok, ref, lot = r.get("instrument_token"), r.get("ref_price"), r.get("lot_size")
        adr = _adr_pct(tok) if tok else None
        dma = _dma50(tok) if tok else None
        r["adr_pct"] = adr
        r["dma50_state"] = dma["state"] if dma else None
        r["dma50_dist_pct"] = dma["dist_pct"] if dma else None
        if adr is None or not ref or not lot:
            r["exp_range_pct"] = None
            r["exp_range_per_lot"] = None
            continue
        # The 1.29 lift is only validated for REAL gaps; a near-flat name gets plain ADR.
        lift = GAP_RANGE_LIFT if abs(r.get("gap_pct", 0)) >= GAP_MIN_FOR_LIFT else 1.0
        exp = adr * lift
        r["lift_applied"] = lift > 1.0
        r["exp_range_pct"] = round(exp, 2)
        r["exp_range_per_lot"] = round(exp / 100.0 * ref * lot)


def premarket_scan(top: int = 12) -> Dict[str, Any]:
    """Pre-open gap screen: rank F&O names by the opening gap (pre-open indicative price,
    or today's open, vs prev close). A big gap flags a likely WIDE-range day (validated
    magnitude edge) — it does NOT predict direction. A watchlist, never a buy list."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # True only during the NSE pre-open auction window (09:00–09:08 IST, weekdays). Outside
    # it the gap is TODAY's realised open vs prev close — already played out, not a forward
    # setup. shortcut: ignores exchange holidays; upgrade with a holiday calendar if needed.
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    in_preopen = now_ist.weekday() < 5 and (9, 0) <= (now_ist.hour, now_ist.minute) <= (9, 8)
    out: Dict[str, Any] = {"timestamp": ts, "is_live": False, "source": "unavailable",
                           "universe": 0, "in_preopen": in_preopen, "gap_up": [], "gap_down": []}
    if not _connected():
        out["source"] = "Kite not connected — connect on System Check"
        return out
    try:
        names, lot_map, quotes = _universe_quotes()
        out["universe"] = len(names)
        rows: List[Dict[str, Any]] = []
        for n in names:
            d = quotes.get(f"NSE:{n}")
            if not d:
                continue
            ohlc = d.get("ohlc", {}) or {}
            prev_close = ohlc.get("close")
            ref = ohlc.get("open") or d.get("last_price")   # pre-open indicative, else today's open
            if not ref or not prev_close:
                continue
            rows.append({
                "symbol": n, "ref_price": ref, "prev_close": prev_close,
                "instrument_token": d.get("instrument_token"), "lot_size": lot_map.get(n),
                "gap_pct": round((ref - prev_close) / prev_close * 100.0, 2),
            })
        ups = sorted([r for r in rows if r["gap_pct"] > 0], key=lambda r: r["gap_pct"], reverse=True)[:top]
        downs = sorted([r for r in rows if r["gap_pct"] < 0], key=lambda r: r["gap_pct"])[:top]
        _attach_expected_range(ups)       # ADR history only for the names shown
        _attach_expected_range(downs)
        out.update({"is_live": True, "source": "Zerodha Kite live (pre-open / open gap)",
                    "scanned": len(rows), "gap_up": ups, "gap_down": downs})
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


def _tier(bias: str, regime: Optional[str], dma50_state: Optional[str], pct_change: float,
          gap_pct: Optional[float], headroom_pct: Optional[float], vs_vwap_pct: Optional[float]) -> Dict[str, Any]:
    """Permission tier from the hygiene factors we already compute. DISCIPLINE, not a profit
    forecast (confluence showed no edge OOS — see regime_filter_backtest.py). GO = 'clears
    every hygiene bar → worth loading and running the 14 gates', never 'this will win'."""
    hostile = (regime == "RISK_OFF" and bias == "LONG") or (regime == "RISK_ON" and bias == "SHORT")
    checks = {
        "trend": (dma50_state == "ABOVE") if bias == "LONG" else (dma50_state == "BELOW"),   # don't fight the 50-DMA
        "participation": abs(pct_change) >= 1.5 or abs(gap_pct or 0) >= 1.0,                  # a real mover
        "room": (headroom_pct or 0) > 0.3,                                                    # not chased
        "vwap": vs_vwap_pct is not None and (vs_vwap_pct > 0 if bias == "LONG" else vs_vwap_pct < 0),
    }
    fails = [k for k, v in checks.items() if not v]
    if hostile:
        return {"tier": "STAND DOWN", "why": f"{regime} tape vs {bias} — don't fight it", "checks": checks}
    if not fails:
        return {"tier": "GO", "why": "clears every hygiene bar — load it and run the 14 gates", "checks": checks}
    if len(fails) == 1:
        return {"tier": "WATCH", "why": "missing: " + fails[0], "checks": checks}
    return {"tier": "STAND DOWN", "why": "missing: " + ", ".join(fails), "checks": checks}


def shortlist(top: int = 12) -> Dict[str, Any]:
    """One permission verdict per ranked candidate — fuses regime + trend + participation +
    room + VWAP into GO / WATCH / STAND DOWN. Assembly of existing factors, no new signal."""
    from dashboard.exit_monitor import _current_regime
    s = scan(top=top)
    regime = None
    try:
        regime = _current_regime()
    except Exception:
        pass
    out = {"timestamp": s["timestamp"], "is_live": s["is_live"], "source": s.get("source"),
           "regime": regime, "universe": s.get("universe"), "scanned": s.get("scanned"), "names": []}
    if not s.get("is_live"):
        return out
    rows = []
    for r in s["longs"] + s["shorts"]:
        t = _tier(r["bias"], regime, r.get("dma50_state"), r.get("pct_change", 0),
                  r.get("gap_pct"), r.get("headroom_pct"), r.get("vs_vwap_pct"))
        rows.append({"symbol": r["symbol"], "bias": r["bias"], "lot_size": r.get("lot_size"), "ltp": r.get("ltp"),
                     "pct_change": r.get("pct_change"), "dma50_state": r.get("dma50_state"),
                     "headroom_per_lot": r.get("headroom_per_lot"), **t})
    rank = {"GO": 0, "WATCH": 1, "STAND DOWN": 2}
    rows.sort(key=lambda x: rank[x["tier"]])
    out["names"] = rows
    return out


def scan(top: int = 12) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"timestamp": ts, "is_live": False, "source": "unavailable",
                           "universe": 0, "longs": [], "shorts": []}
    if not _connected():
        out["source"] = "Kite not connected — connect on System Check"
        return out
    try:
        names, lot_map, quotes = _universe_quotes()
        out["universe"] = len(names)
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
            bias = "LONG" if score > 0 else "SHORT"
            lot = lot_map.get(n)
            # % of the day's range already travelled — the baseline for ADR headroom below.
            range_used = ((hi - lo) / prev_close * 100.0) if (hi and lo) else None
            rows.append({
                "symbol": n, "ltp": ltp, "prev_close": prev_close,
                "instrument_token": d.get("instrument_token"),
                "pct_change": round(pct, 2),
                "vs_vwap_pct": round(vs_vwap, 2) if vs_vwap is not None else None,
                "range_pos": round(rng_pos, 2) if rng_pos is not None else None,
                "gap_pct": round(gap, 2) if gap is not None else None,
                "range_used_pct": round(range_used, 2) if range_used is not None else None,
                "volume": vol, "score": round(score, 2), "bias": bias, "lot_size": lot,
            })

        longs = sorted([r for r in rows if r["vs_vwap_pct"] is None or r["vs_vwap_pct"] > 0],
                       key=lambda r: r["score"], reverse=True)[:top]
        shorts = sorted([r for r in rows if r["vs_vwap_pct"] is None or r["vs_vwap_pct"] < 0],
                        key=lambda r: r["score"])[:top]
        _attach_headroom(longs)       # ADR history only for the names actually shown
        _attach_headroom(shorts)
        out.update({"is_live": True, "source": "Zerodha Kite live (/quote day VWAP)",
                    "scanned": len(rows), "longs": longs, "shorts": shorts})
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(scan(), indent=2, default=str))
