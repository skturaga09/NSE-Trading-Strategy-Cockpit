#!/usr/bin/env python3
"""
MCX commodity backtest (C5). Validates the ATR/chandelier exit on roll-stitched MCX FUTURES
history, per root, with walk-forward and segmentation. Offline validation only (CLI), same
spirit as trailing_backtest / breakeven_backtest.

Roll methodology (explicit, recorded — NOT an undocumented continuous series):
  each calendar date uses the nearest-expiry contract whose (expiry − roll_days_before) is
  still on/after that date; when the active contract changes, that bar is a ROLL TRANSITION.
  Prices are UNADJUSTED across rolls (the roll gap is left in and flagged), so a trade is
  never held across a contract switch — trades that would span a roll are closed at the roll.

Honest limits: daily bars (so day-vs-evening SESSION segmentation is not possible here and is
deferred); event-day tagging uses the EIA weekday as a daily proxy (intraday timing isn't in
daily bars); momentum-proxy entry direction (no historical signal); per-contract Kite history
can be shallow, capping walk-forward depth. Include spread/slippage via ROUND_TRIP_COST_PCT.
"""

import statistics as st
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

ROUND_TRIP_COST_PCT = 0.15   # spread + slippage assumption per trade (underlying %), conservative for MCX
MOM_LOOKBACK = 20
HORIZON = 20                 # max bars held (chandelier usually exits earlier)
ATR_N = 14
DEFAULT_WIDTHS = [1.5, 1.75, 2.0, 2.5, 3.0]
EIA_WEEKDAY = {"CRUDEOIL": 2, "NATURALGAS": 3}   # Wed / Thu (daily event-day proxy)


# ---- pure roll stitching -------------------------------------------------
def active_contract(contracts: List[Dict[str, Any]], on_date: date, roll_days_before: int) -> Optional[Dict[str, Any]]:
    """Nearest-expiry contract still active on `on_date` (rolls roll_days_before its expiry)."""
    for c in sorted(contracts, key=lambda x: x["expiry"]):
        if c["expiry"] - timedelta(days=roll_days_before) >= on_date:
            return c
    return None


def stitch_series(contracts: List[Dict[str, Any]], candles_by_token: Dict[int, List[List[Any]]],
                  roll_days_before: int = 3, roll_window_days: int = 5) -> List[Dict[str, Any]]:
    """Build a date-ordered stitched series. Each item: {date, bar[o,h,l,c,vol], contract,
    roll_window(bool), roll_transition(bool)}. Unadjusted; a contract change flags a transition."""
    # date -> {token: bar}
    by_date: Dict[date, Dict[int, List[Any]]] = {}
    for c in contracts:
        for k in candles_by_token.get(c["token"], []):
            try:
                d = date.fromisoformat(k[0][:10])
            except Exception:
                continue
            by_date.setdefault(d, {})[c["token"]] = k
    out: List[Dict[str, Any]] = []
    prev_symbol = None
    for d in sorted(by_date):
        ac = active_contract(contracts, d, roll_days_before)
        if not ac or ac["token"] not in by_date[d]:
            continue
        bar = by_date[d][ac["token"]]
        out.append({
            "date": d, "bar": bar, "contract": ac["symbol"],
            "roll_window": (ac["expiry"] - d).days <= roll_window_days,
            "roll_transition": prev_symbol is not None and prev_symbol != ac["symbol"],
        })
        prev_symbol = ac["symbol"]
    return out


# ---- indicators / regime -------------------------------------------------
def _atr(bars: List[List[Any]], n: int = ATR_N) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    trs = [max(bars[i][2] - bars[i][3], abs(bars[i][2] - bars[i - 1][4]), abs(bars[i][3] - bars[i - 1][4]))
           for i in range(1, len(bars))]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def _regime(closes: List[float]) -> str:
    """trend if the 20-bar move is large relative to noise, else range."""
    if len(closes) < 21:
        return "unknown"
    mom = (closes[-1] / closes[-21] - 1) * 100
    return "trend" if abs(mom) >= 4.0 else "range"


