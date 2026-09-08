#!/usr/bin/env python3
"""
Setup-radar validation (C6c). Before the C6a setup SCORE is trusted, answer honestly:
  1. Does entering on a firing setup (trend+breakout, in its direction) beat the momentum
     baseline and buy-and-hold, per root?
  2. Is the SCORE monotone with outcome — do higher-score setups actually do better?

Runs the SAME pure detectors (mcx_setups.evaluate_setup) on the C5 roll-stitched daily
history, exits via the C2 chandelier, and buckets trades by score. Offline CLI.

Honest limits (inherited): daily bars (the live lane is intraday — same detectors, but this
validates the mechanism on the data we have depth for); shallow per-contract history → small
samples; momentum/hold baselines are proxies. A non-monotone score here means the score is a
rank, not an edge — do not lift the 'eligible' threshold on it.
"""

from typing import Any, Dict, List, Optional

from dashboard import mcx_backtest as bt
from dashboard.mcx_setups import evaluate_setup

SCORE_BUCKETS = [(0, 40), (40, 55), (55, 70), (70, 101)]


def run_setup_policy(series: List[Dict[str, Any]], cfg: Dict[str, Any], mult: float,
                     min_score: float = 0.0) -> List[Dict[str, Any]]:
    """Enter in the setup's direction whenever it fires with score >= min_score; chandelier
    exit; never span a roll transition. Tags each trade with its score + kind."""
    bars = [s["bar"] for s in series]
    trades: List[Dict[str, Any]] = []
    for a in range(max(bt.MOM_LOOKBACK, 25), len(bars) - 1):
        setup = evaluate_setup(bars[: a + 1], cfg, "unavailable")   # no look-ahead
        if setup["direction"] == "NONE" or setup["score"] < min_score:
            continue
        direction = 1 if setup["direction"] == "LONG" else -1
        nxt_roll = next((i for i in range(a + 1, len(series)) if series[i]["roll_transition"]), None)
        t = bt._sim_trade(bars if nxt_roll is None else bars[: nxt_roll + 1], a, direction, mult)
        if not t:
            continue
        t["score"], t["kind"] = setup["score"], setup["kind"]
        trades.append(t)
    return trades


def score_buckets(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """avg%/win%/n per score bucket — the monotonicity check for whether score means anything."""
    out = []
    for lo, hi in SCORE_BUCKETS:
        sub = [t for t in trades if lo <= t["score"] < hi]
        if not sub:
            out.append({"bucket": f"{lo}-{hi}", "n": 0}); continue
        pnls = [t["pnl"] for t in sub]
        out.append({"bucket": f"{lo}-{hi}", "n": len(sub),
                    "avg_pnl": round(sum(pnls) / len(pnls), 2),
                    "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1)})
    return out


def run(roots: Optional[List[str]] = None) -> None:
    from dashboard import mcx, mcx_config
    cfg = {**mcx_config.get(), "structure_pivot_k": 2}
    roots = roots or cfg.get("mcx_watchlist_default", mcx.MCX_LIQUID_ROOTS)
    amap = cfg.get("mcx_atr_mult", {})
    min_score = float(cfg.get("mcx_setup_min_score", 55))
    print(f"Setup-radar validation · setup-entry vs momentum vs hold · min_score {min_score} · daily roll-stitched")
    print("Q: does the setup beat momentum/hold, and is SCORE monotone with outcome?\n")
    for root in roots:
        contracts, cbt = bt._contracts_and_candles(root)
        series = bt.stitch_series(contracts, cbt)
        if len(series) < 60:
            print(f"=== {root}: not enough history ({len(series)}) ===\n"); continue
        mult = amap.get(mcx.economic_root(root), amap.get("base_metals_default", 1.75))
        tb_cfg = {**cfg, "mcx_setup_detectors": ["trend", "breakout"]}
        pb_cfg = {**cfg, "mcx_setup_detectors": ["pullback"]}
        tb_tr = run_setup_policy(series, tb_cfg, mult, 0.0)      # trend+breakout (the C6a live set)
        pb_tr = run_setup_policy(series, pb_cfg, mult, 0.0)      # pullback-only (the hypothesis)
        mom_tr = bt.run_policy(series, mult, root)
        print(f"=== {root}  ({len(series)} bars, mult {mult}) ===")
        print(f"   {'policy':<22}{'trades':>8}{'avg%':>8}{'win%':>7}{'avgR':>7}{'maxDD%':>8}")
        for name, m in [("trend+breakout", bt._metrics(tb_tr)), ("pullback", bt._metrics(pb_tr)),
                        ("momentum baseline", bt._metrics(mom_tr))]:
            if m.get("trades"):
                print(f"   {name:<22}{m['trades']:>8}{m['avg_pnl']:>8}{m['win_rate']:>7}{str(m['avg_R']):>7}{m['max_drawdown']:>8}")
        line = " ".join(f"{b['bucket']}:{b.get('avg_pnl','—')}%/{b.get('win_rate','—')}%(n{b['n']})" for b in score_buckets(pb_tr))
        print(f"     pullback score→outcome: {line}")
        print()


if __name__ == "__main__":
    run()
