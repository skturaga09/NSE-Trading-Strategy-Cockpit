#!/usr/bin/env python3
"""
Intraday validation of the pullback setup (C6c, live-lane). The live radar runs on 15-min
bars; the daily backtest only validated the mechanism. This validates the lane that actually
trades: roll-stitched INTRADAY history per root, pullback-entry vs momentum, with score
buckets. This is the gate that can legitimately flip `mcx_setups_validated`.

Reuses the C5/C6c primitives (active_contract, _sim_trade, _metrics, run_setup_policy,
score_buckets). Honest limits: Kite intraday history depth is finite (a few months per
contract), and each contract is only active ~a month, so stitched depth is bounded; the
pullback SCORE must also rank (buckets monotone) before the gate flips, not just beat momentum.
"""

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from dashboard import mcx, mcx_backtest as bt
from dashboard.mcx_setup_backtest import run_setup_policy, score_buckets

INTERVAL = "15minute"
LOOKBACK_DAYS = 90
BACK_CONTRACTS = 4


def _headers() -> Dict[str, str]:
    from dashboard import app as core
    kc = core.KITE_CONFIG
    return {"Authorization": f"token {kc.get('api_key','')}:{kc.get('access_token','')}", "X-Kite-Version": "3"}


def _fetch_intraday(token: int, frm: str, to: str, interval: str = INTERVAL) -> List[List[Any]]:
    try:
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/{interval}",
                         params={"from": frm, "to": to}, headers=_headers(), timeout=20).json()
        return j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        return []


def _contracts_and_intraday(root: str):
    rows = mcx.instruments()
    futs = sorted(mcx.futures_map(rows).get(root.upper(), []), key=lambda x: x["expiry"])[-BACK_CONTRACTS:]
    contracts = [{"symbol": f["tradingsymbol"], "token": f["token"], "expiry": f["expiry"]} for f in futs]
    cbt: Dict[int, List[List[Any]]] = {}
    for c in contracts:
        frm = (c["expiry"] - timedelta(days=LOOKBACK_DAYS)).isoformat()
        cbt[c["token"]] = _fetch_intraday(c["token"], frm, c["expiry"].isoformat())
    return contracts, cbt


def stitch_intraday(contracts: List[Dict[str, Any]], cbt: Dict[int, List[List[Any]]],
                    roll_days_before: int = 3, roll_window_days: int = 5) -> List[Dict[str, Any]]:
    """Intraday-resolution roll stitch: keep every bar from the contract that is ACTIVE on that
    bar's date (rolls roll_days_before expiry); order by timestamp; flag roll transitions."""
    items = []
    for c in contracts:
        for k in cbt.get(c["token"], []):
            items.append((k[0], k, c))
    items.sort(key=lambda x: x[0])
    out: List[Dict[str, Any]] = []
    prev = None
    for ts, bar, c in items:
        try:
            d = date.fromisoformat(ts[:10])
        except Exception:
            continue
        ac = bt.active_contract(contracts, d, roll_days_before)
        if not ac or ac["token"] != c["token"]:
            continue
        out.append({"ts": ts, "date": d, "bar": bar, "contract": c["symbol"],
                    "roll_window": (c["expiry"] - d).days <= roll_window_days,
                    "roll_transition": prev is not None and prev != c["symbol"]})
        prev = c["symbol"]
    return out


def run(roots: Optional[List[str]] = None) -> None:
    from dashboard import mcx_config
    cfg = {**mcx_config.get(), "structure_pivot_k": 2}
    roots = roots or cfg.get("mcx_watchlist_default", mcx.MCX_LIQUID_ROOTS)
    amap = cfg.get("mcx_atr_mult", {})
    pb_cfg = {**cfg, "mcx_setup_detectors": ["pullback"]}
    print(f"INTRADAY validation · {INTERVAL} roll-stitched · pullback vs momentum · lookback {LOOKBACK_DAYS}d")
    print("Gate flips only if pullback beats momentum AND the score buckets are monotone, per root.\n")
    for root in roots:
        contracts, cbt = _contracts_and_intraday(root)
        series = stitch_intraday(contracts, cbt)
        if len(series) < 200:
            print(f"=== {root}: thin intraday history ({len(series)} bars) — cannot validate ===\n"); continue
        mult = amap.get(mcx.economic_root(root), amap.get("base_metals_default", 1.75))
        pb = bt._metrics(run_setup_policy(series, pb_cfg, mult, 0.0))
        mo = bt._metrics(bt.run_policy(series, mult, root))
        print(f"=== {root}  ({len(series)} {INTERVAL} bars, {len(contracts)} contracts, mult {mult}) ===")
        print(f"   {'policy':<20}{'trades':>8}{'avg%':>8}{'win%':>7}{'avgR':>7}{'maxDD%':>8}")
        for name, m in [("pullback", pb), ("momentum baseline", mo)]:
            if m.get("trades"):
                print(f"   {name:<20}{m['trades']:>8}{m['avg_pnl']:>8}{m['win_rate']:>7}{str(m['avg_R']):>7}{m['max_drawdown']:>8}")
        line = " ".join(f"{b['bucket']}:{b.get('avg_pnl','—')}%/{b.get('win_rate','—')}%(n{b['n']})" for b in score_buckets(run_setup_policy(series, pb_cfg, mult, 0.0)))
        print(f"     pullback score→outcome: {line}")
        print()


if __name__ == "__main__":
    run()
