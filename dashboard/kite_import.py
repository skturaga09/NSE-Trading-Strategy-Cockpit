#!/usr/bin/env python3
"""
Import real trades from the live Zerodha Kite account into the outcome journal.

The dashboard cannot route real orders yet, so trades placed directly in Kite are
invisible to the journal. This pulls the account's F&O/intraday positions via Kite
Connect and records them as journal rows (source "Zerodha (live)"), so real trading
gets measured for win-rate and net P&L.

Honest limits: trades placed outside the dashboard carry no signal-feature snapshot
and no protective stop, so they are journaled with an exact net P&L / win-loss but a
NULL R-multiple — they never contaminate the R-based expectancy of dashboard signals.
Equity holdings (long-term investments) are intentionally NOT journaled here.
"""

from typing import Any, Dict

import requests

from dashboard import app as core
from dashboard import journal


def _headers() -> Dict[str, str]:
    kc = core.KITE_CONFIG
    return {"Authorization": f"token {kc.get('api_key','')}:{kc.get('access_token','')}",
            "X-Kite-Version": "3"}


def _is_option(symbol: str) -> bool:
    s = symbol.upper()
    return s.endswith("CE") or s.endswith("PE")


def import_positions() -> Dict[str, Any]:
    """Fetch net positions from Kite and upsert each into the journal.

    Closed round-trips (quantity 0) resolve as realized WIN/LOSS from broker P&L;
    still-open positions are recorded OPEN and resolve on a later re-import."""
    kc = core.KITE_CONFIG
    if not (kc.get("api_key") and kc.get("access_token")):
        return {"success": False, "message": "Kite not connected — connect first.", "imported": 0}
    try:
        r = requests.get("https://api.kite.trade/portfolio/positions",
                         headers=_headers(), timeout=15)
        j = r.json()
    except Exception as e:
        return {"success": False, "message": f"Kite request failed: {e}", "imported": 0}
    if j.get("status") != "success":
        return {"success": False, "message": j.get("message", "Kite error"), "imported": 0}

    imported = closed = still_open = 0
    for p in j["data"].get("net", []):
        sym = p["tradingsymbol"]
        qty = p.get("quantity", 0)
        opt = _is_option(sym)
        oid = f"KITE_{sym}"
        if qty == 0:
            # Closed round-trip: broker gives realized buy/sell avgs + P&L.
            journal.record_external(
                order_id=oid, symbol=sym, source="Zerodha (live)",
                entry_price=p.get("buy_price") or 0.0, qty=int(p.get("buy_quantity") or 0),
                is_option=opt, status="CLOSED", plan_type="positional",
                exit_price=p.get("sell_price") or 0.0, net_pnl=round(p.get("pnl", 0.0), 2))
            closed += 1
        else:
            # Still open: entry = avg price on the held side.
            entry = p.get("buy_price") if qty > 0 else p.get("sell_price")
            journal.record_external(
                order_id=oid, symbol=sym, source="Zerodha (live)",
                entry_price=entry or 0.0, qty=abs(int(qty)), is_option=opt,
                status="OPEN", plan_type="positional")
            still_open += 1
        imported += 1

    return {"success": True, "imported": imported, "closed": closed,
            "open": still_open,
            "message": f"Imported {imported} Kite positions ({closed} closed, {still_open} open)."}


if __name__ == "__main__":
    # Run by the EOD launchd job (~15:45 IST) to capture the day's trades before
    # Kite clears its intraday positions/trades book overnight.
    import json as _json
    import time
    from pathlib import Path

    res = import_positions()
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {_json.dumps(res)}"
    print(line)
    try:
        log_file = Path(__file__).parent / "logs" / "kite_import.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    raise SystemExit(0 if res.get("success") else 1)
