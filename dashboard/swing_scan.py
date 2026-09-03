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

# OI-buildup thresholds — day-over-day % change in futures open interest. OI is a
# DAILY signal (it accumulates through the session), so the overnight board treats
# these as the bar to "seriously consider" a name for an overnight hold.
OI_NOISE = 5.0          # below this = noise, not a real buildup
OI_NOTABLE = 10.0       # surface as an overnight candidate at/above this
OI_STRONG = 20.0        # aggressive positioning
OI_REFRESH_MIN = 30.0   # recompute the full-universe OI map at most this often
                        # (OI is a daily signal — no need to churn it every few min)
OI_FORMING_BEFORE = "14:00"  # today's OI is still accumulating before this IST time

# Secondary "building" tier: a FRESH buildup below the notable OI bar but with a STRONG
# close. Catches strong movers (e.g. SOLARINDS +4.5% OI, +4.4% close, near day high) that
# the OI bar alone would drop. The strong-close filter is what separates these from the
# 200+ flat-OI names — the conviction here comes from price, with OI merely confirming.
SEC_OI_FLOOR = 1.0      # OI must be genuinely rising (fresh longs/shorts), not flat
SEC_MOVE_MIN = 2.5      # |day % move| at least this — a real mover, not a drift
SEC_RANGE_MIN = 0.6     # closed in the top (long) / bottom (short) of the day's range

# Ignition scanner — the SOLARINDS "early accumulation" footprint. Fuses the signals a
# discretionary trader can't watch across 200+ names at once: a VOLUME surge (the move
# has real participation), a MULTI-DAY OI build (accumulation, not a one-day squeeze), a
# fresh buildup + strong close, and a breakout from a base. Public data — the edge is
# complete, consistent, MEASURED coverage, not secret info. Validated by the learning layer.
IGNITION_RELVOL_MIN = 1.5   # today's volume must be >= this x its ~20-day average
IGNITION_MIN_SCORE = 45.0   # 0..100 composite bar to surface as an ignition candidate


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


_CANDLES: Dict[str, Any] = {}  # token -> (date_iso, candles) — daily candles change once/day


def _daily_candles(token: str, days: int = 45) -> List[List[Any]]:
    """Daily OHLC(+OI) candles for a futures token over the last `days`. Cached per day:
    the structure levels derived from these come from prior-session pivots and don't
    move intraday, so we fetch once per token per day instead of on every 30s scan —
    which keeps the per-scan enrich() from hammering Kite's historical endpoint."""
    today = date.today().isoformat()
    hit = _CANDLES.get(token)
    if hit and hit[0] == today and hit[1]:
        return hit[1]
    frm = (date.today() - timedelta(days=days)).isoformat()
    to = today
    try:
        r = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": to, "oi": 1}, headers=_headers(), timeout=8)
        j = r.json()
        candles = j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        candles = []
    if candles:
        _CANDLES[token] = (today, candles)
    return candles


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


def _levels(entry: float, struct: Dict[str, Optional[float]], bias: str,
            vol_fallback: float, lo: float = 1.0, hi: float = 15.0, buf: float = 0.3) -> Dict[str, Any]:
    """Derive stop & target from structure (nearest swing level) with a volatility
    fallback, plus R:R. Shared by swing (daily) and intraday plans."""
    if bias == "LONG":
        sp = struct.get("support_pct")
        use = sp is not None and lo <= sp <= hi
        stop_pct = (sp + buf) if use else vol_fallback
        stop = round(entry * (1 - stop_pct / 100), 2)
        stop_basis = "structure (swing low)" if use else "volatility"
    else:
        rp = struct.get("resistance_pct")
        use = rp is not None and lo <= rp <= hi
        stop_pct = (rp + buf) if use else vol_fallback
        stop = round(entry * (1 + stop_pct / 100), 2)
        stop_basis = "structure (swing high)" if use else "volatility"
    risk = abs(entry - stop)
    tgt_basis = "2R"
    if bias == "LONG":
        rp = struct.get("resistance_pct")
        res = entry * (1 + rp / 100) if rp else None
        if res and (res - entry) >= risk:
            target, tgt_basis = round(res, 2), "structure (resistance)"
        else:
            target = round(entry + 2 * risk, 2)
    else:
        sp = struct.get("support_pct")
        sup = entry * (1 - sp / 100) if sp else None
        if sup and (entry - sup) >= risk:
            target, tgt_basis = round(sup, 2), "structure (support)"
        else:
            target = round(entry - 2 * risk, 2)
    rr = round(abs(target - entry) / risk, 2) if risk > 0 else None
    return {"entry": entry, "stop": stop, "target": target, "stop_pct": round(stop_pct, 1),
            "rr": rr, "stop_basis": stop_basis, "target_basis": tgt_basis, "risk_per_share": round(risk, 2)}


