#!/usr/bin/env python3
"""
Does a heavy call-OI strike act as RESISTANCE (a good upside target)? Limited validation.

The claim behind an OI-aware target: the strike with the biggest call open-interest
above spot is a wall option writers defend, so price tends to STALL there — making it
a better profit target than blind 2R geometry. This tests that premise.

DATA LIMIT (be honest): Kite drops expired option tokens and serves only DAILY option
OI, so we can look back only over the CURRENT expiry (~2 weeks) at daily resolution.
Small sample, daily not intraday — this is a directional sanity check, not a verdict.

Method, per (name, day t) where a call wall sits above spot within 1 ADR:
  wall   = strike above spot with the most call OI, needing OI ≥ 1.5× the in-window
           median (a real wall, not the max of flat OI)
  touched= next 3 days' high reaches the wall (within 0.3%)
  held   = after touching, price closes back below the wall (the wall capped it)
A CONTROL uses a random in-window strike above spot instead of the OI wall; if the OI
wall is special, its hold-rate should beat the control's.

Reuses liquidity_sweep._eq_tokens + trailing_backtest.fetch_window. Self-check: `selfcheck`.
"""

import random
import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

ADR_DAYS = 14
WINDOW_PCT = 10.0     # only consider walls within this % above spot
FWD_DAYS = 3          # forward horizon to reach/respect the wall
TOUCH_TOL = 0.003     # within 0.3% counts as "touched"
WALL_MULT = 1.5       # wall OI must be ≥ this × the in-window median call OI


def _near_expiry_calls(name: str, rows: List[Dict[str, Any]]) -> List[Tuple[float, str]]:
    """(strike, token) for the nearest-expiry CE options of `name`."""
    today = date.today().isoformat()
    ces = [r for r in rows if r.get("name") == name and r.get("instrument_type") == "CE"
           and r.get("expiry") and r["expiry"] >= today]
    if not ces:
        return []
    near = min(r["expiry"] for r in ces)
    return sorted((float(r["strike"]), r["instrument_token"]) for r in ces if r["expiry"] == near)


def _oi_by_date(token: str, headers: Dict[str, str], frm: str, to: str) -> Dict[str, float]:
    """date -> end-of-day OI for one option token."""
    try:
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": to, "oi": 1}, headers=headers, timeout=10).json()
        cs = j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        cs = []
    return {c[0][:10]: c[6] for c in cs if len(c) > 6}


