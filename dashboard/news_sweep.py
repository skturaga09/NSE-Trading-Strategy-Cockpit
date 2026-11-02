#!/usr/bin/env python3
"""
Morning news sweep — NSE corporate filings on F&O names, tagged by impact and correlated to
the recommendation ledger.

Source: NSE corporate announcements (the official exchange filings feed). Every item already
carries the exact symbol, so there's no name-guessing. On 2026-11-02 a pre-open sweep would
have surfaced FORCEMOT's monthly sales (filed Nov 1), RELIANCE's results transcript (Nov 1
night) and DIXON's results — three of that day's biggest movers.

~300 filings a day are mostly boilerplate (newspaper copies, trading-window notices, meeting
schedules), so items are tagged HIGH only when the category or text names a price-moving
event: results, orders, monthly sales, M&A, corporate actions, regulatory approvals/actions.

Honest limits: a filing explains a move far more often than it predicts one — and it never
says which way. It's context for the ledger and the event-risk gate, not a signal on its own.

Runs off the ledger heartbeat (no scheduled job of its own): rec_ledger.tick() calls sweep()
from 08:00 to 15:30, at most every 30 minutes. Read-only.
"""

import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

DB_PATH = Path(__file__).parent / "journal.db"
IST = ZoneInfo("Asia/Kolkata")
SWEEP_EVERY_SEC = 30 * 60
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# Price-moving filings. Matched against category + text, lower-cased.
HIGH_KEYWORDS = (
    "financial result", "outcome of board meeting", "monthly business update", "sales number",
    "order", "contract", "letter of award", "acquisition", "merger", "amalgamation", "demerger",
    "bonus", "split", "buyback", "buy-back", "dividend", "fund rais", "qip", "preferential issue",
    "credit rating", "usfda", "warning letter", "approval", "resignation of", "insolvency",
    "penalty", "sebi order", "search", "fire", "strike", "lockout", "plant shutdown", "guidance",
)
NOISE_KEYWORDS = ("newspaper publication", "trading window", "compliance certificate",
                  "loss of share certificate", "duplicate share", "schedule of meet",
                  "intimation of schedule", "schedule of analyst")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    an_ts TEXT NOT NULL, symbol TEXT NOT NULL, category TEXT, text TEXT, url TEXT,
    impact TEXT NOT NULL, swept_ts TEXT NOT NULL,
    UNIQUE(symbol, an_ts, category)
);
"""
_LAST = {"t": 0.0}


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _impact(category: str, text: str) -> str:
    """HIGH = names a price-moving event; LOW = boilerplate. Noise wins over a stray keyword
    so 'schedule of meet' for a results call stays LOW."""
    s = f"{category} {text}".lower()
    if any(k in s for k in NOISE_KEYWORDS):
        return "LOW"
    return "HIGH" if any(k in s for k in HIGH_KEYWORDS) else "LOW"


def _ts(an_dt: str) -> Optional[str]:
    """NSE 'an_dt' ('01-Nov-2026 13:02:50') → 'YYYY-MM-DD HH:MM:SS'."""
    try:
        return datetime.strptime(an_dt, "%d-%b-%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def fetch_filings(days: int = 3) -> List[Dict[str, Any]]:
    """NSE corporate announcements over the last `days` (covers weekends). Seeds cookies first —
    NSE rejects cookie-less API calls (same handshake as live_fii_dii.fetch_from_nse)."""
    now = datetime.now(IST)
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept": "application/json, text/plain, */*",
                      "Accept-Language": "en-US,en;q=0.9"})
    try:
        s.get("https://www.nseindia.com/", timeout=10)
        r = s.get("https://www.nseindia.com/api/corporate-announcements",
                  params={"index": "equities", "from_date": (now - timedelta(days=days)).strftime("%d-%m-%Y"),
                          "to_date": now.strftime("%d-%m-%Y")}, timeout=20)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def sweep(days: int = 3) -> Dict[str, Any]:
    """Pull filings, keep F&O names, tag impact, store (deduped). Returns counts."""
    from dashboard.fno_scanner import fno_universe
    universe = set(fno_universe())
    items = fetch_filings(days)
    swept = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    added = high = 0
    with _conn() as c:
        for x in items:
            sym, ts = x.get("symbol"), _ts(x.get("an_dt", ""))
            if sym not in universe or not ts:
                continue
            cat, text = x.get("desc") or "", x.get("attchmntText") or ""
            imp = _impact(cat, text)
            cur = c.execute("INSERT OR IGNORE INTO news_items (an_ts, symbol, category, text, url, impact, swept_ts) "
                            "VALUES (?,?,?,?,?,?,?)", (ts, sym, cat, text[:400], x.get("attchmntFile"), imp, swept))
            added += cur.rowcount
            high += cur.rowcount and imp == "HIGH"
    _LAST["t"] = time.time()
    return {"fetched": len(items), "fno_new": added, "high_new": high}


def maybe_sweep() -> Optional[Dict[str, Any]]:
    """Throttled sweep for the ledger heartbeat: 08:00–15:30 IST weekdays, ≤ once per 30 min."""
    now = datetime.now(IST)
    if now.weekday() >= 5 or not ("08:00" <= now.strftime("%H:%M") <= "15:30"):
        return None
    if time.time() - _LAST["t"] < SWEEP_EVERY_SEC:
        return None
    return sweep()


def since_last_close(impact: Optional[str] = "HIGH") -> List[Dict[str, Any]]:
    """Filings since the previous session's 15:30 (Friday's close on a Monday) — the overnight
    + morning news a trader should see before the open."""
    now = datetime.now(IST)
    prev = now - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    start = prev.strftime("%Y-%m-%d") + " 15:30:00"
    q = "SELECT * FROM news_items WHERE an_ts >= ?" + (" AND impact = ?" if impact else "") + " ORDER BY an_ts DESC"
    with _conn() as c:
        return [dict(r) for r in c.execute(q, (start, impact) if impact else (start,))]


def for_symbols(symbols: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """High-impact filings since the last close, keyed by symbol — for ledger correlation."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    want = set(symbols)
    for n in since_last_close("HIGH"):
        if n["symbol"] in want:
            out.setdefault(n["symbol"], []).append({"ts": n["an_ts"], "category": n["category"], "text": n["text"]})
    return out


def _selfcheck() -> None:
    assert _impact("Monthly Business Updates", "FORCE MOTORS LTD has informed…") == "HIGH"
    assert _impact("Analysts/Institutional Investor Meet/Con", "Transcript of the discussion on the Unaudited Financial Results") == "HIGH"
    assert _impact("Copy of Newspaper Publication", "financial results published") == "LOW"   # noise wins
    assert _impact("Analysts/Institutional Investor Meet/Con", "Schedule of meet") == "LOW"
    assert _impact("Analysts/Institutional Investor Meet/Con",
                   "Intimation of schedule of Analysts meet to discuss financial results") == "LOW"
    assert _impact("Updates", "Intimation of Work Order received") == "HIGH"
    assert _ts("01-Nov-2026 13:02:50") == "2026-11-01 13:02:50"
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        print(sweep())
        for n in since_last_close()[:15]:
            print(f"  {n['an_ts'][5:16]}  {n['symbol']:<11} {n['category'][:36]:<36} | {n['text'][:70]}")