def _intraday_candles(token: str, days: int = 5, interval: str = "15minute") -> List[List[Any]]:
    frm = (date.today() - timedelta(days=days)).isoformat()
    to = date.today().isoformat()
    try:
        r = requests.get(f"https://api.kite.trade/instruments/historical/{token}/{interval}",
                         params={"from": frm, "to": to}, headers=_headers(), timeout=8)
        j = r.json()
        return j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        return []


def intraday_structure_plan(underlying: str) -> Dict[str, Any]:
    """Structure-based intraday stop/target for a single underlying, from 15-min
    swing pivots over the last few sessions (volatility fallback ~1.5%)."""
    from dashboard.option_chain import _spot_ltp
    underlying = underlying.upper()
    out: Dict[str, Any] = {"underlying": underlying, "is_live": False, "source": "unavailable",
                           "spot": None, "long": None, "short": None}
    if not _connected():
        out["source"] = "Kite not connected"
        return out
    try:
        fut = _futures_map().get(underlying)
        spot = _spot_ltp(underlying)
        if not fut or not spot:
            out["source"] = "No futures/spot for this underlying"
            return out
        candles = _intraday_candles(fut["token"])
        if len(candles) < 12:
            out["source"] = "Not enough intraday history"
            return out
        struct = _structure_levels(candles, k=2)
        out.update({
            "is_live": True, "source": "Zerodha Kite 15-min structure", "spot": spot,
            "long": _levels(spot, struct, "LONG", vol_fallback=1.5, lo=0.5, hi=6.0, buf=0.2),
            "short": _levels(spot, struct, "SHORT", vol_fallback=1.5, lo=0.5, hi=6.0, buf=0.2),
        })
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


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


