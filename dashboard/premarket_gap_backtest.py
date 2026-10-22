#!/usr/bin/env python3
"""
Does the premarket gap predict a BIG-MOVE day? OOS validation on daily F&O history.

A day's `open` is the NSE pre-open auction result, so (open − prev_close) IS the
premarket gap we'd see at 09:08 — meaning we can test the whole idea on 2 years of
daily candles before building any live pre-open screen.

Two separate questions, answered separately (conflating them loses money):
  MAGNITUDE  — do big-gap days have a bigger realised range than normal days?
               (i.e. does the gap flag "this name will MOVE a lot today?")
  DIRECTION  — on gap days, does price continue the gap (gap-and-go) or fade it
               (gap-fill)? Entry at open in the gap direction, exit at close, net cost.

Per the lab discipline: split each name's history in half, report TRAIN vs TEST.
Nothing wired live — this only decides whether a premarket radar is worth building.
Reuses liquidity_sweep._eq_tokens + trailing_backtest.fetch_window. Self-check: `selfcheck`.
"""

import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List

ADR_DAYS = 14
GAP_MIN = 1.0        # |gap%| at/above this counts as a "big gap"
COST_PCT = 0.10      # round-trip cost for the direction trade, %


def _features(candles: List[List[Any]]) -> List[Dict[str, Any]]:
    """Per daily bar i: gap%, realised range%, open→close continuation%, trailing ADR%."""
    out: List[Dict[str, Any]] = []
    for i in range(ADR_DAYS + 1, len(candles)):
        o, h, l, c = candles[i][1], candles[i][2], candles[i][3], candles[i][4]
        pc = candles[i - 1][4]
        if not pc or not o:
            continue
        ranges = [(candles[j][2] - candles[j][3]) / candles[j - 1][4] * 100
                  for j in range(i - ADR_DAYS, i) if candles[j - 1][4]]
        out.append({
            "date": candles[i][0][:10],
            "gap": (o - pc) / pc * 100,
            "rng": (h - l) / o * 100,
            "cont": (c - o) / o * 100,            # same sign as gap = continuation
            "adr": (sum(ranges) / len(ranges)) if ranges else None,
        })
    return out


def _agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Magnitude + direction stats for one half (train or test)."""
    if not rows:
        return {"n": 0}
    big = [r for r in rows if abs(r["gap"]) >= GAP_MIN and r["adr"]]
    all_rng = sum(r["rng"] for r in rows) / len(rows)
    out = {"n": len(rows), "all_rng": round(all_rng, 2), "big_n": len(big)}
    if big:
        out["big_rng"] = round(sum(r["rng"] for r in big) / len(big), 2)
        out["big_vs_adr"] = round(sum(r["rng"] / r["adr"] for r in big) / len(big), 2)  # ×typical range
        out["rng_lift"] = round(out["big_rng"] / all_rng, 2) if all_rng else None        # big-gap range ÷ all-day range
        dir_ps = [(1 if r["gap"] > 0 else -1) * r["cont"] for r in big]                   # follow the gap
        out["dir_gross"] = round(sum(dir_ps) / len(dir_ps), 3)
        out["dir_net"] = round(out["dir_gross"] - COST_PCT, 3)
        out["dir_win"] = round(sum(1 for x in dir_ps if x > COST_PCT) / len(dir_ps) * 100, 1)
    return out


def run(years: float = 2.0, limit: int = 0) -> None:
    from dashboard.liquidity_sweep import _eq_tokens
    from dashboard.trailing_backtest import fetch_window
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=int(years * 365))).isoformat()
    names = sorted(_eq_tokens().items())
    if limit:
        names = names[:limit]

    rows: List[Dict[str, Any]] = []
    done = 0
    for name, token in names:
        try:
            candles = fetch_window(int(token), start, end)
        except Exception:
            candles = []
        if len(candles) < ADR_DAYS + 5:
            continue
        rows.extend(_features(candles))
        done += 1
        time.sleep(0.3)
        if done % 25 == 0:
            print(f"  …{done}/{len(names)} names", file=sys.stderr)

    if not rows:
        print("no data — is the Kite token live?")
        return
    dates = sorted({r["date"] for r in rows})
    split = dates[len(dates) // 2]
    tr = _agg([r for r in rows if r["date"] < split])
    te = _agg([r for r in rows if r["date"] >= split])

    print(f"\nPremarket-gap big-move test · NSE F&O · {done} names · {years}yr · "
          f"big gap = |gap|≥{GAP_MIN}% · dir cost {COST_PCT}%")
    print(f"  split at {split}")
    print(f"  {'half':<7}{'big days':>9}{'all rng%':>10}{'big rng%':>10}{'×ADR':>7}{'lift':>7}"
          f"{'dir net%':>10}{'dir win%':>10}")
    for label, a in (("train", tr), ("test", te)):
        if a["n"] and a.get("big_n"):
            print(f"  {label:<7}{a['big_n']:>9}{a['all_rng']:>10}{a['big_rng']:>10}{a['big_vs_adr']:>7}"
                  f"{a['rng_lift']:>7}{a['dir_net']:>10}{a['dir_win']:>10}")

    # Verdicts read the TEST half.
    mag = "YES — big gaps flag big-range days" if te.get("rng_lift", 0) and te["rng_lift"] >= 1.3 \
          else "weak — big-gap days are barely wider than normal"
    if te.get("dir_net", -9) > 0 and te.get("dir_win", 0) >= 50:
        dir_v = "continuation edge (gap-and-go) net of cost"
    elif te.get("dir_net", 9) < 0 and te.get("dir_gross", 0) < 0:
        dir_v = "fade edge likely (gaps tend to FILL) — gap-and-go LOSES"
    else:
        dir_v = "no directional edge net of cost"
    print(f"  MAGNITUDE verdict: {mag}")
    print(f"  DIRECTION verdict: {dir_v}")
    print("  (magnitude = 'will it move'; direction = 'which way' — only the 2nd makes money alone)")


def _selfcheck() -> None:
    # 16 flat days then a +2% gap day that ranges 3% and closes +1% from open.
    base = [[f"d{i}", 100, 101, 99, 100, 0] for i in range(16)]
    gapday = ["d16", 102.0, 103.0, 100.0, 103.0, 0]   # prev close 100 → gap +2%, range 3/102, cont +1/102
    feats = _features(base + [gapday])
    g = feats[-1]
    assert round(g["gap"], 2) == 2.0, g["gap"]
    assert round(g["cont"], 2) == 0.98, g["cont"]      # (103-102)/102*100
    a = _agg(feats)
    assert a["big_n"] == 1 and a["dir_gross"] == round(0.98, 3), a
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        run(limit=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
