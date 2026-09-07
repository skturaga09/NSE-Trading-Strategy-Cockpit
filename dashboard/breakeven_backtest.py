#!/usr/bin/env python3
"""
Backtest the BREAKEVEN-LOCK arm/floor (exit_monitor Phase 1), across regimes.

The live rule acts on the OPTION PREMIUM's P&L%, not the underlying — so this adds the
"separate synthetic layer" the trailing harness deliberately left out: for each entry it
prices an ATM option along the underlying path (Black-Scholes, with theta decay and a
regime IV), then runs the EXACT live floor logic (hard stop + profit ratchet + breakeven
lock) on that premium path. It sweeps the breakeven arm so you can see the real tradeoff:

  rescued  = trades that WOULD have round-tripped green→red, saved by the lock (the win)
  whipsaw  = green trades the lock cut at breakeven that would have ended richer (the cost)

Reuses the trailing harness's data seam (fetch_window) and the live _effective_trail, so
what's measured is what ships. Honest limits (inherited): daily OHLC (not tick), a single
synthetic ATM option per trade at a fixed regime IV, momentum-proxy entry direction, no
GTT latency. It validates the arm's REGIME-ROBUSTNESS and the rescue/whipsaw balance —
not an exact live fill.
"""

import statistics as st
from typing import Any, Dict, List, Optional, Tuple

from dashboard import app as core  # noqa: F401  (ensures KITE_CONFIG is loaded for fetch_window)
from dashboard import option_chain as oc
from dashboard import exit_monitor as em
from dashboard.trailing_backtest import fetch_window, NIFTY_TOKEN, REGIMES

T0_DAYS = 25.0        # calendar days to expiry at entry (mid-monthly option)
HORIZON = 5           # sessions held
MOM_LOOKBACK = 20     # momentum window for entry direction (matches trailing harness)
ARMS = [0.0, 6.0, 8.0, 10.0, 12.0, 15.0]   # 0 = breakeven lock OFF (baseline)
FLOOR = 0.0           # breakeven floor: 0 = protect entry
REGIME_IV = {"CHOP (last yr)": 0.25, "TREND (2020-21)": 0.28, "CRASH (Mar-26)": 0.45}


def _prem(S: float, K: float, t_days: float, iv: float, is_call: bool) -> float:
    return oc._bs(S, K, max(t_days, 0.5) / 365.0, iv, is_call)


def _floor_pct(peak: float, cfg: Dict[str, Any], be_arm: float, be_floor: float) -> Tuple[float, str]:
    """Most-protective exit floor (in premium P&L%) given the peak so far, and which rule set it."""
    floor, why = -cfg["stop_pct"], "stop"
    gb = em._effective_trail(peak, cfg)               # live ratchet give-back, or None
    if gb is not None and (peak - gb) > floor:
        floor, why = peak - gb, "ratchet"
    if be_arm and peak >= be_arm and be_floor > floor:
        floor, why = be_floor, "breakeven"
    return floor, why


def _simulate(path: List[List[Any]], a: int, direction: int, iv: float, cfg: Dict[str, Any],
              be_arm: float, be_floor: float) -> Optional[Tuple[float, str]]:
    """One long-option trade (CALL if momentum up, else PUT) over up to HORIZON sessions.
    Conservative same-day order: test the downside floor against the day's ADVERSE premium
    before raising the peak from the day's FAVORABLE premium (no look-ahead)."""
    is_call = direction == 1
    entry_S = path[a][4]
    K = entry_S                                        # ATM at entry
    prem0 = _prem(entry_S, K, T0_DAYS, iv, is_call)
    if prem0 <= 0:
        return None
    peak = 0.0
    end = min(a + HORIZON, len(path) - 1)
    for i in range(a + 1, end + 1):
        t_days = T0_DAYS - (i - a) * 7.0 / 5.0         # ~7 calendar days per 5 sessions
        hi, lo = path[i][2], path[i][3]
        fav_S, adv_S = (hi, lo) if is_call else (lo, hi)
        pnl_adv = (_prem(adv_S, K, t_days, iv, is_call) - prem0) / prem0 * 100
        pnl_fav = (_prem(fav_S, K, t_days, iv, is_call) - prem0) / prem0 * 100
        floor, why = _floor_pct(peak, cfg, be_arm, be_floor)
        if pnl_adv <= floor:                           # downside floor breached → exit at the floor
            return round(floor, 2), why
        peak = max(peak, pnl_fav)
        if pnl_fav >= cfg["target_pct"]:               # upside target
            return round(cfg["target_pct"], 2), "target"
    t_end = T0_DAYS - (end - a) * 7.0 / 5.0
    return round((_prem(path[end][4], K, t_end, iv, is_call) - prem0) / prem0 * 100, 2), "horizon"


