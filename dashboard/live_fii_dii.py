#!/usr/bin/env python3
"""
Live FII/DII cash-market flows — fetched end-of-day, cached to disk.

FII/DII figures are published once per day (provisional, ~6 PM after market
close); there is no intraday feed. This module fetches the latest official
figure from NSE (primary) or Moneycontrol (fallback), caches it, and exposes it
in the shape the dashboard's cockpit expects.

Run `python3 dashboard/live_fii_dii.py` after ~6 PM (or via launchd) to refresh
the cache. get_fii_dii() returns the cached figure (or None if never fetched /
too stale), so the dashboard never blocks on the network and degrades to the
calibrated estimate when unavailable.

NSE is often blocked from datacenter IPs (403) but works from a residential
connection — i.e. from the user's own Mac, which is where the launchd job runs.
"""

import json
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any

CACHE_FILE = Path(__file__).resolve().parent / "fii_dii_cache.json"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")


def _num(x: Any) -> Optional[float]:
    """Parse '14,250.34' / '-1,200' / '(1,200)' into a float (crore)."""
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(re.sub(r"[^0-9.\-]", "", s) or "0")
        return -v if neg else v
    except Exception:
        return None


def _classify(fii_net: float, dii_net: float, date: str, source: str) -> Dict[str, Any]:
    fii_regime = "ACCUMULATION" if fii_net >= 0 else "DISTRIBUTION"
    dii_regime = "ACCUMULATION" if dii_net >= 0 else "DISTRIBUTION"
    if fii_net >= 0 and dii_net >= 0:
        divergence = "CONFIRMED_BULLISH"
    elif fii_net < 0 and dii_net < 0:
        divergence = "CONFIRMED_BEARISH"
    else:
        divergence = "DIVERGENT"

    def fmt(v: float) -> str:
        return f"{'+' if v >= 0 else '-'} ₹{abs(v):,.0f} Cr"

    return {
        "fii_regime": fii_regime,
        "dii_regime": dii_regime,
        "fii_net_mtd": fmt(fii_net),   # single-day net; label kept for cockpit compatibility
        "dii_net_mtd": fmt(dii_net),
        "fii_net_cr": round(fii_net, 2),
        "dii_net_cr": round(dii_net, 2),
        "flow_divergence": divergence,
        "date": date,
        "source": source,
        "is_live": True,
    }


def fetch_from_nse() -> Optional[Dict[str, Any]]:
    """Primary: NSE fiidiiTradeReact JSON (needs a cookie handshake)."""
    try:
        import requests
    except ImportError:
        return None
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept": "application/json, text/plain, */*",
                      "Accept-Language": "en-US,en;q=0.9"})
    try:
        s.get("https://www.nseindia.com/", timeout=10)  # seed cookies
        r = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=10)
        if r.status_code != 200:
            return None
        rows = r.json()
        fii_net = dii_net = None
        date = ""
        for row in rows:
            cat = str(row.get("category", "")).upper()
            net = _num(row.get("netValue"))
            date = row.get("date", date)
            if "FII" in cat or "FPI" in cat:
                fii_net = net
            elif "DII" in cat:
                dii_net = net
        if fii_net is None or dii_net is None:
            return None
        return _classify(fii_net, dii_net, date, "NSE (fiidiiTradeReact)")
    except Exception:
        return None


def fetch_from_moneycontrol() -> Optional[Dict[str, Any]]:
    """Fallback: scrape the latest row from Moneycontrol's FII/DII activity table."""
    try:
        import requests
    except ImportError:
        return None
    url = "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php"
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=12)
        if r.status_code != 200:
            return None
        html = r.text
        # Grab the first data row of the FII/DII table: date + 3 numbers each.
        m = re.search(
            r"(\d{2}-\d{2}-\d{4}|\d{1,2}-[A-Za-z]{3}-\d{4})"
            r"[^0-9\-]+([\d,.\-()]+)[^0-9\-]+([\d,.\-()]+)[^0-9\-]+([\d,.\-()]+)"
            r"[^0-9\-]+([\d,.\-()]+)[^0-9\-]+([\d,.\-()]+)[^0-9\-]+([\d,.\-()]+)",
            html,
        )
        if not m:
            return None
        date = m.group(1)
        fii_net = _num(m.group(4))   # FII: buy, sell, net
        dii_net = _num(m.group(7))   # DII: buy, sell, net
        if fii_net is None or dii_net is None:
            return None
        return _classify(fii_net, dii_net, date, "Moneycontrol (scrape)")
    except Exception:
        return None


def refresh() -> Optional[Dict[str, Any]]:
    """Fetch fresh data (NSE then Moneycontrol) and write the cache. Returns the data or None."""
    data = fetch_from_nse() or fetch_from_moneycontrol()
    if data:
        data["as_of"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass
    return data


def get_fii_dii(max_age_hours: float = 30.0) -> Optional[Dict[str, Any]]:
    """Return the cached FII/DII figure if present and not older than max_age_hours, else None."""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        as_of = data.get("as_of")
        if as_of:
            age = time.time() - time.mktime(time.strptime(as_of, "%Y-%m-%d %H:%M:%S"))
            if age > max_age_hours * 3600:
                return None
        return data
    except Exception:
        return None


if __name__ == "__main__":
    d = refresh()
    if d:
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        print("FII/DII refresh failed (NSE blocked / Moneycontrol layout changed). "
              "NSE usually works from a residential IP.")
