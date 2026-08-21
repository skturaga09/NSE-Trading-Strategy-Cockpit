#!/usr/bin/env python3
"""
Live Market Data — real breadth, regime, and prices from Yahoo Finance (yfinance).

Powers the trend-synthesis engine with genuine numbers instead of calibrated
mocks. Everything is cached with a TTL so the dashboard does not re-hit the
network on every request, and every function degrades gracefully (returns None)
so callers can fall back to calibrated data when offline or rate-limited.

What is genuinely live here:
  - Nifty 50 index level, 50-DMA / 200-DMA, and the derived regime & health score
  - Market breadth across a Nifty-50 basket: % above 200-DMA, advance/decline,
    new 52-week highs/lows
  - Per-symbol last price, 200-DMA distance, and relative strength vs the index

What is NOT available from a free feed (kept calibrated, flagged is_live=False
by the caller): FII/DII institutional flows.
"""

import time
import warnings
from typing import Dict, List, Optional, Any

warnings.filterwarnings("ignore")

try:
    import logging
    import yfinance as yf
    import pandas as pd
    # Keep the dashboard server log clean — yfinance logs failed tickers loudly.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    YF_OK = True
except Exception:
    YF_OK = False

# A representative Nifty-50 large-cap basket (Yahoo .NS tickers). Breadth across
# this basket is a valid read of the broad-market trend.
NIFTY50_BASKET: List[str] = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
    "BHARTIARTL.NS", "SBIN.NS", "LT.NS", "ITC.NS", "KOTAKBANK.NS",
    "HINDUNILVR.NS", "AXISBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "SUNPHARMA.NS",
    "M&M.NS", "TITAN.NS", "ULTRACEMCO.NS", "NTPC.NS", "TATAMOTORS.NS",
    "POWERGRID.NS", "TATASTEEL.NS", "ASIANPAINT.NS", "NESTLEIND.NS", "BAJAJFINSV.NS",
    "WIPRO.NS", "ADANIENT.NS", "ADANIPORTS.NS", "COALINDIA.NS", "JSWSTEEL.NS",
    "HCLTECH.NS", "ONGC.NS", "GRASIM.NS", "TECHM.NS", "HINDALCO.NS",
    "CIPLA.NS", "DRREDDY.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "BRITANNIA.NS",
    "TRENT.NS", "BEL.NS", "APOLLOHOSP.NS", "HEROMOTOCO.NS", "SBILIFE.NS",
    "INDUSINDBK.NS", "TATACONSUM.NS", "DIVISLAB.NS", "SHRIRAMFIN.NS", "HDFCLIFE.NS",
]

INDEX_TICKER = "^NSEI"

# --- cache -----------------------------------------------------------------
_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_CACHE_TTL_SEC = 900  # 15 minutes


def _dma(series: "pd.Series", n: int) -> Optional[float]:
    s = series.dropna()
    if len(s) == 0:
        return None
    return float(s.tail(n).mean())


def _fetch_frame() -> Optional["pd.DataFrame"]:
    """Batched 1y daily download of index + basket. Returns the Close frame or None."""
    if not YF_OK:
        return None
    tickers = [INDEX_TICKER] + NIFTY50_BASKET
    try:
        df = yf.download(
            tickers, period="1y", interval="1d",
            progress=False, auto_adjust=True, threads=True,
        )
        if df is None or df.empty:
            return None
        close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
        return close.dropna(how="all")
    except Exception:
        return None


