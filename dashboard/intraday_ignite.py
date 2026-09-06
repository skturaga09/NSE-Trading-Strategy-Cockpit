#!/usr/bin/env python3
"""
INTRADAY ignition radar — early-entry detector (separate lane; touches no existing logic).

The swing/ignition boards fire at EOD on the day's completed OI buildup — by then the
move has happened and you're chasing (KEI/POLYCAB: entered 11:15 after the fall, puts
faded). This scans the live session for the LEADING footprint of a move as it STARTS:
  - VOLUME PACE   — today's cumulative volume vs its 20-day norm, adjusted for time of
                    day (running hot early = real participation). The leading signal.
  - PRICE MOVE    — % from prev close, and closing near the day's extreme (breaking out).
  - VWAP side     — price on the trade's side of VWAP (bull above / bear below).
(Intraday OI is deliberately NOT the trigger — it's provisional and reverses at
settlement; volume + price lead, OI only confirms later on the EOD board.)

Honest stance: earlier = noisier (more false starts), so this is a HEADS-UP screen,
not advice, and every fire is logged for an early-vs-EOD outcome comparison later.
"""

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from dashboard import app as core
from dashboard.option_chain import _headers
from dashboard.fno_scanner import fno_universe, _chunk
from dashboard import swing_scan

# Thresholds (kept local — this lane has no shared config with the swing/exit logic).
VOL_PACE_MIN = 1.5     # today's volume must pace >= this x its time-of-day norm
MOVE_MIN = 1.0         # abs % move from prev close to count as a real move
MIN_SCORE = 45.0       # 0..100 composite bar to surface / alert
DAY_MINUTES = 375.0    # 09:15 -> 15:30

_DIR = Path(__file__).parent
_SEEN = _DIR / "ignite_seen.json"          # dedupe alerts per name per day
_LOG = _DIR / "logs" / "ignite_fires.jsonl"  # audit / learning: every fire


