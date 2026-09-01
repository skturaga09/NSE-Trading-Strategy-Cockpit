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

    # Record only OPEN positions here; CLOSED trades come from import_trades()
    # (reconstructed from actual fills) to avoid double-counting.
    still_open = 0
    open_syms: List[str] = []
    for p in j["data"].get("net", []):
        sym = p["tradingsymbol"]
        qty = p.get("quantity", 0)
        if qty == 0:
            continue
        entry = p.get("buy_price") if qty > 0 else p.get("sell_price")
        journal.record_external(
            order_id=f"KITE_{sym}", symbol=sym, source="Zerodha (live)",
            entry_price=entry or 0.0, qty=abs(int(qty)), is_option=_is_option(sym),
            status="OPEN", plan_type="positional")
        open_syms.append(sym)
        still_open += 1

    # Drop stale imported OPEN rows for positions that are no longer open.
    cleaned = journal.close_stale_external(open_syms)
    return {"success": True, "open": still_open, "cleaned": cleaned,
            "message": f"Imported {still_open} open Kite positions (cleaned {cleaned} stale)."}


def import_trades() -> Dict[str, Any]:
    """Reconstruct CLOSED round-trips from Kite NET POSITIONS (a flat position — net
    quantity 0 with fills on both sides — is a fully round-tripped trade).

    Why positions and not /trades: /trades holds only *today's* fills, so a trade
    OPENED on a prior day and CLOSED today shows just its closing leg there and was
    silently dropped (it's neither a same-day round-trip nor a still-open position).
    The net-positions endpoint carries the overnight opening leg in its buy/sell
    quantities and values, so this captures both same-day and multi-day closes.
    P&L = sell_value − buy_value, from Kite's own figures.

    A partially-closed position (still net non-zero) stays OPEN and is journaled as a
    closed trade only once it is fully flat."""
    kc = core.KITE_CONFIG
    if not (kc.get("api_key") and kc.get("access_token")):
        return {"success": False, "message": "Kite not connected.", "closed": 0}
    try:
        j = requests.get("https://api.kite.trade/portfolio/positions",
                         headers=_headers(), timeout=15).json()
    except Exception as e:
        return {"success": False, "message": f"Kite request failed: {e}", "closed": 0}
    if j.get("status") != "success":
        return {"success": False, "message": j.get("message", "Kite error"), "closed": 0}

    from datetime import date as _date
    today = _date.today().isoformat().replace("-", "")
    closed = 0
    for p in j["data"].get("net", []):
        sym = p["tradingsymbol"]
        bq = float(p.get("buy_quantity") or 0)
        sq = float(p.get("sell_quantity") or 0)
        # Flat (net 0) and traded on BOTH sides = a fully round-tripped closed trade,
        # regardless of whether the opening leg was today or a prior session.
        if p.get("quantity", 0) != 0 or bq <= 0 or sq <= 0:
            continue
        bv = float(p.get("buy_value") or 0)
        sv = float(p.get("sell_value") or 0)
        qty = int(min(bq, sq))
        entry = bv / bq if bq else 0.0
        exit_ = sv / sq if sq else 0.0
        pnl = sv - bv                          # Kite's own values; == its `pnl` field
        # Carry over the entry-feature snapshot (regime etc.) the monitor captured
        # on the open row, so the closed trade is learnable by the calibration brain.
        feats = journal.get_entry_features(f"KITE_{sym}")
        journal.record_external(
            order_id=f"KITETRADE_{sym}_{today}", symbol=sym, source="Zerodha (live)",
            entry_price=round(entry, 2), qty=qty, is_option=_is_option(sym),
            status="CLOSED", plan_type="intraday" if p.get("product") == "MIS" else "positional",
            exit_price=round(exit_, 2), net_pnl=round(pnl, 2),
            regime=feats.get("regime"), sector=feats.get("sector"), bias_score=feats.get("bias_score"))
        closed += 1
    return {"success": True, "closed": closed,
            "message": f"Reconstructed {closed} closed round-trips from net positions."}


def run_eod() -> Dict[str, Any]:
    """EOD job: accurate closed round-trips from fills, then the open snapshot."""
    trades = import_trades()
    positions = import_positions()
    return {"success": trades.get("success") and positions.get("success"),
            "trades": trades, "positions": positions}


if __name__ == "__main__":
    # Run by the EOD launchd job (~15:45 IST) before Kite clears the day's book.
    import json as _json
    import time
    from pathlib import Path

    res = run_eod()
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