def _compute(close: "pd.DataFrame") -> Optional[Dict[str, Any]]:
    """Turn a Close frame into a cockpit-shaped market_health + breadth block."""
    if INDEX_TICKER not in close.columns:
        return None
    nifty = close[INDEX_TICKER].dropna()
    if len(nifty) < 50:
        return None

    nifty_last = float(nifty.iloc[-1])
    dma200 = _dma(nifty, 200)
    dma50 = _dma(nifty, 50)
    pct_vs_200 = ((nifty_last / dma200) - 1.0) * 100.0 if dma200 else 0.0

    total = above200 = advances = declines = new_highs = new_lows = 0
    for tk in NIFTY50_BASKET:
        if tk not in close.columns:
            continue
        s = close[tk].dropna()
        if len(s) < 2:
            continue
        total += 1
        last = float(s.iloc[-1])
        prev = float(s.iloc[-2])
        d200 = _dma(s, 200)
        if d200 and last > d200:
            above200 += 1
        if last > prev:
            advances += 1
        elif last < prev:
            declines += 1
        window = s.tail(252)
        hi = float(window.max())
        lo = float(window.min())
        if last >= hi * 0.995:
            new_highs += 1
        if last <= lo * 1.005:
            new_lows += 1

    if total == 0:
        return None

    breadth_pct = round(above200 / total * 100.0, 1)
    ad_ratio = advances / declines if declines > 0 else float(advances or 1)
    cross_bonus = 5.0 if (dma50 and dma200 and dma50 > dma200) else (-5.0 if (dma50 and dma200) else 0.0)

    score = 40.0 + (breadth_pct - 50.0) * 0.6 + pct_vs_200 * 1.5 + cross_bonus
    score = round(max(0.0, min(100.0, score)), 0)

    nifty_above_200 = bool(dma200 and nifty_last > dma200)
    if nifty_above_200 and breadth_pct >= 55:
        regime = "RISK_ON"
    elif (not nifty_above_200) and breadth_pct <= 45:
        regime = "RISK_OFF"
    else:
        regime = "NEUTRAL"

    return {
        "market_health": {
            "score": int(score),
            "regime": regime,
            "advance_decline": f"{ad_ratio:.1f} : 1",
            "stocks_above_200dma_pct": breadth_pct,
            "new_52w_highs": new_highs,
            "new_52w_lows": new_lows,
            "nifty_last": round(nifty_last, 1),
            "nifty_50dma": round(dma50, 1) if dma50 else None,
            "nifty_200dma": round(dma200, 1) if dma200 else None,
        },
        "as_of": time.strftime("%Y-%m-%d %H:%M:%S"),
        "universe_size": total,
    }


def get_live_market(force: bool = False) -> Optional[Dict[str, Any]]:
    """Cached live market_health + breadth. Returns None if unavailable (offline / no yfinance)."""
    now = time.time()
    if not force and _CACHE["data"] is not None and (now - _CACHE["ts"]) < _CACHE_TTL_SEC:
        return _CACHE["data"]
    close = _fetch_frame()
    if close is None:
        return None
    result = _compute(close)
    if result is not None:
        _CACHE["ts"] = now
        _CACHE["data"] = result
    return result


# Per-symbol last-price cache so positions polling (every ~2s) does not hammer
# Yahoo. Refreshed at most once per _LTP_TTL seconds per symbol.
_LTP_CACHE: Dict[str, Any] = {}
_LTP_TTL = 45

# Index tradingsymbols → Yahoo tickers.
_INDEX_YF = {
    "NIFTY": "^NSEI", "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK", "NIFTY BANK": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
}


def get_ltp(symbol: str) -> Optional[float]:
    """Real last price for an equity/index symbol from Yahoo (cached). None if unavailable."""
    if not YF_OK or not symbol:
        return None
    key = symbol.upper().strip()
    now = time.time()
    hit = _LTP_CACHE.get(key)
    if hit and (now - hit[1]) < _LTP_TTL:
        return hit[0]

    yf_ticker = _INDEX_YF.get(key, key if key.endswith(".NS") else f"{key}.NS")
    price: Optional[float] = None
    try:
        tk = yf.Ticker(yf_ticker)
        try:
            price = float(tk.fast_info["last_price"])
        except Exception:
            h = tk.history(period="1d")
            if len(h):
                price = float(h["Close"].iloc[-1])
    except Exception:
        price = None

    if price and price > 0:
        price = round(price, 2)
        _LTP_CACHE[key] = (price, now)
        return price
    return None


# NSE sector indices (Yahoo tickers) → dashboard theme labels. Labels match the
# symbol→theme map in app.py so a screened stock earns its sector's live conviction.
_SECTOR_INDICES: Dict[str, str] = {
    "^NSEBANK": "Banking & Financials",
    "^CNXIT": "IT & Digital",
    "^CNXPHARMA": "Pharma & Healthcare",
    "^CNXAUTO": "Auto",
    "^CNXFMCG": "FMCG & Consumption",
    "^CNXMETAL": "Metals",
    "^CNXENERGY": "Energy",
    "^CNXREALTY": "Realty",
    "^CNXINFRA": "Defence & Capital Goods",
    "^CNXMEDIA": "Media",
}