# ---- exit simulation (chandelier) ---------------------------------------
def _sim_trade(bars: List[List[Any]], a: int, direction: int, mult: float) -> Optional[Dict[str, Any]]:
    """Enter at close[a]; exit on chandelier breach (highest-high(22)−mult×ATR) or horizon.
    Returns pnl_pct, base_pnl (hold-to-horizon), hold bars, mae_pct, r_mult, ever_fav."""
    entry = bars[a][4]
    atr0 = _atr(bars[: a + 1])
    if not atr0 or entry <= 0:
        return None
    r_pct = mult * atr0 / entry * 100.0
    end = min(a + HORIZON, len(bars) - 1)
    ever_fav = False
    mae = 0.0
    exit_i, exit_px = end, bars[end][4]
    for i in range(a + 1, end + 1):
        hi, lo = bars[i][2], bars[i][3]
        # adverse excursion so far
        adv = ((lo - entry) if direction == 1 else (entry - hi)) / entry * 100.0 * 1
        mae = min(mae, adv)
        fav = ((hi - entry) if direction == 1 else (entry - lo)) / entry * 100.0
        if fav > 0:
            ever_fav = True
        win = bars[max(0, i - 22):i + 1]
        a_i = _atr(bars[: i + 1]) or atr0
        if direction == 1:
            stop = max(c[2] for c in win) - mult * a_i
            if bars[i][4] < stop:
                exit_i, exit_px = i, stop
                break
        else:
            stop = min(c[3] for c in win) + mult * a_i
            if bars[i][4] > stop:
                exit_i, exit_px = i, stop
                break
    pnl = (exit_px - entry) / entry * 100.0 * direction - ROUND_TRIP_COST_PCT
    base_px = bars[end][4]
    base = (base_px - entry) / entry * 100.0 * direction - ROUND_TRIP_COST_PCT
    return {"pnl": round(pnl, 3), "base": round(base, 3), "hold": exit_i - a,
            "mae": round(mae, 3), "r_mult": round(pnl / r_pct, 2) if r_pct else None, "ever_fav": ever_fav}


def _metrics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"trades": 0}
    pnls = [t["pnl"] for t in trades]
    rmults = [t["r_mult"] for t in trades if t["r_mult"] is not None]
    # drawdown of the cumulative pnl curve
    cum = 0.0; peak = 0.0; dd = 0.0
    for p in pnls:
        cum += p; peak = max(peak, cum); dd = min(dd, cum - peak)
    return {
        "trades": len(trades),
        "avg_pnl": round(sum(pnls) / len(pnls), 2),
        "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1),
        "total": round(sum(pnls), 1),
        "avg_hold": round(sum(t["hold"] for t in trades) / len(trades), 1),
        "avg_R": round(sum(rmults) / len(rmults), 2) if rmults else None,
        "avg_MAE": round(sum(t["mae"] for t in trades) / len(trades), 2),
        "max_drawdown": round(dd, 1),
        "rescued": sum(1 for t in trades if t["base"] < 0 <= t["pnl"]),
        "whipsaw": sum(1 for t in trades if t["ever_fav"] and t["pnl"] < 0),
    }


