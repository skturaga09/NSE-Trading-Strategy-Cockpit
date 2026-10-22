#!/usr/bin/env python3
"""
Liquidity-sweep detector + out-of-sample validation (daily, NSE F&O).

A "liquidity sweep" (a.k.a. stop-hunt / ICT liquidity grab) is the one concrete,
falsifiable primitive under the Price-Action / Supply-Demand / ICT / Smart-Money
umbrella: price pierces BELOW a prior confirmed swing-low (tripping resting stops),
then CLOSES back above it — a failed breakdown that often reverses up. Mirror for a
swept swing-high → short.

`sweep_signal()` is pure over an OHLC list [ts,o,h,l,c,...] (same discipline as
structure_exit.signal) so it is unit-testable and backtestable with zero live deps.
It reuses structure_exit.last_confirmed_pivot (the swept level) and _atr (pierce
depth), so there is no new pivot/ATR code here.

NOT wired to the live radar. This is the validation gate first: `run()` walks the
whole F&O futures universe over daily candles, splits each name in half (train vs
test), and reports whether a swept reversal actually follows through out-of-sample.
It earns a radar input only if the TEST half shows edge (verdict printed below) —
same OOS discipline as the MCX setup lane. Until then: gate OFF.
"""

import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List

from dashboard.structure_exit import last_confirmed_pivot, _atr

MIN_SAMPLE = 30   # fewer trades than this → "accumulating", no verdict (matches swing_journal)