def _market_open_now() -> bool:
    """NSE weekday hours in IST (no holiday calendar)."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    return "09:15" <= now.strftime("%H:%M") <= "15:30"


def _oi_tier(oi_chg_pct: Optional[float]) -> Optional[str]:
    """Bucket a day-over-day OI change into a conviction tier."""
    if oi_chg_pct is None:
        return None
    a = abs(oi_chg_pct)
    return ("strong" if a >= OI_STRONG else "notable" if a >= OI_NOTABLE
            else "mild" if a >= OI_NOISE else "noise")


def _signal_pack(candles: List[List[Any]]) -> Optional[Dict[str, Any]]:
    """Full per-name daily-signal pack from one candle series [ts,o,h,l,c,vol,oi]:
    OI buildup (+tier), relative volume (today vs ~20-day avg), OI trend (consecutive
    up sessions + 3-session change), and nearest pivot distances (breakout proximity).
    Everything the Ignition score needs, computed from a single fetch."""
    if not candles or len(candles) < 4:
        return None
    b = _buildup_from_candles(candles) or {}
    if b.get("oi_chg_pct") is not None:
        b["tier"] = _oi_tier(b["oi_chg_pct"])
    # Relative volume: today vs the average of the prior ~20 sessions.
    vols = [c[5] for c in candles if len(c) > 5 and c[5] is not None]
    if len(vols) >= 6:
        base = vols[-21:-1] if len(vols) >= 21 else vols[:-1]
        avg = (sum(base) / len(base)) if base else 0
        b["rel_volume"] = round(vols[-1] / avg, 2) if avg else None
    # OI trend: consecutive up-OI sessions ending today, and the 3-session OI change.
    ois = [c[6] for c in candles if len(c) > 6 and c[6] is not None]
    if len(ois) >= 4:
        streak = 0
        for i in range(len(ois) - 1, 0, -1):
            if ois[i] > ois[i - 1]:
                streak += 1
            else:
                break
        b["oi_up_days"] = streak
        b["oi_3d_pct"] = round((ois[-1] - ois[-4]) / ois[-4] * 100, 1) if ois[-4] else None
    # Breakout proximity: nearest pivot above (resistance) / below (support), % from close.
    st = _structure_levels(candles)
    b["resistance_pct"] = st.get("resistance_pct")
    b["support_pct"] = st.get("support_pct")
    return b or None


def _full_pack(token: str) -> Optional[Dict[str, Any]]:
    """Fetch ~40 sessions of daily candles (fresh, so OI/volume reflect the latest) and
    build the full signal pack. Used by the background full-universe refresh."""
    frm = (date.today() - timedelta(days=60)).isoformat()
    to = date.today().isoformat()
    try:
        r = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": to, "oi": 1}, headers=_headers(), timeout=8)
        j = r.json()
        candles = j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        return None
    return _signal_pack(candles)


def _ignition(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Score a name's 'ignition' — early accumulation footprint — from its live price row
    plus the cached daily pack. Requires a real volume surge AND a fresh buildup; blends
    volume, multi-day OI, direction-agreeing strong close, and breakout proximity into
    0..100. Returns None when it doesn't qualify."""
    p = r.get("buildup") or {}
    rv = p.get("rel_volume")
    label = p.get("label")
    if rv is None or rv < IGNITION_RELVOL_MIN or label not in ("Long buildup", "Short buildup"):
        return None
    d = 1 if label == "Long buildup" else -1
    rel = min(rv, 4.0) / 4.0                                   # volume surge (capped 4x)
    oi_days = min(p.get("oi_up_days") or 0, 3) / 3.0           # sustained accumulation
    dir_up = 1.0 if (r["pct_change"] * d) > 0 else 0.0
    close = (r["range_pos"] if d == 1 else 1 - r["range_pos"]) * dir_up   # strong close in dir
    lvl = p.get("resistance_pct") if d == 1 else p.get("support_pct")
    brk = 1.0 if lvl is None else max(0.0, 1 - min(lvl, 5.0) / 5.0)        # near/at breakout
    score = 100.0 * (0.35 * rel + 0.25 * oi_days + 0.20 * close + 0.20 * brk)
    return {"score": round(score, 1), "bias": "LONG" if d == 1 else "SHORT",
            "rel_volume": rv, "oi_up_days": p.get("oi_up_days"), "oi_3d_pct": p.get("oi_3d_pct"),
            "components": {"vol": round(rel, 2), "oi_trend": round(oi_days, 2),
                           "close": round(close, 2), "breakout": round(brk, 2)}}


# Full-universe OI buildup cache: {name -> buildup dict or None}. OI is a slow daily
# signal, so we compute it for EVERY futures name (so a big buildup can never be
# dropped just because its price score isn't top-N) but refresh only every
# OI_REFRESH_MIN and off the request path (P4) — a background thread does the ~190
# historical calls so the fast price scan is never blocked.
_OI: Dict[str, Any] = {"date": None, "ts": None, "map": None, "busy": False}


def _refresh_oi(futmap: Dict[str, Dict[str, Any]]) -> None:
    """Recompute OI buildup for the whole futures universe (throttled to ~3 req/s for
    Kite's historical limit). A per-name failure is stored as None so that name shows
    as 'OI unavailable' rather than silently vanishing — completeness over a clean lie."""
    m: Dict[str, Optional[Dict[str, Any]]] = {}
    for name, fut in futmap.items():
        b: Optional[Dict[str, Any]] = None
        try:
            b = _full_pack(fut["token"])   # OI buildup + rel-volume + OI-trend + breakout
        except Exception:
            b = None
        m[name] = b
        time.sleep(0.2)  # + network latency ≈ 3 req/s (Kite historical limit)
    with _LOCK:
        _OI.update({"date": date.today().isoformat(), "ts": datetime.now(), "map": m, "busy": False})


