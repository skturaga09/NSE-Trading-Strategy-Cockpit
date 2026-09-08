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
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

# Monthly stock-option tradingsymbol → underlying / strike / CE|PE  (e.g. ADANIGREEN26SEP1300CE)
_SYM = re.compile(r"^(?P<u>[A-Z&]+?)(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<strike>\d+)(?P<t>CE|PE)$")

# Phase 2b — intraday candle seam. MIS trades read INTRADAY structure (default 15-min)
# instead of daily. Kite's forming intraday bar changes constantly, so cache per
# (token, interval) with a short TTL to avoid hammering /historical on every 3s poll.
_INTRA_CACHE: Dict[tuple, Any] = {}
_INTRA_TTL_SEC = 300.0     # 5 min — a 15-min bar closes every 15 min, so this is plenty


def fetch_intraday(token: str, interval: str = "15minute", lookback_days: int = 8) -> List[List[Any]]:
    """Recent intraday OHLC candles for a token (the single intraday data seam; swap for a
    replay to test offline). Cached per (token, interval) for _INTRA_TTL_SEC."""
    import requests
    from dashboard import app as core
    key = (token, interval)
    hit = _INTRA_CACHE.get(key)
    if hit and (time.time() - hit[0]) < _INTRA_TTL_SEC:
        return hit[1]
    kc = core.KITE_CONFIG
    headers = {"Authorization": f"token {kc.get('api_key','')}:{kc.get('access_token','')}",
               "X-Kite-Version": "3"}
    frm = (date.today() - timedelta(days=lookback_days)).isoformat()
    to = date.today().isoformat()
    candles: List[List[Any]] = []
    try:
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/{interval}",
                         params={"from": frm, "to": to}, headers=headers, timeout=10).json()
        if j.get("status") == "success":
            candles = j.get("data", {}).get("candles", []) or []
    except Exception:
        candles = []
    if candles:
        _INTRA_CACHE[key] = (time.time(), candles)
    return candles


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


def _rsi(closes: List[float], n: int = 14) -> Optional[float]:
    """Wilder RSI over the given closes (latest value)."""
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0); losses += max(-d, 0.0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
    if al == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + ag / al), 1)


def confirmations(candles: List[List[Any]], side: str, cfg: Dict[str, Any]) -> List[str]:
    """Secondary weakening signals — NEVER an exit on their own (per the design principle),
    only used to annotate a structure exit or drive an optional heads-up. Two robust ones:
      - RSI rollover: RSI(14) reached an extreme in the last few bars and has turned back
        (a momentum rollover, not the naive 'RSI>70 → sell').
      - Volume climax: an above-average-volume REJECTION bar against the position's side.
    """
    flags: List[str] = []
    closes = [c[4] for c in candles]
    n = int(cfg.get("rsi_period", 14))
    ob = float(cfg.get("rsi_overbought", 70)); os_ = float(cfg.get("rsi_oversold", 30))
    if len(closes) >= n + 4:
        series = [_rsi(closes[: len(closes) - j], n) for j in range(0, 3)]  # latest, -1, -2
        series = [s for s in series if s is not None]
        if len(series) >= 2:
            latest, prev = series[0], series[1]
            recent = series[:3]
            if side == "LONG" and max(recent) >= ob and latest < prev:
                flags.append(f"RSI rolled over from overbought ({max(recent):.0f}→{latest:.0f})")
            if side == "SHORT" and min(recent) <= os_ and latest > prev:
                flags.append(f"RSI rolled up from oversold ({min(recent):.0f}→{latest:.0f})")
    # Volume climax: latest bar's volume vs the prior 20-bar average, with a rejection close.
    vols = [c[5] for c in candles if len(c) > 5 and c[5]]
    if len(vols) >= 6:
        base = vols[-21:-1] if len(vols) >= 21 else vols[:-1]
        avg = (sum(base) / len(base)) if base else 0
        last = candles[-1]
        o, h, l, c_, v = last[1], last[2], last[3], last[4], (last[5] if len(last) > 5 else 0)
        mult = float(cfg.get("volume_climax_mult", 1.5))
        rng = (h - l) or 1e-9
        pos_in_rng = (c_ - l) / rng                       # 1 = closed at high, 0 = at low
        if avg and v >= mult * avg:
            if side == "LONG" and c_ < o and pos_in_rng <= 0.4:
                flags.append(f"volume climax — {round(v/avg,1)}× avg on a rejection bar")
            if side == "SHORT" and c_ > o and pos_in_rng >= 0.6:
                flags.append(f"volume climax — {round(v/avg,1)}× avg on a rejection bar")
    return flags