def sweep_signal(candles: List[List[Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Pure sweep check on the LATEST bar. Returns
    {action:'SWEEP'|'HOLD', side:'LONG'|'SHORT'|None, level, stop, reason}.
    The swept pivot is taken from candles[:-1] so the latest bar can never be the
    pivot itself — no look-ahead, and the pivot is at least `k` bars old."""
    k = int(cfg.get("sweep_pivot_k", 2))
    buf = float(cfg.get("sweep_buffer_atr", 0.0))   # min pierce depth, in ATR units
    hold = {"action": "HOLD", "side": None, "level": None, "stop": None, "reason": ""}
    if len(candles) < 2 * k + 4:
        return hold
    prior = candles[:-1]
    last = candles[-1]
    lo, hi, close = last[3], last[2], last[4]
    a = _atr(prior) or 0.0
    swing_lo = last_confirmed_pivot(prior, k, "low")
    swing_hi = last_confirmed_pivot(prior, k, "high")
    if swing_lo is not None and lo < swing_lo - buf * a and close > swing_lo:
        return {"action": "SWEEP", "side": "LONG", "level": round(swing_lo, 2), "stop": round(lo, 2),
                "reason": f"swept swing-low {round(swing_lo,2)} (to {round(lo,2)}), closed back above at {round(close,2)}"}
    if swing_hi is not None and hi > swing_hi + buf * a and close < swing_hi:
        return {"action": "SWEEP", "side": "SHORT", "level": round(swing_hi, 2), "stop": round(hi, 2),
                "reason": f"swept swing-high {round(swing_hi,2)} (to {round(hi,2)}), closed back below at {round(close,2)}"}
    return hold


def _bt_trades(candles: List[List[Any]], cfg: Dict[str, Any], lo: int, hi: int) -> List[float]:
    """Simulate non-overlapping sweep trades with entries in bar range [lo, hi].
    Enter at the sweep bar's close; stop when a later close moves back BEYOND the
    sweep extreme (the reversal failed); otherwise exit at close after max_hold.
    Returns per-trade % returns (sign-adjusted for side)."""
    H = int(cfg.get("sweep_max_hold", 10))
    trades: List[float] = []
    i = max(2 * int(cfg.get("sweep_pivot_k", 2)) + 4, lo)
    while i <= hi and i < len(candles) - 1:
        sig = sweep_signal(candles[:i + 1], cfg)
        if sig["action"] != "SWEEP":
            i += 1
            continue
        d = 1 if sig["side"] == "LONG" else -1
        entry, stop = candles[i][4], sig["stop"]
        j_end = min(i + H, len(candles) - 1)
        for j in range(i + 1, min(i + H, len(candles) - 1) + 1):
            c = candles[j][4]
            if (d == 1 and c < stop) or (d == -1 and c > stop):
                j_end = j
                break
        trades.append((candles[j_end][4] - entry) / entry * 100 * d)
        i = j_end + 1          # no overlapping trades
    return trades


def _stats(ps: List[float]) -> Dict[str, Any]:
    if not ps:
        return {"n": 0, "avg": 0.0, "win": 0.0, "total": 0.0}
    return {"n": len(ps), "avg": round(sum(ps) / len(ps), 2),
            "win": round(sum(1 for x in ps if x > 0) / len(ps) * 100, 1),
            "total": round(sum(ps), 1)}


def _eq_tokens() -> Dict[str, str]:
    """F&O name → NSE EQ (spot) instrument_token. The structure lives in the underlying's
    CONTINUOUS spot series — the nearest-expiry monthly future has only weeks of history, so
    it is useless for a multi-year backtest. Indices (NIFTY etc.) have no EQ row and drop out."""
    import csv, io, requests
    from dashboard.swing_scan import _futures_map, _headers
    txt = requests.get("https://api.kite.trade/instruments/NSE", headers=_headers(), timeout=30).text
    eq = {r["tradingsymbol"]: r["instrument_token"]
          for r in csv.DictReader(io.StringIO(txt)) if r.get("instrument_type") == "EQ"}
    return {n: eq[n] for n in _futures_map() if n in eq}


def run(years: float = 2.0, limit: int = 0, cfg: Dict[str, Any] | None = None) -> None:
    """Walk the F&O universe (by underlying spot); per name split candles in half (train vs
    test), aggregate sweep trades across names, and print a train/test comparison + verdict.
    `limit` caps the number of names (0 = all). Needs a live Kite token."""
    from dashboard.trailing_backtest import fetch_window
    cfg = cfg or {}
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=int(years * 365))).isoformat()
    names = sorted(_eq_tokens().items())
    if limit:
        names = names[:limit]
    train: List[float] = []
    test: List[float] = []
    done = 0
    for name, token in names:
        try:
            candles = fetch_window(int(token), start, end)
        except Exception:
            candles = []
        if len(candles) < 60:
            continue
        mid = len(candles) // 2
        train += _bt_trades(candles, cfg, 0, mid - 1)
        test += _bt_trades(candles, cfg, mid, len(candles) - 1)
        done += 1
        time.sleep(0.3)        # stay under Kite's historical rate limit
        if done % 25 == 0:
            print(f"  …{done}/{len(names)} names", file=sys.stderr)

    tr, te = _stats(train), _stats(test)
    print(f"\nLiquidity-sweep OOS validation · daily · NSE F&O · {done} names · {years}yr "
          f"· pivot k={cfg.get('sweep_pivot_k', 2)} · max hold {cfg.get('sweep_max_hold', 10)}")
    print(f"  {'half':<8}{'trades':>8}{'avg%':>8}{'win%':>8}{'total%':>9}")
    for label, st in (("train", tr), ("test", te)):
        print(f"  {label:<8}{st['n']:>8}{st['avg']:>8}{st['win']:>8}{st['total']:>9}")

    # Verdict from the TEST half only — the honest readout (train is where overfit hides).
    if te["n"] < MIN_SAMPLE:
        verdict = f"accumulating (test n={te['n']} < {MIN_SAMPLE}) — no verdict yet"
    elif te["avg"] > 0 and te["win"] >= 50 and tr["avg"] > 0:
        verdict = "EDGE out-of-sample — candidate for a radar input (still gate it)"
    else:
        verdict = "no edge out-of-sample — do NOT wire to the radar"
    print(f"  verdict: {verdict}\n  (gate stays OFF regardless — this only decides whether to build the next slice)")


def _selfcheck() -> None:
    """Assert the detector fires on a crafted sweep and holds otherwise."""
    # 9 bars: a clean swing-low at idx 3 (low=90), then bar 8 pierces to 88 and closes back at 97.
    def bar(o, h, l, c):
        return [0, o, h, l, c, 1000]
    base = [bar(100, 101, 99, 100), bar(100, 100, 95, 96), bar(96, 97, 92, 93),
            bar(93, 94, 90, 91), bar(91, 95, 91, 94), bar(94, 98, 93, 97),
            bar(97, 99, 96, 98), bar(98, 100, 97, 99)]
    cfg = {"sweep_pivot_k": 2}
    assert sweep_signal(base + [bar(99, 99, 88, 97)], cfg)["side"] == "LONG", "should detect bullish sweep"
    assert sweep_signal(base + [bar(99, 100, 97, 99)], cfg)["action"] == "HOLD", "no pierce → HOLD"
    assert sweep_signal(base + [bar(99, 99, 88, 89)], cfg)["action"] == "HOLD", "pierced but closed below → HOLD"
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        lim = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        run(limit=lim)