def _ist_now() -> datetime:
    """Current time in IST — the trading day (session minutes, date keys, fire timestamps)
    is defined in IST, so the whole module reads the clock through here, never the host's
    naive local time. Falls back to naive local only if zoneinfo is unavailable."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now()


def _expected_volume_fraction(now: Optional[datetime] = None) -> float:
    """Fraction of a normal day's VOLUME expected to have traded by now — NOT linear.
    NSE intraday volume is front-loaded (heavy at the open, light midday, heavy into
    the close), so a linear time-fraction hugely overstates 'pace' early. We approximate
    the cumulative-volume curve as frac**0.8 (clamped so the very open doesn't blow up).
    So vol_pace = today's cumulative volume / (avg_daily_volume * this)."""
    if now is None:
        now = _ist_now()
    mins = (now.hour * 60 + now.minute) - (9 * 60 + 15)
    frac = max(0.03, min(mins / DAY_MINUTES, 1.0))   # clamp to [~11min, full day]
    return frac ** 0.8


def _avg_daily_volume(name: str, futmap: Dict[str, Any]) -> Optional[float]:
    """20-day average daily FUTURES volume from cached daily candles. Pairs with the live
    futures volume in scan() so the pace ratio stays within one instrument (not cash/futures)."""
    fut = futmap.get(name)
    if not fut:
        return None
    c = swing_scan._daily_candles(fut["token"])
    vols = [k[5] for k in c[-21:-1] if len(k) > 5 and k[5]]
    return (sum(vols) / len(vols)) if vols else None


def _score(vol_pace: float, day_pct: float, range_pos: float, vs_vwap: float, d: int) -> float:
    vol = min(vol_pace, 4.0) / 4.0
    mv = min(abs(day_pct), 5.0) / 5.0
    close = (range_pos if d == 1 else 1 - range_pos)          # near the day's extreme
    vwap = 1.0 if (vs_vwap * d) > 0 else 0.0
    return round(100.0 * (0.40 * vol + 0.25 * mv + 0.20 * close + 0.15 * vwap), 1)


def scan() -> Dict[str, Any]:
    ts = _ist_now().strftime("%Y-%m-%d %H:%M:%S")
    out: Dict[str, Any] = {"timestamp": ts, "is_live": False, "source": "unavailable",
                           "longs": [], "shorts": [], "scanned": 0, "universe": 0,
                           "market_open": swing_scan._market_open_now()}
    kc = core.KITE_CONFIG
    if not (kc.get("api_key") and kc.get("access_token")):
        out["source"] = "Kite not connected"
        return out
    try:
        names = fno_universe()
        futmap = swing_scan._futures_map()
        out["universe"] = len(names)
        # Radar is a live-session tool. Outside market hours, skip the full-universe
        # /quote sweep entirely (the UI polls every 15s) — there's nothing intraday to
        # read, so a snapshot would be stale anyway. check_and_alert() bails the same way.
        if not out["market_open"]:
            out["source"] = "market closed — radar runs live 09:15–15:30 IST"
            return out
        exp_vol_frac = _expected_volume_fraction()
        # Volume pace is measured on the FUTURES leg (live futures volume vs its own
        # 20-day candle average) so numerator and denominator are the SAME instrument —
        # matching the swing board's rel_volume. Price / VWAP / range come from the cash
        # leg, which is the reference the CE/PE options track.
        cash_syms = [f"NSE:{n}" for n in names]
        fut_syms = [f"NFO:{futmap[n]['tradingsymbol']}" for n in names if futmap.get(n)]
        quotes: Dict[str, Any] = {}
        for grp in _chunk(cash_syms + fut_syms, 200):
            j = requests.get("https://api.kite.trade/quote", params=[("i", s) for s in grp],
                             headers=_headers(), timeout=10).json()
            if j.get("status") == "success":
                quotes.update(j["data"])

        rows: List[Dict[str, Any]] = []
        for n in names:
            d = quotes.get(f"NSE:{n}")
            if not d:
                continue
            ltp = d.get("last_price")
            ohlc = d.get("ohlc", {}) or {}
            prev_close, hi, lo = ohlc.get("close"), ohlc.get("high"), ohlc.get("low")
            vwap = d.get("average_price")
            if not (ltp and prev_close):
                continue
            # Volume pace on the futures leg: live futures volume vs its own 20-day
            # average (both from the same futures instrument — see the quote batch above).
            fut = futmap.get(n)
            fvol = (quotes.get(f"NFO:{fut['tradingsymbol']}") or {}).get("volume") if fut else None
            avgvol = _avg_daily_volume(n, futmap)
            if not fvol or not avgvol:
                continue
            vol_pace = round(fvol / (avgvol * exp_vol_frac), 2) if avgvol * exp_vol_frac else 0
            day_pct = round((ltp - prev_close) / prev_close * 100, 2)
            vs_vwap = round(((ltp - vwap) / vwap * 100), 2) if vwap else 0.0
            range_pos = round(((ltp - lo) / (hi - lo)), 2) if (hi and lo and hi > lo) else 0.5
            # direction from price + VWAP; must have a real move on hot volume
            d_ = 1 if (day_pct > 0 and (not vwap or ltp >= vwap)) else -1 if (day_pct < 0 and (not vwap or ltp <= vwap)) else 0
            if d_ == 0 or vol_pace < VOL_PACE_MIN or abs(day_pct) < MOVE_MIN:
                continue
            sc = _score(vol_pace, day_pct, range_pos, vs_vwap, d_)
            if sc < MIN_SCORE:
                continue
            rows.append({"symbol": n, "ltp": ltp, "day_pct": day_pct, "vs_vwap_pct": vs_vwap,
                         "range_pos": range_pos, "vol_pace": vol_pace, "score": sc,
                         "bias": "LONG" if d_ == 1 else "SHORT",
                         "lot_size": (futmap.get(n) or {}).get("lot_size")})
        rows.sort(key=lambda r: r["score"], reverse=True)
        out["longs"] = [r for r in rows if r["bias"] == "LONG"][:12]
        out["shorts"] = [r for r in rows if r["bias"] == "SHORT"][:12]
        out["scanned"] = sum(1 for n in names if f"NSE:{n}" in quotes)  # cash leg only
        out["is_live"] = out["market_open"]
        out["source"] = "Zerodha Kite live (/quote intraday)" if out["market_open"] else "market closed — last snapshot"
    except Exception as e:
        out["source"] = f"Kite request failed: {e}"
    return out


def _load(p: Path, default: Any) -> Any:
    try:
        if p.exists():
            return json.loads(p.read_text())
    except Exception:
        pass
    return default


def check_and_alert() -> Dict[str, Any]:
    """Background job: alert on names NEWLY igniting this session (dedup per name/day),
    log every fire for the early-vs-EOD comparison. Market hours only."""
    if not swing_scan._market_open_now():
        return {"skipped": "market closed", "alerts": 0}   # bail before any /quote calls
    r = scan()
    if not r.get("is_live"):
        return {"skipped": "market closed", "alerts": 0}
    from dashboard import exit_monitor
    seen = _load(_SEEN, {})
    today = _ist_now().strftime("%Y-%m-%d")
    if seen.get("date") != today:
        seen = {"date": today, "fired": []}
    fired = set(seen.get("fired", []))
    sent = 0
    for r_ in (r["longs"] + r["shorts"]):
        if r_["symbol"] in fired:
            continue
        arrow = "▲" if r_["bias"] == "LONG" else "▼"
        exit_monitor.notify(
            f"⚡ IGNITING {arrow} {r_['symbol']}",
            f"score {r_['score']} · vol {r_['vol_pace']}x pace · {r_['day_pct']:+}% · {'above' if r_['vs_vwap_pct']>0 else 'below'} VWAP\n"
            f"Early intraday mover ({'CALL/CE' if r_['bias']=='LONG' else 'PUT/PE'} side) — a heads-up screen, NOT advice. "
            f"Confirm the level & your rules; earlier = noisier.",
            tags=["zap"], priority=4)
        fired.add(r_["symbol"])
        _log_fire(r_, today)
        sent += 1
    seen["fired"] = sorted(fired)
    try:
        _SEEN.write_text(json.dumps(seen))
    except Exception:
        pass
    return {"alerts": sent, "igniting": len(r["longs"]) + len(r["shorts"])}


def _log_fire(r: Dict[str, Any], today: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _ist_now().strftime("%Y-%m-%d %H:%M:%S"), **r}) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    print(json.dumps(check_and_alert(), indent=2))
