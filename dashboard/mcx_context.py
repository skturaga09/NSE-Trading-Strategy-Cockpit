#!/usr/bin/env python3
"""
MCX inter-market context (C1b). Global benchmarks (COMEX/NYMEX), DXY, USDINR, US10y — used
as CONTEXT ONLY, never as execution-grade MCX price data. Every value carries a source
timestamp / age / status, and any missing source degrades gracefully (partial context, never
a failure that blocks basic MCX futures monitoring).

Attribution identity (returns, 1-day close-to-close approximation of Δln):
    Δ MCX future ≈ Δ international benchmark + Δ USDINR + residual/basis
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dashboard import mcx

_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_TTL = 900.0   # context cache/stale window (seconds)

# economic_root -> international benchmark. None = no free proxy (base metals → LME, unavailable).
GLOBAL_BENCHMARK: Dict[str, Optional[Dict[str, str]]] = {
    "CRUDEOIL": {"name": "WTI crude (NYMEX)", "ticker": "CL=F"},
    "NATURALGAS": {"name": "Henry Hub gas (NYMEX)", "ticker": "NG=F"},
    "GOLD": {"name": "COMEX gold", "ticker": "GC=F"},
    "SILVER": {"name": "COMEX silver", "ticker": "SI=F"},
    "COPPER": {"name": "COMEX copper", "ticker": "HG=F"},
    "ZINC": None, "LEAD": None, "ALUMINIUM": None, "NICKEL": None,
}
MACRO = {"DXY": "DX-Y.NYB", "USDINR": "INR=X", "US10Y": "^TNX"}


def _all_tickers() -> List[str]:
    ts = [b["ticker"] for b in GLOBAL_BENCHMARK.values() if b] + list(MACRO.values())
    return sorted(set(ts))


def _snapshot(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """Per-ticker {last, prev_close, change_pct, ts, status}. Cached; degrades to {} on failure."""
    now = time.time()
    if not force and _CACHE["data"] is not None and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["data"]
    out: Dict[str, Dict[str, Any]] = {}
    try:
        import yfinance as yf
        df = yf.download(_all_tickers(), period="7d", interval="1d", progress=False, threads=True)
        closes = df["Close"] if "Close" in df else df
        for tk in _all_tickers():
            try:
                s = closes[tk].dropna() if hasattr(closes, "columns") else closes.dropna()
                if len(s) < 2:
                    continue
                last = float(s.iloc[-1]); prev = float(s.iloc[-2])
                out[tk] = {"last": round(last, 4), "prev_close": round(prev, 4),
                           "change_pct": round((last / prev - 1.0) * 100.0, 3),
                           "ts": s.index[-1].isoformat(), "status": "delayed"}
            except Exception:
                continue
    except Exception:
        out = {}
    if out:
        _CACHE.update({"ts": now, "data": out})
    return out


def _src(tk: str, snap: Dict[str, Any]) -> Dict[str, Any]:
    d = snap.get(tk)
    if not d:
        return {"status": "unavailable", "change_pct": None, "last": None, "ts": None}
    return {"status": d["status"], "change_pct": d["change_pct"], "last": d["last"], "ts": d["ts"]}


def _attribution(mcx_ret: Optional[float], global_ret: Optional[float],
                 usdinr_ret: Optional[float]) -> Dict[str, Any]:
    """Pure: split the MCX move into global + FX + residual, with an alignment read."""
    if mcx_ret is None or global_ret is None:
        return {"mcx_return_pct": mcx_ret, "global_return_pct": global_ret,
                "usdinr_return_pct": usdinr_ret, "residual_return_pct": None,
                "alignment": "unavailable"}
    fx = usdinr_ret or 0.0
    residual = round(mcx_ret - global_ret - fx, 3)
    denom = max(abs(mcx_ret), 0.1)
    frac = abs(residual) / denom
    alignment = "high" if frac <= 0.35 else "mixed" if frac <= 0.7 else "low"
    return {"mcx_return_pct": round(mcx_ret, 3), "global_return_pct": round(global_ret, 3),
            "usdinr_return_pct": round(fx, 3), "residual_return_pct": residual, "alignment": alignment}


def _mcx_front_return(root: str) -> Optional[float]:
    """Front future's day %change from a live MCX quote (None if unavailable)."""
    try:
        fn = mcx.front_next_future(root)
        front = fn["front"]
        if not front:
            return None
        q = mcx.quote([front["tradingsymbol"]]).get(f"MCX:{front['tradingsymbol']}") or {}
        ltp = q.get("last_price"); prev = (q.get("ohlc") or {}).get("close")
        return round((ltp / prev - 1.0) * 100.0, 3) if (ltp and prev) else None
    except Exception:
        return None


def mcx_global_attribution(root: str, snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Attribution for one economic root, with a data-quality trail."""
    snap = snap if snap is not None else _snapshot()
    econ = mcx.economic_root(root)
    bench = GLOBAL_BENCHMARK.get(econ)
    g = _src(bench["ticker"], snap) if bench else {"status": "unavailable", "change_pct": None, "last": None, "ts": None}
    fx = _src(MACRO["USDINR"], snap)
    mcx_ret = _mcx_front_return(root)
    attr = _attribution(mcx_ret, g["change_pct"], fx["change_pct"])
    return {
        "root": root.upper(), "economic_root": econ,
        "benchmark": bench["name"] if bench else None,
        "window": "1d", "start_timestamp": None, "end_timestamp": g.get("ts"),
        **attr,
        "data_quality": {
            "global_benchmark": g, "usdinr": fx,
            "note": "global data is CONTEXT ONLY (delayed, different session) — not execution-grade MCX price",
        },
    }


def context() -> Dict[str, Any]:
    """Macro block (DXY/USDINR/US10y) + per-root attribution for the liquid universe."""
    snap = _snapshot()
    macro = {name: _src(tk, snap) for name, tk in MACRO.items()}
    roots = mcx_config_roots()
    attributions = {r: mcx_global_attribution(r, snap) for r in roots}
    stale = not snap
    warnings = ["global context unavailable — showing MCX-only"] if stale else []
    src = {"global_benchmark": {"age_seconds": None if stale else 0, "stale_after": _TTL,
                                "ts": None if stale else datetime.now(timezone.utc).isoformat()}}
    return {**mcx.envelope(mcx.market_state(), src, warnings), "macro": macro, "roots": attributions}


def context_for_root(root: str) -> Dict[str, Any]:
    return {**mcx.envelope(mcx.market_state(), {}), **mcx_global_attribution(root)}


def mcx_config_roots() -> List[str]:
    try:
        from dashboard import mcx_config
        return mcx_config.get().get("mcx_watchlist_default", mcx.MCX_LIQUID_ROOTS)
    except Exception:
        return mcx.MCX_LIQUID_ROOTS
