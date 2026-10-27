#!/usr/bin/env python3
"""
Does CONFLUENCE make a clear indication? The regime + trend + un-chased filter, OOS.

The lab's long-standing untested lever: momentum entries are ~breakeven overall, but
maybe they only pay when you (a) take them WITH the 50-DMA trend, (b) aren't already
chasing an exhausted move, and (c) are in a healthy-breadth regime. This tests exactly
that — the filter the dashboard's screens imply but never proved.

Base candidate = a daily MOVER (|today's close-to-close| ≥ MOVE_MIN%), direction = the
move's sign (what the radar surfaces). Outcome = H-day forward return in that direction,
net of cost. Cohorts: base, +trend, +un-chased, +regime, and ALL three. If ALL beats
base out-of-sample and is positive, confluence IS the indication; if not, it's hygiene.

Breadth is market-wide: the fraction of the universe above its 50-DMA that day, computed
from the same panel (no extra calls). Reuses liquidity_sweep._eq_tokens +
trailing_backtest.fetch_window. Self-check: `selfcheck`.
"""

import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List

MOVE_MIN = 2.0       # a "mover" — what shows up on the radar
H = 5                # swing hold horizon (trading days)
ADR_DAYS = 14
DMA = 50
COST_PCT = 0.10      # swing round-trip cost, %
MIN_SAMPLE = 30


def _cohorts(d: int, above: bool, range_used: float, adr: float, breadth_up: float) -> Dict[str, bool]:
    """Which filters a candidate passes. d=+1 long (up move), -1 short (down move)."""
    trend = (d == 1 and above) or (d == -1 and not above)         # with the 50-DMA
    unchased = range_used < adr                                   # room left (not exhausted)
    regime = (d == 1 and breadth_up > 0.5) or (d == -1 and breadth_up < 0.5)  # breadth supports it
    return {"base": True, "trend": trend, "unchased": unchased, "regime": regime,
            "all": trend and unchased and regime}


def _features(candles: List[List[Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    closes = [c[4] for c in candles]
    for i in range(DMA, len(candles) - H):
        pc = candles[i - 1][4]
        c = candles[i][4]
        if not pc or not c:
            continue
        dma = sum(closes[i - DMA + 1:i + 1]) / DMA
        ranges = [(candles[j][2] - candles[j][3]) / candles[j - 1][4] * 100
                  for j in range(i - ADR_DAYS, i) if candles[j - 1][4]]
        out.append({
            "date": candles[i][0][:10],
            "ret_today": (c / pc - 1) * 100,
            "fwd": (candles[i + H][4] / c - 1) * 100,
            "above": c >= dma,
            "range_used": (candles[i][2] - candles[i][3]) / pc * 100,
            "adr": (sum(ranges) / len(ranges)) if ranges else None,
        })
    return out


def _stat(ps: List[float]) -> Dict[str, Any]:
    if not ps:
        return {"n": 0, "avg": 0.0, "net": 0.0, "win": 0.0}
    a = sum(ps) / len(ps)
    return {"n": len(ps), "avg": round(a, 2), "net": round(a - COST_PCT, 2),
            "win": round(sum(1 for x in ps if x > COST_PCT) / len(ps) * 100, 1)}


def run(years: float = 2.0, limit: int = 0) -> None:
    from dashboard.liquidity_sweep import _eq_tokens
    from dashboard.trailing_backtest import fetch_window
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=int(years * 365))).isoformat()
    names = sorted(_eq_tokens().items())
    if limit:
        names = names[:limit]

    panel: List[Dict[str, Any]] = []
    done = 0
    for name, token in names:
        try:
            candles = fetch_window(int(token), start, end)
        except Exception:
            candles = []
        if len(candles) < DMA + H + 1:
            continue
        panel.extend(_features(candles))
        done += 1
        time.sleep(0.3)
        if done % 25 == 0:
            print(f"  …{done}/{len(names)} names", file=sys.stderr)

    if not panel:
        print("no data — is the Kite token live?")
        return
    # Market breadth per day: fraction of the universe above its 50-DMA.
    by_date: Dict[str, List[bool]] = {}
    for r in panel:
        by_date.setdefault(r["date"], []).append(r["above"])
    breadth = {d: sum(v) / len(v) for d, v in by_date.items()}

    dates = sorted({r["date"] for r in panel})
    split = dates[len(dates) // 2]
    cohorts = ["base", "trend", "unchased", "regime", "all"]
    buckets = {c: {"train": [], "test": []} for c in cohorts}
    for r in panel:
        if abs(r["ret_today"]) < MOVE_MIN or r["adr"] is None:
            continue
        d = 1 if r["ret_today"] > 0 else -1
        passes = _cohorts(d, r["above"], r["range_used"], r["adr"], breadth[r["date"]])
        dir_fwd = r["fwd"] * d
        half = "train" if r["date"] < split else "test"
        for c in cohorts:
            if passes[c]:
                buckets[c][half].append(dir_fwd)

    print(f"\nConfluence filter OOS · NSE F&O · {done} names · {years}yr · mover≥{MOVE_MIN}% · "
          f"hold {H}d · cost {COST_PCT}% · split {split}")
    print(f"  {'cohort':<10}{'half':<7}{'trades':>8}{'avg%':>8}{'net%':>8}{'win%':>8}")
    base_test_net = None
    for c in cohorts:
        for half in ("train", "test"):
            s = _stat(buckets[c][half])
            print(f"  {c:<10}{half:<7}{s['n']:>8}{s['avg']:>8}{s['net']:>8}{s['win']:>8}")
        if c == "base":
            base_test_net = _stat(buckets["base"]["test"])["net"]
    at = _stat(buckets["all"]["test"])
    if at["n"] < MIN_SAMPLE:
        verdict = f"inconclusive — ALL test n={at['n']} < {MIN_SAMPLE}"
    elif at["net"] > 0 and at["net"] > (base_test_net or -9) and at["win"] >= 50:
        verdict = "CONFLUENCE ADDS EDGE out-of-sample — the filter is a real indication (build the GO tier on it)"
    else:
        verdict = "no edge — confluence is discipline/hygiene, NOT a validated GO signal"
    print(f"  verdict: {verdict}")
    print("  (reads the ALL cohort's TEST half, net of cost, vs base)")


def _selfcheck() -> None:
    # long move, above DMA, has room, healthy breadth → passes everything
    assert _cohorts(1, True, 1.0, 3.0, 0.7) == {"base": True, "trend": True, "unchased": True, "regime": True, "all": True}
    # long move but BELOW dma (counter-trend) → fails trend and all
    c = _cohorts(1, False, 1.0, 3.0, 0.7)
    assert c["trend"] is False and c["all"] is False, c
    # long move, exhausted (range_used>adr) → fails unchased
    assert _cohorts(1, True, 4.0, 3.0, 0.7)["unchased"] is False
    # short move in a bullish-breadth tape → regime unsupportive
    assert _cohorts(-1, False, 1.0, 3.0, 0.7)["regime"] is False
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        run(limit=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
