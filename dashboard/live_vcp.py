#!/usr/bin/env python3
"""
Live VCP screener — real Minervini setups computed from price history.

Wraps the nse-vcp-screener skill (real trend-template, contraction detection,
volume dry-up, pivot proximity, and relative strength from yfinance) and adds
caching + background refresh so the dashboard never blocks on a multi-second
full-universe screen.

get_vcp_candidates(universe) returns (candidates, source, screening):
  - fresh cache        -> (real candidates, "Live VCP screen (yfinance)", False)
  - stale / first call  -> (last cache or None, "Screening in background…", True)
    and kicks off a background screen; the next call picks up the result.

Falls back to None when the screener/yfinance isn't importable, so callers use
their modeled snapshot instead.
"""

import argparse
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")
try:
    import logging
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
except Exception:
    pass

_SKILL = Path(__file__).parent.parent / "skills" / "nse-vcp-screener" / "scripts"
sys.path.insert(0, str(_SKILL))

try:
    from screen_vcp import screen_stock, fetch_benchmark, get_universe
    VCP_OK = True
except Exception:
    VCP_OK = False

# Relaxed-but-honest screen parameters (the skill default trend_min_score=85 is
# very strict; 60 surfaces building setups too).
_ARGS = argparse.Namespace(
    trend_min_score=60.0, lookback_days=120, min_contractions=2,
    t1_depth_min=5.0, t1_depth_max=50.0, contraction_ratio=0.85, min_contraction_days=3,
)

# Cap per-universe tickers so a background screen stays bounded (~0.2s each).
_UNIVERSE_CAP = {"nifty50": 50, "nifty200": 120, "nifty500": 150}
_TTL = 1800  # 30 min

_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
_SCREENING: set = set()


def _map(r: Dict[str, Any]) -> Dict[str, Any]:
    """Skill result → dashboard candidate shape."""
    cons = r.get("contractions", [])
    depth = lambda i: round(cons[i]["depth_pct"], 1) if len(cons) > i else 0.0
    dist = r.get("pivot_distance_pct", 0.0)
    status = "ACTIONABLE_BREAKOUT_SETUP" if abs(dist) <= 1.5 else "NEAR_PIVOT_BUILDING"
    return {
        "symbol": r["ticker"],
        "composite_score": round(r["composite_score"], 1),
        "trend_score": round(r.get("trend_score", 0), 1),
        "contraction_count": len(cons),
        "t1_depth_pct": depth(0),
        "t2_depth_pct": depth(1),
        "t3_depth_pct": depth(2),
        "volume_dryup_score": round(r.get("volume_score", 0), 1),
        "pivot_price": round(r["pivot"], 1),
        "current_price": round(r["price"], 2),
        "distance_to_pivot_pct": round(abs(dist), 2),
        "relative_strength_score": round(r.get("rs_score", 0), 1),
        "rs_vs_index_6m_pct": round(r.get("rs_value", 0), 2),
        "quality": r.get("quality", ""),
        "status": status,
    }


def _screen(universe: str) -> None:
    """Background worker: screen the (capped) universe and cache real candidates."""
    try:
        cap = _UNIVERSE_CAP.get(universe, 50)
        tickers = get_universe(universe)[:cap]
        bench = fetch_benchmark()
        out: List[Dict[str, Any]] = []
        for tk in tickers:
            try:
                r = screen_stock(tk, bench, _ARGS)
                if r:
                    out.append(_map(r))
            except Exception:
                continue
        out.sort(key=lambda c: c["composite_score"], reverse=True)
        with _LOCK:
            _CACHE[universe] = {"ts": time.time(), "candidates": out, "screened": len(tickers)}
    finally:
        with _LOCK:
            _SCREENING.discard(universe)


def get_vcp_candidates(universe: str) -> Tuple[Optional[List[Dict[str, Any]]], str, bool]:
    """Cached real VCP candidates. See module docstring for the return contract."""
    if not VCP_OK:
        return None, "unavailable", False

    now = time.time()
    with _LOCK:
        hit = _CACHE.get(universe)
        fresh = hit and (now - hit["ts"]) < _TTL
        if fresh:
            return hit["candidates"], "Live VCP screen (yfinance)", False
        already = universe in _SCREENING
        if not already:
            _SCREENING.add(universe)

    if not already:
        threading.Thread(target=_screen, args=(universe,), daemon=True).start()

    # Serve the last (stale) cache if we have one while a refresh runs.
    with _LOCK:
        hit = _CACHE.get(universe)
        if hit:
            return hit["candidates"], "Live VCP screen (yfinance, refreshing…)", True
    return None, "Screening in background… (showing modeled snapshot)", True


if __name__ == "__main__":
    import json
    uni = sys.argv[1] if len(sys.argv) > 1 else "nifty50"
    print(f"Screening {uni} synchronously…")
    _screen(uni)
    print(json.dumps(_CACHE[uni]["candidates"], indent=2))
