#!/usr/bin/env python3
"""
Overnight (close → next close) OOS backtest for the F&O screen's logic.

Answers one honest question: does picking instruments TODAY and holding for
TOMORROW's move have any out-of-sample edge? Three cross-sectional rules, ranked
across the whole F&O universe each day, long the top basket / short the bottom,
exit at the next session's close:

  momentum   — long today's biggest gainers, short the losers (the screen as-is)
  mom+room   — same, but only names that still have ADR headroom (not extended)
  reversal   — the contrarian: long today's losers, short the gainers

Signals are DAILY proxies (historical bars carry no intraday VWAP): "today's move"
= close-to-close %, and headroom = ADR(14) − today's range, exactly as the live
"room left" column computes it. Per the lab discipline: split each name's history
in half, report TRAIN vs TEST, net of a round-trip cost, and print a plain verdict.
Nothing here is wired live — it only decides whether an overnight lane is worth it.

Reuses liquidity_sweep._eq_tokens (name→NSE EQ spot token) and
trailing_backtest.fetch_window (daily candles). Self-check: `selfcheck`.
"""

import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List

MIN_SAMPLE = 30
BASKET = 10          # names per side per day
ADR_DAYS = 14
COST_PCT = 0.10      # round-trip cost per trade (brokerage+STT+impact), % — conservative for liquid stock futures


def _features(candles: List[List[Any]]) -> List[Dict[str, Any]]:
    """Per usable daily bar i: today's move, next-day return, range used, ADR(14).
    Needs ADR_DAYS of history before i and one bar after i (the exit)."""
    out: List[Dict[str, Any]] = []
    for i in range(ADR_DAYS + 1, len(candles) - 1):
        pc, c, nc = candles[i - 1][4], candles[i][4], candles[i + 1][4]
        if not pc or not c:
            continue
        ranges = [(candles[j][2] - candles[j][3]) / candles[j - 1][4] * 100
                  for j in range(i - ADR_DAYS, i) if candles[j - 1][4]]
        out.append({
            "date": candles[i][0][:10],
            "ret_today": (c / pc - 1) * 100,
            "next_ret": (nc / c - 1) * 100,
            "rng_used": (candles[i][2] - candles[i][3]) / pc * 100,
            "adr": (sum(ranges) / len(ranges)) if ranges else None,
        })
    return out


def _select(cross: List[Dict[str, Any]], rule: str, basket: int = BASKET) -> List[float]:
    """Given one day's cross-section (each item has ret_today, next_ret, rng_used, adr),
    return the sign-adjusted next-day returns of the long and short baskets for `rule`."""
    if len(cross) < 2 * basket:
        return []
    ranked = sorted(cross, key=lambda r: r["ret_today"])
    losers, gainers = ranked[:basket], ranked[-basket:]
    if rule == "momentum":
        longs, shorts = gainers, losers
    elif rule == "reversal":
        longs, shorts = losers, gainers
    elif rule == "mom+room":
        # momentum, but only names with ADR headroom left (today's range < typical range)
        has_room = [r for r in cross if r["adr"] and r["rng_used"] < r["adr"]]
        rr = sorted(has_room, key=lambda r: r["ret_today"])
        if len(rr) < 2 * basket:
            return []
        longs, shorts = rr[-basket:], rr[:basket]
    else:
        return []
    return [r["next_ret"] for r in longs] + [-r["next_ret"] for r in shorts]


def _stats(ps: List[float]) -> Dict[str, Any]:
    if not ps:
        return {"n": 0, "gross": 0.0, "net": 0.0, "win": 0.0}
    g = sum(ps) / len(ps)
    return {"n": len(ps), "gross": round(g, 3), "net": round(g - COST_PCT, 3),
            "win": round(sum(1 for x in ps if x > COST_PCT) / len(ps) * 100, 1)}


def run(years: float = 2.0, limit: int = 0) -> None:
    from dashboard.liquidity_sweep import _eq_tokens
    from dashboard.trailing_backtest import fetch_window
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=int(years * 365))).isoformat()
    names = sorted(_eq_tokens().items())
    if limit:
        names = names[:limit]

    # Build a date-indexed cross-section panel across all names.
    panel: Dict[str, List[Dict[str, Any]]] = {}
    done = 0
    for name, token in names:
        try:
            candles = fetch_window(int(token), start, end)
        except Exception:
            candles = []
        if len(candles) < ADR_DAYS + 5:
            continue
        for f in _features(candles):
            panel.setdefault(f["date"], []).append(f)
        done += 1
        time.sleep(0.3)
        if done % 25 == 0:
            print(f"  …{done}/{len(names)} names", file=sys.stderr)

    dates = sorted(panel)
    if not dates:
        print("no data — is the Kite token live?")
        return
    split = dates[len(dates) // 2]       # first half = train, second = test

    print(f"\nOvernight (close→next close) OOS · NSE F&O · {done} names · {years}yr · "
          f"basket {BASKET}/side · cost {COST_PCT}%/trade")
    print(f"  split at {split} · train {dates[0]}→{split} · test {split}→{dates[-1]}")
    print(f"  {'rule':<12}{'half':<7}{'trades':>8}{'gross%':>8}{'net%':>8}{'win%':>8}  verdict")
    base = _stats([r["next_ret"] for d in dates for r in panel[d]])  # all names: market drift reference
    print(f"  {'(baseline)':<12}{'all':<7}{base['n']:>8}{base['gross']:>8}{'':>8}{'':>8}  avg next-day return of every name")

    for rule in ("momentum", "mom+room", "reversal"):
        train, test = [], []
        for d in dates:
            (train if d < split else test).extend(_select(panel[d], rule))
        tr, te = _stats(train), _stats(test)
        if te["n"] < MIN_SAMPLE:
            verdict = f"accumulating (test n={te['n']})"
        elif te["net"] > 0 and tr["net"] > 0 and te["win"] >= 50:
            verdict = "EDGE out-of-sample — worth a live lane (still gate it)"
        else:
            verdict = "no edge net of cost"
        for label, st in (("train", tr), ("test", te)):
            print(f"  {rule:<12}{label:<7}{st['n']:>8}{st['gross']:>8}{st['net']:>8}{st['win']:>8}"
                  f"{'  ' + verdict if label == 'test' else ''}")
    print("  (verdict reads the TEST half net of cost; gate stays OFF regardless)")
    print("  caveat: universe = today's F&O names over 2yr (survivorship-biased → edge overstated, so 'no edge' is conservative)")


def _selfcheck() -> None:
    # One day, 3 names. Gainer +5%, flat 0%, loser -5%; gainer then +1% next day, loser +3%.
    cross = [
        {"ret_today": 5.0, "next_ret": 1.0, "rng_used": 1.0, "adr": 3.0},   # gainer
        {"ret_today": 0.0, "next_ret": 2.0, "rng_used": 1.0, "adr": 3.0},   # flat
        {"ret_today": -5.0, "next_ret": 3.0, "rng_used": 1.0, "adr": 3.0},  # loser
    ]
    mom = _select(cross, "momentum", basket=1)   # long gainer (+1), short loser (-3) → [1, -3]
    rev = _select(cross, "reversal", basket=1)   # long loser (+3), short gainer (-1) → [3, -1]
    assert mom == [1.0, -3.0], mom
    assert rev == [3.0, -1.0], rev
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        run(limit=int(sys.argv[1]) if len(sys.argv) > 1 else 0)