def run_policy(series: List[Dict[str, Any]], mult: float, root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Momentum-directional entries each bar; chandelier exit; tag each trade for segmentation.
    A trade never spans a roll transition (closed at the roll bar)."""
    from dashboard import mcx
    econ = mcx.economic_root(root) if root else None
    ev_wd = EIA_WEEKDAY.get(econ, -1)                    # EIA weekday for this root (daily proxy)
    bars = [s["bar"] for s in series]
    closes = [b[4] for b in bars]
    trades: List[Dict[str, Any]] = []
    for a in range(MOM_LOOKBACK, len(bars) - 1):
        direction = 1 if closes[a] >= closes[a - MOM_LOOKBACK] else -1
        # cap horizon at the next roll transition after entry (don't hold across a roll)
        nxt_roll = next((i for i in range(a + 1, len(series)) if series[i]["roll_transition"]), None)
        t = _sim_trade(bars if nxt_roll is None else bars[:nxt_roll + 1], a, direction, mult)
        if not t:
            continue
        t["tags"] = {"regime": _regime(closes[: a + 1]),
                     "roll_window": series[a]["roll_window"],
                     "event_day": series[a]["date"].weekday() == ev_wd}
        trades.append(t)
    return trades


def walk_forward(series: List[Dict[str, Any]], widths: List[float], folds: int = 3) -> List[Dict[str, Any]]:
    """Pick the best width on each train fold; report OOS metrics on the next fold."""
    n = len(series)
    if n < 100:
        return []
    step = n // (folds + 1)
    out = []
    for f in range(folds):
        train = series[: step * (f + 1)]
        test = series[step * (f + 1): step * (f + 2)]
        if len(test) < 25:
            continue
        best_w, best_total = widths[0], -1e9
        for w in widths:
            m = _metrics(run_policy(train, w))
            if m.get("total", -1e9) > best_total:
                best_total, best_w = m["total"], w
        oos = _metrics(run_policy(test, best_w))
        out.append({"fold": f + 1, "chosen_width": best_w, **oos})
    return out


# ---- live data + CLI -----------------------------------------------------
def _contracts_and_candles(root: str, back_contracts: int = 6):
    from dashboard import mcx
    from dashboard.trailing_backtest import fetch_window
    rows = mcx.instruments()
    futs = sorted(mcx.futures_map(rows).get(root.upper(), []), key=lambda x: x["expiry"])
    futs = futs[-back_contracts:] if len(futs) > back_contracts else futs
    contracts = [{"symbol": f["tradingsymbol"], "token": f["token"], "expiry": f["expiry"]} for f in futs]
    cbt: Dict[int, List[List[Any]]] = {}
    for c in contracts:
        try:
            cbt[c["token"]] = fetch_window(c["token"], (c["expiry"] - timedelta(days=180)).isoformat(),
                                           c["expiry"].isoformat())
        except Exception:
            cbt[c["token"]] = []
    return contracts, cbt


def run(roots: Optional[List[str]] = None) -> None:
    from dashboard import mcx, mcx_config
    roots = roots or mcx_config.get().get("mcx_watchlist_default", mcx.MCX_LIQUID_ROOTS)
    amap = mcx_config.get().get("mcx_atr_mult", {})
    print(f"MCX backtest · chandelier exit · widths {DEFAULT_WIDTHS} · horizon {HORIZON} · cost {ROUND_TRIP_COST_PCT}%/trade")
    print("Roll: unadjusted, roll 3d before expiry; trades never span a roll transition. Daily bars.\n")
    for root in roots:
        contracts, cbt = _contracts_and_candles(root)
        series = stitch_series(contracts, cbt)
        if len(series) < 60:
            print(f"=== {root}: not enough stitched history ({len(series)} bars) ===\n"); continue
        pref = amap.get(mcx.economic_root(root), amap.get("base_metals_default", 1.75))
        print(f"=== {root}  ({len(series)} stitched bars, {len(contracts)} contracts, pref width {pref}) ===")
        print(f"   {'width':>6}{'trades':>8}{'avg%':>8}{'win%':>7}{'avgR':>7}{'MAE%':>8}{'maxDD%':>8}{'resc':>6}{'whip':>6}")
        for w in DEFAULT_WIDTHS:
            m = _metrics(run_policy(series, w))
            if not m.get("trades"):
                continue
            print(f"   {w:>6}{m['trades']:>8}{m['avg_pnl']:>8}{m['win_rate']:>7}{str(m['avg_R']):>7}{m['avg_MAE']:>8}{m['max_drawdown']:>8}{m['rescued']:>6}{m['whipsaw']:>6}")
        # segmentation at the preferred width
        tr = run_policy(series, pref, root)
        for seg, key in [("trend", lambda t: t["tags"]["regime"] == "trend"),
                         ("range", lambda t: t["tags"]["regime"] == "range"),
                         ("roll-window", lambda t: t["tags"]["roll_window"]),
                         ("event-day", lambda t: t["tags"]["event_day"])]:
            sub = [t for t in tr if key(t)]
            m = _metrics(sub)
            if m.get("trades"):
                print(f"     · {seg:<12} n={m['trades']:>4} avg%={m['avg_pnl']:>6} win%={m['win_rate']:>5} avgR={m['avg_R']}")
        wf = walk_forward(series, DEFAULT_WIDTHS)
        if wf:
            print("     walk-forward (OOS):", " ".join(f"f{r['fold']}:w{r['chosen_width']}→{r['avg_pnl']}%/{r['win_rate']}%" for r in wf))
        print()


if __name__ == "__main__":
    run()