def _wall(spot: float, oi_at: Dict[float, float], rng_pct: float) -> Optional[float]:
    """Strike above spot (within rng_pct%) with the most call OI, if it's ≥ WALL_MULT ×
    the in-window median (a genuine wall). Returns the strike price, else None."""
    inwin = {k: v for k, v in oi_at.items() if spot < k <= spot * (1 + rng_pct / 100) and v}
    if len(inwin) < 3:
        return None
    med = sorted(inwin.values())[len(inwin) // 2]
    top = max(inwin, key=lambda k: inwin[k])
    return top if med and inwin[top] >= WALL_MULT * med else None


def _probe(candles: List[List[Any]], i: int, wall: float) -> Optional[Tuple[bool, bool]]:
    """(touched, held) over the FWD_DAYS after bar i. held only defined when touched."""
    fwd = candles[i + 1:i + 1 + FWD_DAYS]
    if len(fwd) < FWD_DAYS:
        return None
    touched = max(c[2] for c in fwd) >= wall * (1 - TOUCH_TOL)
    held = touched and fwd[-1][4] < wall            # closed back below the wall at horizon end
    return touched, held


def run(years: float = 0.1, limit: int = 20) -> None:
    from dashboard.liquidity_sweep import _eq_tokens
    from dashboard.trailing_backtest import fetch_window, _headers
    import csv, io
    headers = _headers()
    nfo = list(csv.DictReader(io.StringIO(
        requests.get("https://api.kite.trade/instruments/NFO", headers=headers, timeout=30).text)))
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=max(30, int(years * 365)))).isoformat()
    names = sorted(_eq_tokens().items())[:limit]

    wall_t = wall_h = ctl_t = ctl_h = n = 0
    done = 0
    for name, token in names:
        calls = _near_expiry_calls(name, nfo)
        if len(calls) < 4:
            continue
        try:
            candles = fetch_window(int(token), start, end)
        except Exception:
            candles = []
        if len(candles) < ADR_DAYS + FWD_DAYS + 1:
            continue
        by_date = {c[0][:10]: c for c in candles}
        oi = {k: _oi_by_date(t, headers, start, end) for k, t in calls}   # strike -> {date: oi}
        time.sleep(0.2)
        for i in range(ADR_DAYS, len(candles) - FWD_DAYS):
            d = candles[i][0][:10]
            spot = candles[i][4]
            oi_at = {k: oi[k].get(d) for k in oi if oi[k].get(d)}
            w = _wall(spot, oi_at, WINDOW_PCT)
            if not w:
                continue
            adr = sum((candles[j][2] - candles[j][3]) for j in range(i - ADR_DAYS, i)) / ADR_DAYS
            if (w - spot) > 1.5 * adr:          # wall must be reachable (~within 1.5 ADR)
                continue
            pr = _probe(candles, i, w)
            if not pr:
                continue
            n += 1
            wall_t += pr[0]; wall_h += pr[1]
            # control: a random in-window strike above spot (not the OI max)
            cand = [k for k in oi_at if spot < k <= spot * (1 + WINDOW_PCT / 100) and abs(k - w) > 1e-9]
            if cand:
                cw = random.choice(cand)
                cp = _probe(candles, i, cw)
                if cp:
                    ctl_t += cp[0]; ctl_h += cp[1]
        done += 1
        if done % 5 == 0:
            print(f"  …{done}/{len(names)} names, {n} wall-days", file=sys.stderr)

    print(f"\nOI-wall-as-resistance test · {done} names · current expiry · DAILY · {FWD_DAYS}d fwd")
    print(f"  wall-days: {n}  (sample is tiny — one expiry, daily — directional only)")
    if n:
        print(f"  OI wall   · touched {wall_t/n*100:.0f}% · held-after-touch {wall_h/max(wall_t,1)*100:.0f}%")
        if ctl_t:
            print(f"  control   · touched {ctl_t/n*100:.0f}% · held-after-touch {ctl_h/max(ctl_t,1)*100:.0f}%")
        verdict = ("OI wall holds more than a random strike — usable as a target cap"
                   if wall_h / max(wall_t, 1) > ctl_h / max(ctl_t, 1) + 0.1
                   else "no clear edge over a random strike at this sample — treat as context only")
        print(f"  verdict: {verdict}")
    print("  (gate stays OFF; this only decides whether OI target is a real level or just a shown hint)")


def _selfcheck() -> None:
    # Flat OI except a clear wall at 110; spot 100 → wall should be 110.
    oi = {105.0: 100, 110.0: 900, 115.0: 120, 120.0: 90}
    assert _wall(100.0, oi, 30.0) == 110.0, _wall(100.0, oi, 30.0)
    # No wall when OI is flat (no strike ≥1.5× median).
    assert _wall(100.0, {105.0: 100, 110.0: 110, 115.0: 105}, 30.0) is None
    # touched & held: fwd highs reach 110 then close back below.
    cndl = [[f"d{j}", 0, 0, 0, 0, 0] for j in range(5)]
    cndl += [["t", 100, 100, 100, 100, 0], ["f1", 0, 111, 0, 108, 0], ["f2", 0, 109, 0, 107, 0], ["f3", 0, 108, 0, 105, 0]]
    assert _probe(cndl, 5, 110.0) == (True, True), _probe(cndl, 5, 110.0)
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        run(limit=int(sys.argv[1]) if len(sys.argv) > 1 else 20)