def _oi_map(futmap: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Return the freshest cached OI map immediately; kick a non-blocking refresh when
    it's stale (or empty). Skips the refresh after market close once today's snapshot
    exists (OI is final for the day), so it doesn't churn overnight."""
    today = date.today().isoformat()
    now = datetime.now()
    with _LOCK:
        fresh = (_OI["date"] == today and _OI["map"] is not None and _OI["ts"] is not None
                 and (now - _OI["ts"]).total_seconds() < OI_REFRESH_MIN * 60)
        cached = _OI["map"] or {}
        ts = _OI["ts"]
        busy = _OI.get("busy", False)
    should = (not fresh) and (not busy) and (_market_open_now() or not cached)
    if should:
        with _LOCK:
            _OI["busy"] = True
        threading.Thread(target=_refresh_oi, args=(dict(futmap),), daemon=True).start()
    return {"map": cached, "ts": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else None,
            "ready": bool(cached)}


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

        # Attach the cached full-universe OI buildup to every scanned name (free — it's
        # already computed), so OI can drive the overnight boards below without any name
        # being dropped for being outside the price-ranked top-N.
        oi = _oi_map(futmap)
        oimap = oi["map"]
        for r in rows:
            r["buildup"] = oimap.get(r["symbol"])

        def enrich(r: Dict[str, Any], bias: str) -> Dict[str, Any]:
            r = dict(r)
            r["bias"] = bias
            entry, lot = r["ltp"], r["lot_size"]
            candles = _daily_candles(r.pop("fut_token"))
            # Keep the tiered buildup already attached from the cached full-universe map;
            # only fall back to a fresh 2-candle compute if it's somehow missing.
            if not r.get("buildup"):
                r["buildup"] = _buildup_from_candles(candles)
            struct = _structure_levels(candles)
            vol_pct = round(max(3.0, r["range_pct"] * 1.5), 1)   # volatility fallback
            lv = _levels(entry, struct, bias, vol_fallback=vol_pct, lo=1.0, hi=15.0)
            per_lot_risk = round(lv["risk_per_share"] * lot)
            max_lots = int(risk // per_lot_risk) if per_lot_risk > 0 else 0
            r["plan"] = {**lv, "per_lot_risk": per_lot_risk, "max_lots": max_lots,
                         "notional_1lot": round(entry * lot), "fits": max_lots >= 1}
            return r

        constructive = sorted([r for r in rows if r["score"] > 0], key=lambda r: r["score"], reverse=True)[:top]
        weak = sorted([r for r in rows if r["score"] < 0], key=lambda r: r["score"])[:top]

        # --- Overnight OI-buildup boards (whole universe, thresholded) ---
        # A fresh buildup (OI UP) that agrees with price is the overnight signal:
        #   Long buildup  = price up + OI up  -> constructive overnight
        #   Short buildup = price down + OI up -> weak overnight
        # (Short covering / long unwinding have OI DOWN — not a fresh commitment — so
        #  they stay off these boards.) Bar to appear: OI change >= OI_NOTABLE.
        def _oichg(r: Dict[str, Any]) -> float:
            return ((r.get("buildup") or {}).get("oi_chg_pct")) or 0.0
        def _label(r: Dict[str, Any]) -> Optional[str]:
            return (r.get("buildup") or {}).get("label")

        long_pool = [r for r in rows if _label(r) == "Long buildup" and _oichg(r) >= OI_NOTABLE]
        short_pool = [r for r in rows if _label(r) == "Short buildup" and _oichg(r) >= OI_NOTABLE]
        long_pool.sort(key=lambda r: (_oichg(r), r["score"]), reverse=True)
        short_pool.sort(key=lambda r: (_oichg(r), -r["score"]), reverse=True)

        CAP = 12  # full gap-aware plans for the top CAP per side; the rest are still listed
        overnight_longs = [enrich(r, "LONG") for r in long_pool[:CAP]]
        overnight_shorts = [enrich(r, "SHORT") for r in short_pool[:CAP]]

        def _brief(r: Dict[str, Any]) -> Dict[str, Any]:
            b = r.get("buildup") or {}
            return {"symbol": r["symbol"], "pct_change": r["pct_change"], "ltp": r["ltp"],
                    "oi_chg_pct": b.get("oi_chg_pct"), "tier": b.get("tier"), "label": b.get("label")}
        overnight_longs_more = [_brief(r) for r in long_pool[CAP:]]
        overnight_shorts_more = [_brief(r) for r in short_pool[CAP:]]

        # --- Secondary "building" boards: fresh buildup UNDER the OI bar + strong close ---
        def _build_long(r: Dict[str, Any]) -> bool:
            return (_label(r) == "Long buildup" and SEC_OI_FLOOR <= _oichg(r) < OI_NOTABLE
                    and r["pct_change"] >= SEC_MOVE_MIN and r["range_pos"] >= SEC_RANGE_MIN
                    and r["vs_vwap_pct"] > 0)
        def _build_short(r: Dict[str, Any]) -> bool:
            return (_label(r) == "Short buildup" and SEC_OI_FLOOR <= _oichg(r) < OI_NOTABLE
                    and r["pct_change"] <= -SEC_MOVE_MIN and r["range_pos"] <= (1 - SEC_RANGE_MIN)
                    and r["vs_vwap_pct"] < 0)
        build_long_pool = sorted([r for r in rows if _build_long(r)], key=lambda r: r["score"], reverse=True)
        build_short_pool = sorted([r for r in rows if _build_short(r)], key=lambda r: r["score"])
        building_longs = [enrich(r, "LONG") for r in build_long_pool[:CAP]]
        building_shorts = [enrich(r, "SHORT") for r in build_short_pool[:CAP]]

        # --- Ignition board: the early-accumulation footprint (volume + OI + breakout) ---
        ign_pool: List[Dict[str, Any]] = []
        for r in rows:
            ig = _ignition(r)
            if ig and ig["score"] >= IGNITION_MIN_SCORE:
                rr = dict(r)
                rr["ignition"] = ig
                ign_pool.append(rr)
        ign_pool.sort(key=lambda r: r["ignition"]["score"], reverse=True)
        ignition = [enrich(r, r["ignition"]["bias"]) for r in ign_pool[:CAP]]

        # Anti-drop transparency: names we couldn't read OI for, and mild buildups that
        # fell just under the bar — surfaced as counts so nothing is silently gone.
        oi_unavailable = sorted(n for n in names if n in futmap and oimap.get(n) is None)
        below_long = sum(1 for r in rows if _label(r) == "Long buildup" and 0 < _oichg(r) < OI_NOTABLE)
        below_short = sum(1 for r in rows if _label(r) == "Short buildup" and 0 < _oichg(r) < OI_NOTABLE)
        now_hm = datetime.now().strftime("%H:%M")
        oi_forming = _market_open_now() and now_hm < OI_FORMING_BEFORE

        out["constructive"] = [enrich(r, "LONG") for r in constructive]
        out["weak"] = [enrich(r, "SHORT") for r in weak]
        out["overnight_longs"] = overnight_longs
        out["overnight_shorts"] = overnight_shorts
        out["overnight_longs_more"] = overnight_longs_more
        out["overnight_shorts_more"] = overnight_shorts_more
        out["building_longs"] = building_longs
        out["building_shorts"] = building_shorts
        out["ignition"] = ignition
        out.update({
            "is_live": True, "source": "Zerodha Kite live (/quote + full-universe futures OI)",
            "scanned": len(rows),
            "oi_ready": oi["ready"], "oi_ts": oi["ts"], "oi_forming": oi_forming,
            "oi_thresholds": {"noise": OI_NOISE, "notable": OI_NOTABLE, "strong": OI_STRONG},
            "oi_unavailable_count": len(oi_unavailable),
            "oi_below_threshold": {"long": below_long, "short": below_short},
        })
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(scan(top=5), indent=2, default=str))