_THEME_CACHE: Dict[str, Any] = {"ts": 0.0, "data": None}
_THEME_TTL = 1800


def get_sector_themes(top_n: int = 3) -> Optional[List[Dict[str, Any]]]:
    """Rank NSE sectors by live momentum & relative strength; return the top N themes.

    Each theme: {theme, conviction (0-5), driver} derived from 3-month return,
    relative strength vs Nifty, and trend vs the 50/200-DMA. None if unavailable.
    """
    if not YF_OK:
        return None
    now = time.time()
    if _THEME_CACHE["data"] is not None and (now - _THEME_CACHE["ts"]) < _THEME_TTL:
        return _THEME_CACHE["data"]

    try:
        tickers = list(_SECTOR_INDICES) + [INDEX_TICKER]
        df = yf.download(tickers, period="1y", interval="1d", progress=False, threads=True)
        close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
    except Exception:
        return None
    if INDEX_TICKER not in close.columns:
        return None

    def ret_3m(s: "pd.Series") -> Optional[float]:
        s = s.dropna()
        return float(s.iloc[-1] / s.iloc[-63] - 1.0) * 100.0 if len(s) > 63 else None

    nifty_ret = ret_3m(close[INDEX_TICKER])
    if nifty_ret is None:
        return None

    scored: List[Dict[str, Any]] = []
    for tk, theme in _SECTOR_INDICES.items():
        if tk not in close.columns:
            continue
        s = close[tk].dropna()
        r = ret_3m(s)
        if r is None:
            continue
        last = float(s.iloc[-1])
        d50 = _dma(s, 50)
        d200 = _dma(s, 200) if len(s) >= 200 else None
        rs = r - nifty_ret
        above50 = bool(d50 and last > d50)
        above200 = d200 is None or last > d200  # if no 200d history, don't penalize
        conv = 2.5 + rs * 0.15 + (0.6 if above200 else -0.6) + (0.4 if above50 else -0.4)
        conv = round(max(0.5, min(5.0, conv)), 1)
        trend = "above" if above200 else "below"
        scored.append({
            "theme": theme,
            "conviction": conv,
            "driver": f"{r:+.1f}% 3M · RS {rs:+.1f} vs Nifty · {trend} 200-DMA",
            "_rs": rs,
        })

    if not scored:
        return None
    scored.sort(key=lambda x: x["conviction"], reverse=True)
    top = [{k: v for k, v in t.items() if k != "_rs"} for t in scored[:top_n]]
    _THEME_CACHE["ts"] = now
    _THEME_CACHE["data"] = top
    return top


def get_live_quotes(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    """Live last price, 200-DMA distance, and 6-month relative strength vs Nifty for each symbol."""
    if not YF_OK or not symbols:
        return {}
    tickers = [s if s.endswith(".NS") else f"{s}.NS" for s in symbols]
    try:
        df = yf.download([INDEX_TICKER] + tickers, period="1y", interval="1d",
                         progress=False, auto_adjust=True, threads=True)
        close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
    except Exception:
        return {}

    out: Dict[str, Dict[str, float]] = {}
    nifty = close[INDEX_TICKER].dropna() if INDEX_TICKER in close.columns else None
    nifty_ret = None
    if nifty is not None and len(nifty) > 126:
        nifty_ret = float(nifty.iloc[-1] / nifty.iloc[-126] - 1.0)

    for sym, tk in zip(symbols, tickers):
        if tk not in close.columns:
            continue
        s = close[tk].dropna()
        if len(s) < 2:
            continue
        last = float(s.iloc[-1])
        d200 = _dma(s, 200)
        rec = {"last_price": round(last, 2)}
        if d200:
            rec["pct_above_200dma"] = round((last / d200 - 1.0) * 100.0, 2)
        if nifty_ret is not None and len(s) > 126:
            stock_ret = float(s.iloc[-1] / s.iloc[-126] - 1.0)
            rec["rs_vs_index_6m_pct"] = round((stock_ret - nifty_ret) * 100.0, 2)
        out[sym] = rec
    return out


if __name__ == "__main__":
    import json
    print("yfinance available:", YF_OK)
    print(json.dumps(get_live_market(force=True), indent=2, default=str))