def _atr(candles: List[List[Any]], n: int = 14) -> Optional[float]:
    """Wilder ATR(n) from OHLC candles [ts,o,h,l,c,...]."""
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][2], candles[i][3], candles[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def chandelier(candles: List[List[Any]], side: str, mult: float,
               lookback: int = 22, n: int = 14) -> Optional[Dict[str, Any]]:
    """Chandelier exit (LeBeau): LONG stop = highest-high(lookback) − mult×ATR; SHORT stop =
    lowest-low(lookback) + mult×ATR. Returns the stop dict when the latest CLOSE breaches it,
    else None. Stateless (trails from the recent extreme, not a stored entry peak)."""
    if len(candles) < max(lookback, n) + 2:
        return None
    a = _atr(candles, n)
    if not a:
        return None
    close = candles[-1][4]
    win = candles[-lookback:]
    if side == "LONG":
        ref = max(c[2] for c in win)
        stop = ref - mult * a
        if close < stop:
            return {"stop": round(stop, 2), "atr": round(a, 2), "ref": round(ref, 2)}
    else:
        ref = min(c[3] for c in win)
        stop = ref + mult * a
        if close > stop:
            return {"stop": round(stop, 2), "atr": round(a, 2), "ref": round(ref, 2)}
    return None


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


def _mcx_signal(symbol: str, product: Optional[str], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """MCX exit signal (C2). Resolves the option's CONTRACTUAL future, pulls that future's
    candles, and runs an ATR chandelier as the PRIMARY exit with the structure break as a
    fallback. Per-commodity ATR multiple. Confirmations annotate; a still-intact winner with
    stacked confirmations returns a WARN heads-up."""
    from dashboard import mcx, mcx_config
    rows = mcx.instruments()
    opt = next((o for o in mcx._opts(rows) if o["tradingsymbol"] == symbol), None)
    if not opt:
        return None
    link = mcx.contract_link(opt, rows)
    if not link.underlying_future_token:
        return None
    side = "LONG" if opt["instrument_type"] == "CE" else "SHORT"
    mcfg = mcx_config.get()
    intraday = (product or "").upper() == "MIS"
    if intraday:
        try:
            from dashboard import app as core
            if not core.ZerodhaPlumbingInspector.is_open("MCX"):
                return None
        except Exception:
            return None
        candles = fetch_intraday(link.underlying_future_token, mcfg.get("mcx_structure_intraday_interval", "15minute"))
        tf = "intraday"
    else:
        candles = mcx._daily_candles(link.underlying_future_token)
        tf = "daily"
    if not candles or len(candles) < 24:
        return None
    econ = link.economic_root
    amap = mcfg.get("mcx_atr_mult", {})
    mult = float(amap.get(econ, amap.get("base_metals_default", 1.75)))
    conf = confirmations(candles, side, cfg) if cfg.get("structure_confirmations", True) else []
    ann = (" · confirms: " + ", ".join(conf)) if conf else ""
    ch = chandelier(candles, side, mult)
    if ch:
        reason = (f"ATR chandelier ({tf}) — {side} exit: close {candles[-1][4]} beyond {mult}×ATR "
                  f"stop {ch['stop']} (ATR {ch['atr']}, from {ch['ref']})")
        struct = signal(candles, side, {"structure_pivot_k": int(cfg.get("structure_pivot_k", 2))})
        if struct["action"] == "EXIT":
            reason += " + structure break"
        return {"action": "EXIT", "method": "chandelier", "timeframe": tf, "level": ch["stop"],
                "reason": reason + ann, "confirmations": conf}
    struct = signal(candles, side, {"structure_pivot_k": int(cfg.get("structure_pivot_k", 2))})
    if struct["action"] == "EXIT":
        return {"action": "EXIT", "method": "structure", "timeframe": tf, "level": struct["level"],
                "reason": struct["reason"] + ann, "confirmations": conf}
    if cfg.get("structure_warn", True) and len(conf) >= int(cfg.get("structure_warn_min_confirms", 2)):
        return {"action": "WARN", "timeframe": tf, "confirmations": conf,
                "reason": "weakening while structure holds — " + ", ".join(conf)}
    return None


def position_signal(symbol: str, product: Optional[str], cfg: Dict[str, Any],
                    exchange: str = "NSE") -> Optional[Dict[str, Any]]:
    """Live wrapper for exit_monitor: parse the option symbol, pull the underlying's candles
    for the right TIMEFRAME (MIS → intraday, else daily), and return the structure signal
    ONLY when it's a full EXIT (else None). MCX routes through the contractual future with an
    ATR-first exit (see _mcx_signal); NSE/NFO keep the structure-first logic below."""
    if not cfg.get("structure_exits", True):
        return None
    if (exchange or "NSE").upper() == "MCX":
        try:
            return _mcx_signal(symbol, product, cfg)
        except Exception:
            return None
    m = _SYM.match(symbol or "")
    if not m:
        return None
    side = "LONG" if m.group("t") == "CE" else "SHORT"
    from dashboard import swing_scan               # lazy: avoids any import cycle
    fut = swing_scan._futures_map().get(m.group("u"))
    if not fut:
        return None
    # Timeframe by product: MIS trades break down on intraday structure (Phase 2b), swing/
    # positional on daily. Intraday needs market hours (the forming bar is meaningless once shut).
    intraday = (product or "").upper() == "MIS"
    if intraday:
        if not swing_scan._market_open_now():
            return None
        candles = fetch_intraday(fut["token"], cfg.get("structure_intraday_interval", "15minute"))
        tf, k = "intraday", int(cfg.get("structure_intraday_pivot_k", cfg.get("structure_pivot_k", 2)))
    else:
        candles = swing_scan._daily_candles(fut["token"])   # warm daily cache — no new cost
        tf, k = "daily", int(cfg.get("structure_pivot_k", 2))
    if not candles or len(candles) < 2 * k + 3:
        return None
    s = signal(candles, side, {**cfg, "structure_pivot_k": k})
    conf = confirmations(candles, side, cfg) if cfg.get("structure_confirmations", True) else []
    if s["action"] == "EXIT":
        s["timeframe"] = tf
        s["confirmations"] = conf
        if conf:                                   # annotate the exit for conviction
            s["reason"] = s["reason"] + " · confirms: " + ", ".join(conf)
        return s
    # Structure still intact, but confirmations stacking up → optional early-warning heads-up
    # (never an exit). exit_monitor gates this to positions actually in profit.
    if cfg.get("structure_warn", True) and len(conf) >= int(cfg.get("structure_warn_min_confirms", 2)):
        return {"action": "WARN", "timeframe": tf, "level": s.get("level"), "confirmations": conf,
                "reason": "weakening while structure still holds — " + ", ".join(conf)
                          + (f"; swing level {s['level']}" if s.get("level") else "")}
    return None


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
