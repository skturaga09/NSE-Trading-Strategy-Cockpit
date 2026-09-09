#!/usr/bin/env python3
"""
Daily F&O NAV snapshotter. Records the REAL F&O account value once per day so the Journal can
draw a true, daily-marked NAV over time (like Zerodha), with its composition:

  overall fund value (NAV) = free cash + current market value of open F&O positions
    where  invested   = cost basis of open positions (Σ buy_price×qty, long)
           open_mtm   = Σ position unrealized P&L  (current value − invested)
           realized   = cumulative booked P&L to date (from the journal)

Appends one JSON line per day to fno_nav_history.jsonl (same-day re-runs overwrite that day).
Read-only against Kite; no orders. Runs EOD via launchd; safe to run any time.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

_HIST = Path(__file__).parent / "fno_nav_history.jsonl"
_FNO_EXCHANGES = {"NFO", "MCX", "BFO", "CDS"}   # F&O segments (equity/commodity/currency derivatives)


def _ist_today() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def snapshot() -> Dict[str, Any]:
    """Compute today's F&O fund value + composition from live Kite data and persist it."""
    import requests
    from dashboard.option_chain import _headers
    from dashboard import journal
    try:
        m = requests.get("https://api.kite.trade/user/margins", headers=_headers(), timeout=10).json()
        if m.get("status") != "success":
            return {"success": False, "error": "margins unavailable"}
        eq = m["data"].get("equity", {})
        cash = float((eq.get("available") or {}).get("live_balance") or 0.0)

        pos = requests.get("https://api.kite.trade/portfolio/positions", headers=_headers(), timeout=10).json()
        net = (pos.get("data") or {}).get("net", []) if pos.get("status") == "success" else []
        invested = current_value = open_mtm = 0.0
        for p in net:
            if (p.get("exchange") or "").upper() not in _FNO_EXCHANGES:
                continue
            qty = p.get("quantity") or 0
            if qty == 0:
                continue                              # closed today — no open exposure
            ltp = p.get("last_price") or 0.0
            buy = p.get("buy_price") or p.get("average_price") or 0.0
            current_value += ltp * qty
            invested += buy * abs(qty)
            open_mtm += p.get("pnl") or 0.0

        realized = round(sum(v for v in journal.daily_pnl().values()), 2)
        nav = round(cash + current_value, 2)
        rec = {"date": _ist_today(), "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "nav": nav, "cash": round(cash, 2), "invested": round(invested, 2),
               "current_value": round(current_value, 2), "open_mtm": round(open_mtm, 2),
               "realized_to_date": realized, "open_positions": sum(1 for p in net if (p.get("quantity") or 0) != 0)}
        _append(rec)
        return {"success": True, **rec}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _append(rec: Dict[str, Any]) -> None:
    rows = [r for r in history() if r.get("date") != rec["date"]]   # overwrite same-day
    rows.append(rec)
    rows.sort(key=lambda r: r["date"])
    try:
        _HIST.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    except Exception:
        pass


def history() -> List[Dict[str, Any]]:
    if not _HIST.exists():
        return []
    out = []
    for line in _HIST.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2))
