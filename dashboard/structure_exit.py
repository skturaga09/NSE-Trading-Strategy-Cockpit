#!/usr/bin/env python3
"""
Underlying-structure exits — Phase 2a: FULL exit on a market-structure break.

The premium floors (exit_monitor) stay the hard safety net; this reads the UNDERLYING's
daily price structure and fires a full exit when the trend structure breaks:
  - a LONG option (CALL) exits when the stock CLOSES below its last confirmed swing low
    (the "higher low" that was holding the uptrend);
  - a PUT exits when the stock CLOSES above its last confirmed swing high.

Close-based and confirmation-delayed — a fractal pivot needs `k` bars on each side, so we
only ever act on CONFIRMED pivots (never the forming bar) → no intrabar or look-ahead
whipsaw. `signal()` is pure over an OHLC list [ts,o,h,l,c,...] so it is unit-testable and
backtestable with zero live deps (same discipline as trailing_backtest.trail_exit);
`position_signal()` is the thin live wrapper exit_monitor calls.

Phase 2a scope (by design): daily timeframe only (swing/positional), higher-low/lower-high
break only, full exit only. EMA/ATR trails, intraday timeframe, partial scaling and
R-multiples are later phases — see docs/exit-structure-spec.md.
"""

import re
from typing import Any, Dict, List, Optional

# Monthly stock-option tradingsymbol → underlying / strike / CE|PE  (e.g. ADANIGREEN26SEP1300CE)
_SYM = re.compile(r"^(?P<u>[A-Z&]+?)(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<strike>\d+)(?P<t>CE|PE)$")


def last_confirmed_pivot(candles: List[List[Any]], k: int, kind: str) -> Optional[float]:
    """Price of the MOST RECENT confirmed fractal pivot. kind='low' → a bar whose low is the
    lowest of the ±k window (a swing low); 'high' → the highest (a swing high). Only indices
    in [k, len-1-k] can be confirmed (need k bars after them), so the forming bars never
    count — no look-ahead."""
    n = len(candles)
    if n < 2 * k + 1:
        return None
    found: Optional[float] = None
    for i in range(k, n - k):
        win = candles[i - k:i + k + 1]
        if kind == "low":
            lo = candles[i][3]
            if lo == min(c[3] for c in win):
                found = lo
        else:
            hi = candles[i][2]
            if hi == max(c[2] for c in win):
                found = hi
    return found


def signal(candles: List[List[Any]], side: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Pure structure-break check. side: 'LONG' (call) or 'SHORT' (put).
    Returns {action: 'EXIT'|'HOLD', reason, level}."""
    k = int(cfg.get("structure_pivot_k", 2))
    hold = {"action": "HOLD", "reason": "", "level": None}
    if len(candles) < 2 * k + 3:
        return hold
    close = candles[-1][4]
    if side == "LONG":
        lvl = last_confirmed_pivot(candles, k, "low")
        if lvl is not None:
            hold["level"] = round(lvl, 1)
            if close < lvl:
                return {"action": "EXIT", "level": round(lvl, 1),
                        "reason": f"closed {round(close,1)} below last swing-low {round(lvl,1)} — uptrend structure broke"}
    else:
        lvl = last_confirmed_pivot(candles, k, "high")
        if lvl is not None:
            hold["level"] = round(lvl, 1)
            if close > lvl:
                return {"action": "EXIT", "level": round(lvl, 1),
                        "reason": f"closed {round(close,1)} above last swing-high {round(lvl,1)} — downtrend structure broke"}
    return hold


def position_signal(symbol: str, product: Optional[str], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Live wrapper for exit_monitor: parse the option symbol, pull the underlying's daily
    candles, and return the structure signal ONLY when it's a full EXIT (else None). Daily
    timeframe only — MIS (intraday) is deferred to Phase 2b."""
    if not cfg.get("structure_exits", True):
        return None
    if (product or "").upper() == "MIS":          # intraday timeframe not handled in 2a
        return None
    m = _SYM.match(symbol or "")
    if not m:
        return None
    side = "LONG" if m.group("t") == "CE" else "SHORT"
    from dashboard import swing_scan               # lazy: avoids any import cycle
    fut = swing_scan._futures_map().get(m.group("u"))
    if not fut:
        return None
    candles = swing_scan._daily_candles(fut["token"])   # warm daily cache — no new cost
    if not candles or len(candles) < 5:
        return None
    s = signal(candles, side, cfg)
    return s if s["action"] == "EXIT" else None


# --------------------------------------------------------------------------------------
# Backtest — validate the higher-low-break trigger's regime-robustness before leaning on it.
# Holds until the structure breaks (or a max horizon), so it should ride trends and cut chop.
# --------------------------------------------------------------------------------------
def _bt_trade(candles: List[List[Any]], a: int, direction: int, k: int, max_h: int):
    entry = candles[a][4]
    side = "LONG" if direction == 1 else "SHORT"
    for i in range(a + 1, min(a + max_h, len(candles) - 1) + 1):
        if signal(candles[:i + 1], side, {"structure_pivot_k": k})["action"] == "EXIT":
            return (candles[i][4] - entry) / entry * 100 * direction, i - a
    end = min(a + max_h, len(candles) - 1)
    return (candles[end][4] - entry) / entry * 100 * direction, end - a


def run() -> None:
    from dashboard.trailing_backtest import fetch_window, NIFTY_TOKEN, REGIMES
    K, MAX_H, MOM = 2, 20, 20
    print(f"Structure-exit backtest · higher-low break · pivot k={K} · max hold {MAX_H} sessions · underlying=NIFTY")
    print("Momentum-directional entries; exit when close breaks the last confirmed swing. vs hold-to-max.\n")
    for name, (s, e) in REGIMES.items():
        candles = fetch_window(NIFTY_TOKEN, s, e)
        if len(candles) < 30:
            print(f"{name}: not enough data ({len(candles)})\n"); continue
        cl = [c[4] for c in candles]
        struct_p, struct_bars, hold_p = [], [], []
        for a in range(MOM, len(candles) - MAX_H):
            d = 1 if cl[a] >= cl[a - MOM] else -1
            p, bars = _bt_trade(candles, a, d, K, MAX_H)
            struct_p.append(p); struct_bars.append(bars)
            end = min(a + MAX_H, len(candles) - 1)
            hold_p.append((candles[end][4] - candles[a][4]) / candles[a][4] * 100 * d)
        def stats(ps):
            return (round(sum(ps) / len(ps), 2), round(sum(1 for x in ps if x > 0) / len(ps) * 100, 1), round(sum(ps), 1))
        sa, sw, stot = stats(struct_p); ha, hw, htot = stats(hold_p)
        print(f"=== {name}  ({s}→{e}, {len(struct_p)} trades) ===")
        print(f"   {'policy':<20}{'avg%':>8}{'win%':>8}{'total%':>9}{'avg bars':>10}")
        print(f"   {'structure exit':<20}{sa:>8}{sw:>8}{stot:>9}{round(sum(struct_bars)/len(struct_bars),1):>10}")
        print(f"   {'hold to '+str(MAX_H):<20}{ha:>8}{hw:>8}{htot:>9}{MAX_H:>10}")
        print()


if __name__ == "__main__":
    run()
