#!/usr/bin/env python3
"""
Read-only Kite Connect check for Phase 0 (docs/verified-facts.md).

Fetches the instrument master and ONE quote (the nearest-expiry NIFTY future, picked
from the master — nothing hardcoded), prints which documented fields are actually
present, and exits. No WebSocket subscription, no orders, nothing written to disk.
The access token is never printed.

Credentials come from the environment only:
  KITE_API_KEY, KITE_ACCESS_TOKEN

Run:  KITE_API_KEY=... KITE_ACCESS_TOKEN=... python3 scripts/verify_kite.py
Exit: 0 = both calls succeeded, 1 = missing credentials, 2 = an API call failed.

Endpoints, headers and documented field lists are from (accessed 2026-11-05):
  https://kite.trade/docs/connect/v3/user/           (Authorization: token api_key:access_token, X-Kite-Version: 3)
  https://kite.trade/docs/connect/v3/market-quotes/  (/instruments CSV columns, /quote fields)
"""

import csv
import io
import os
import sys
from datetime import date

import requests

ROOT = "https://api.kite.trade"
DOC_INSTRUMENT_COLUMNS = ["instrument_token", "exchange_token", "tradingsymbol", "name", "last_price",
                          "expiry", "strike", "tick_size", "lot_size", "instrument_type", "segment", "exchange"]
DOC_QUOTE_FIELDS = ["instrument_token", "timestamp", "last_trade_time", "last_price", "volume", "average_price",
                    "buy_quantity", "sell_quantity", "last_quantity", "ohlc", "net_change",
                    "lower_circuit_limit", "upper_circuit_limit", "oi", "oi_day_high", "oi_day_low", "depth"]


def _report(label, documented, present):
    print(f"\n{label}")
    for f in documented:
        print(f"  {'PRESENT' if f in present else 'MISSING'}  {f}")
    extra = sorted(set(present) - set(documented))
    if extra:
        print(f"  undocumented extras: {', '.join(extra)}")


def main() -> int:
    key, token = os.environ.get("KITE_API_KEY"), os.environ.get("KITE_ACCESS_TOKEN")
    if not (key and token):
        print("Set KITE_API_KEY and KITE_ACCESS_TOKEN in the environment.", file=sys.stderr)
        return 1
    h = {"X-Kite-Version": "3", "Authorization": f"token {key}:{token}"}

    r = requests.get(f"{ROOT}/instruments", headers=h, timeout=60)
    if r.status_code != 200:
        print(f"/instruments failed: HTTP {r.status_code} {r.text[:200]}", file=sys.stderr)
        return 2
    rows = list(csv.DictReader(io.StringIO(r.text)))
    print(f"/instruments: HTTP 200, {len(rows)} rows, Content-Encoding={r.headers.get('Content-Encoding')}")
    _report("Instrument master columns:", DOC_INSTRUMENT_COLUMNS, rows[0].keys() if rows else [])

    today = date.today().isoformat()
    futs = sorted((x for x in rows if x["segment"] == "NFO-FUT" and x["name"] == "NIFTY" and x["expiry"] >= today),
                  key=lambda x: x["expiry"])
    if not futs:
        print("No live NIFTY future found in the master.", file=sys.stderr)
        return 2
    sym = f"NFO:{futs[0]['tradingsymbol']}"
    q = requests.get(f"{ROOT}/quote", params={"i": sym}, headers=h, timeout=15).json()
    if q.get("status") != "success" or sym not in q.get("data", {}):
        print(f"/quote failed: {q.get('error_type')}: {q.get('message')}", file=sys.stderr)
        return 2
    d = q["data"][sym]
    print(f"\n/quote {sym} (lot_size {futs[0]['lot_size']}, expiry {futs[0]['expiry']}): HTTP 200")
    _report("Quote fields:", DOC_QUOTE_FIELDS, d.keys())
    depth = d.get("depth") or {}
    print(f"\n  depth levels: buy={len(depth.get('buy', []))} sell={len(depth.get('sell', []))}")
    print(f"  timestamp={d.get('timestamp')}  last_trade_time={d.get('last_trade_time')}  oi={d.get('oi')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