def backtest_regime(candles: List[List[Any]], iv: float, cfg: Dict[str, Any]) -> Dict[str, Any]:
    cl = [k[4] for k in candles]
    rows: Dict[float, Dict[str, Any]] = {arm: {"pnls": [], "reasons": {}} for arm in ARMS}
    paired = {arm: {"rescued": 0, "whipsaw": 0} for arm in ARMS if arm > 0}
    n = 0
    for a in range(MOM_LOOKBACK, len(candles) - HORIZON):
        direction = 1 if cl[a] >= cl[a - MOM_LOOKBACK] else -1
        base = _simulate(candles, a, direction, iv, cfg, 0.0, FLOOR)   # breakeven OFF
        if base is None:
            continue
        n += 1
        for arm in ARMS:
            r = base if arm == 0 else _simulate(candles, a, direction, iv, cfg, arm, FLOOR)
            if r is None:
                continue
            pnl, why = r
            rows[arm]["pnls"].append(pnl)
            rows[arm]["reasons"][why] = rows[arm]["reasons"].get(why, 0) + 1
            if arm > 0:
                if base[0] < 0 <= pnl:                  # would have gone red, lock saved it
                    paired[arm]["rescued"] += 1
                elif why == "breakeven" and pnl < base[0]:  # lock cut a trade the baseline let run
                    paired[arm]["whipsaw"] += 1
    out: Dict[str, Any] = {"trades": n, "rows": {}}
    for arm, d in rows.items():
        ps = d["pnls"]
        if not ps:
            continue
        out["rows"][arm] = {
            "avg_pnl": round(sum(ps) / len(ps), 2),
            "win_rate": round(sum(1 for p in ps if p > 0) / len(ps) * 100, 1),
            "total": round(sum(ps), 1),
            "rescued": paired.get(arm, {}).get("rescued", 0),
            "whipsaw": paired.get(arm, {}).get("whipsaw", 0),
        }
    return out


def run() -> None:
    cfg = em.get_config()
    print(f"Breakeven-lock backtest · arms {ARMS[1:]}% (0=off) · floor {FLOOR}% · horizon {HORIZON} sessions")
    print(f"Synthetic ATM option per trade (BS, {T0_DAYS:.0f}d→theta-decayed), momentum-proxy direction, underlying=NIFTY.")
    print(f"Live floors reused: stop −{cfg['stop_pct']}% · target +{cfg['target_pct']}% · ratchet {cfg.get('ratchet_tiers')}\n")
    for name, (s, e) in REGIMES.items():
        candles = fetch_window(NIFTY_TOKEN, s, e)
        if len(candles) < 30:
            print(f"{name}: not enough data ({len(candles)})\n"); continue
        r = backtest_regime(candles, REGIME_IV.get(name, 0.30), cfg)
        print(f"=== {name}  ({s}→{e}, {r['trades']} trades, IV {int(REGIME_IV.get(name,0.30)*100)}%) ===")
        print(f"   {'policy':<16}{'avg P&L%':>10}{'win%':>8}{'total%':>10}{'rescued':>9}{'whipsaw':>9}")
        for arm in ARMS:
            row = r["rows"].get(arm)
            if not row:
                continue
            label = "no BE (base)" if arm == 0 else f"BE arm +{arm:.0f}%"
            resc = "" if arm == 0 else str(row["rescued"])
            whip = "" if arm == 0 else str(row["whipsaw"])
            print(f"   {label:<16}{row['avg_pnl']:>10}{row['win_rate']:>8}{row['total']:>10}{resc:>9}{whip:>9}")
        print()


if __name__ == "__main__":
    run()
