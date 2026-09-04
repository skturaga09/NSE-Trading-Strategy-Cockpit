#!/usr/bin/env python3
"""
Backtest harness for the trailing-stop rule, across market regimes.

Purpose: BEFORE wiring any live GTT trailing, answer honestly — does a trailing stop
help, and which width is robust across CHOP / TREND / CRASH regimes? This tests the
mechanic on real underlying price data; it is deliberately decoupled from live orders.

Design (matches the original spec's requirement #10 — abstract the tick source):
  - `fetch_window()` is the ONLY data dependency; swap it for a CSV/replay to test
    offline. Everything else is pure functions over an OHLC list.
  - `trail_exit()` is the exact trailing logic the live actuator would use, so what we
    validate here is what we'd ship.

Honest limits: daily OHLC resolution (not tick), conservative same-day breach handling,
underlying (not option premium — that's a separate synthetic layer), no GTT latency.
So this measures the TRAIL WIDTH's regime-robustness, not exact live fills.
"""

import math
import statistics as st
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from dashboard import app as core

NIFTY_TOKEN = 256265
ROUND_TRIP_COST_PCT = 0.10   # modest cost assumption per trade (bps-ish, underlying)


def _headers() -> Dict[str, str]:
    kc = core.KITE_CONFIG
    return {"Authorization": f"token {kc.get('api_key','')}:{kc.get('access_token','')}",
            "X-Kite-Version": "3"}


def fetch_window(token: int, start: str, end: str) -> List[List[Any]]:
    """Daily OHLC candles [ts,o,h,l,c,vol] for [start,end]. The single data seam —
    replace with a CSV reader to run fully offline against your own dataset."""
    out: List[List[Any]] = []
    cur = date.fromisoformat(end)
    stop = date.fromisoformat(start)
    while cur > stop:
        frm = max(stop, cur - timedelta(days=380)).isoformat()
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": cur.isoformat()}, headers=_headers(), timeout=15).json()
        cs = j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
        if not cs:
            break
        out = cs + out
        cur = date.fromisoformat(cs[0][0][:10]) - timedelta(days=1)
    seen = {k[0][:10]: k for k in out if start <= k[0][:10] <= end}
    return [seen[d] for d in sorted(seen)]


def trail_exit(path: List[List[Any]], entry_idx: int, direction: int,
               entry: float, init_stop_pct: float, trail_pct: float, horizon: int
               ) -> Tuple[float, str, bool]:
    """Simulate the trailing stop from entry over up to `horizon` sessions.
    direction: +1 long, -1 short. Returns (exit_price, reason, was_ever_favorable).
    Conservative: each day we check the PRIOR stop against the day's adverse extreme
    BEFORE raising it from the day's favorable extreme (a same-day spike-and-reverse
    stops at the old level — no look-ahead optimism)."""
    if direction == 1:
        wm = entry; sl = entry * (1 - init_stop_pct / 100)
    else:
        wm = entry; sl = entry * (1 + init_stop_pct / 100)
    ever_fav = False
    end = min(entry_idx + horizon, len(path) - 1)
    for i in range(entry_idx + 1, end + 1):
        hi, lo = path[i][2], path[i][3]
        if direction == 1:
            if lo <= sl:                       # stopped (check before trailing up)
                return sl, "trail-stop", ever_fav
            if hi > wm:
                wm = hi; ever_fav = True
                sl = max(sl, wm * (1 - trail_pct / 100))
        else:
            if hi >= sl:
                return sl, "trail-stop", ever_fav
            if lo < wm:
                wm = lo; ever_fav = True
                sl = min(sl, wm * (1 + trail_pct / 100))
    return path[end][4], "horizon", ever_fav    # never stopped → exit at horizon close


def _pnl(direction: int, entry: float, exit_px: float) -> float:
    raw = (exit_px - entry) / entry * 100 * direction
    return round(raw - ROUND_TRIP_COST_PCT, 3)


def backtest_window(candles: List[List[Any]], widths: List[float], horizon: int = 5,
                    init_stop_pct: float = 4.0, mom_lookback: int = 20) -> Dict[str, Any]:
    """Generate momentum-directional trades each session (proxy for the user's signal
    direction, since we have no historical OI signals), then compare each trail width
    against a no-trail 'hold to horizon' baseline."""
    cl = [k[4] for k in candles]
    res: Dict[str, Dict[str, Any]] = {w: {"pnls": [], "whipsaws": 0} for w in widths}
    res["hold"] = {"pnls": [], "whipsaws": 0}
    n = 0
    for a in range(mom_lookback, len(candles) - horizon):
        direction = 1 if cl[a] >= cl[a - mom_lookback] else -1   # past momentum, no look-ahead
        entry = candles[a][4]
        n += 1
        # baseline: hold to horizon
        hold_px = candles[min(a + horizon, len(candles) - 1)][4]
        res["hold"]["pnls"].append(_pnl(direction, entry, hold_px))
        for w in widths:
            px, reason, fav = trail_exit(candles, a, direction, entry, init_stop_pct, w, horizon)
            p = _pnl(direction, entry, px)
            res[w]["pnls"].append(p)
            if fav and p < 0:                 # went favorable, still exited red = whipsaw
                res[w]["whipsaws"] += 1
    out: Dict[str, Any] = {"trades": n, "rows": {}}
    for key, d in res.items():
        ps = d["pnls"]
        if not ps:
            continue
        out["rows"][key] = {
            "avg_pnl": round(sum(ps) / len(ps), 2),
            "win_rate": round(sum(1 for p in ps if p > 0) / len(ps) * 100, 1),
            "total": round(sum(ps), 1),
            "whipsaw_pct": round(d["whipsaws"] / len(ps) * 100, 1) if key != "hold" else None,
        }
    return out


REGIMES = {
    "CHOP (last yr)":  ("2025-09-01", "2026-09-04"),
    "TREND (2020-21)": ("2020-10-26", "2021-01-19"),
    "CRASH (Mar-26)":  ("2025-12-15", "2026-04-15"),  # widened around the -13% Feb-Mar sell-off
}
WIDTHS = [3.0, 5.0, 8.0, 12.0]


def run() -> None:
    print(f"Trailing-stop backtest · widths {WIDTHS}% · horizon 5 sessions · cost {ROUND_TRIP_COST_PCT}%/trade")
    print("Momentum-directional entries each session (proxy for signal direction). Underlying = NIFTY.\n")
    for name, (s, e) in REGIMES.items():
        candles = fetch_window(NIFTY_TOKEN, s, e)
        if len(candles) < 30:
            print(f"{name}: not enough data ({len(candles)})"); continue
        r = backtest_window(candles, WIDTHS)
        print(f"=== {name}  ({s}→{e}, {r['trades']} trades) ===")
        print(f"   {'method':<14}{'avg P&L%':>10}{'win%':>8}{'total%':>9}{'whipsaw%':>10}")
        for key in ["hold"] + WIDTHS:
            row = r["rows"].get(key)
            if not row:
                continue
            label = "hold (no trail)" if key == "hold" else f"trail {key}%"
            ws = "" if row["whipsaw_pct"] is None else f"{row['whipsaw_pct']}"
            print(f"   {label:<14}{row['avg_pnl']:>10}{row['win_rate']:>8}{row['total']:>9}{ws:>10}")
        print()


if __name__ == "__main__":
    run()
