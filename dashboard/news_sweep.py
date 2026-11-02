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

import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from zoneinfo import ZoneInfo

import requests

_SKILL = Path(__file__).resolve().parent.parent / "skills" / "india-news-tracker" / "scripts"

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
    # analyst / flow actions — mostly in headlines, not filings
    "upgrade", "downgrade", "target price", "buy rating", "sell rating", "outperform", "underperform",
    "block deal", "bulk deal", "stake sale", "stake buy",
    # results as headlines word them (filings say "financial result")
    "q1 result", "q2 result", "q3 result", "q4 result", "q1:", "q2:", "q3:", "q4:", "earnings",
    "net profit", "net loss", "profit jumps", "profit rises", "profit surges", "profit falls",
    "profit slides", "profit declines", "profit drops",
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


# --- RSS headlines -----------------------------------------------------------------------
# Headlines name companies, not symbols, so they're tagged by company name. Kite's names are
# abbreviated ("DIXON TECHNO (INDIA)", "INDIAN ENERGY EXC", "DIVI S LABORATORIES"), so each is
# normalised and reduced to a distinctive key phrase that a real headline will contain.
_SUFFIX = {"ltd", "limited", "india", "i", "corp", "corporation", "co", "company"}
_GENERIC_FIRST = {"bank", "state", "indian", "national", "the", "power", "oil", "hindustan", "bharat",
                  "union", "central", "punjab", "general", "indus", "new", "great", "tata", "adani", "aditya"}
_NAMES: Dict[str, Any] = {"day": None, "phrases": {}, "words": {}, "symbols": set()}


def _norm(s: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", s.lower())          # drop "(india)", "(i)"
    s = re.sub(r"[^a-z0-9& ]+", " ", s)               # "divi's" → "divi s"; keep "&" for l&t, m&m
    return re.sub(r"\s+", " ", s).strip()


def _name_map() -> Dict[str, Any]:
    """Company-name keys → F&O symbol for all F&O names (Kite NSE master) plus the news skill's
    hand-made aliases ('infy', 'sbi', …). Multi-word keys match as a phrase, single words as a
    whole word. Cached per day. shortcut: keyword matching — expect some misses and the odd
    false hit; upgrade to an LLM/NER tagger if precision becomes a problem."""
    today = date.today().isoformat()
    if _NAMES["day"] == today and _NAMES["phrases"]:
        return _NAMES
    import csv
    import io
    from dashboard.fno_scanner import fno_universe
    from dashboard.option_chain import _headers
    universe = set(fno_universe())
    phrases: Dict[str, str] = {}
    words: Dict[str, str] = {}
    try:
        txt = requests.get("https://api.kite.trade/instruments/NSE", headers=_headers(), timeout=30).text
        for r in csv.DictReader(io.StringIO(txt)):
            if r.get("instrument_type") != "EQ" or r.get("tradingsymbol") not in universe:
                continue
            full = _norm(r.get("name") or "").split()
            w = [x for x in full if x not in _SUFFIX]
            if not w:
                continue
            if len(w) == 1:
                if len(w[0]) >= 4:                    # short single words collide with ordinary text
                    words[w[0]] = r["tradingsymbol"]
                continue
            key = w if w[0] in _GENERIC_FIRST else w[:2]   # generic lead ("bank of baroda") → full name
            if key[-1] in ("of", "and", "&"):              # "bank of" would hit Bank of England → keep "bank of india"
                key = full
            phrases[" ".join(key)] = r["tradingsymbol"]
    except Exception:
        pass
    try:
        sys.path.insert(0, str(_SKILL))
        import news_fetcher as nf
        for k, v in nf.STOCK_NAME_TO_SYMBOL.items():
            if v in universe:
                (phrases if " " in k else words)[_norm(k)] = v
    except Exception:
        pass
    _NAMES.update({"day": today, "phrases": phrases, "words": words, "symbols": universe})
    return _NAMES


def _tag(title: str, summary: str = "") -> Set[str]:
    """F&O symbols a headline is about: company-name keys, plus a bare ticker written in caps."""
    m = _name_map()
    # RBI is named in half of all market news and contains "bank of india" — neutralise it first.
    text = " " + _norm(f"{title} {summary}").replace("reserve bank of india", "rbi") + " "
    hits: Set[str] = set()
    # Phrases match from a word start (Kite's truncated "dixon techno" must hit "dixon technologies"),
    # longest first, consuming the span so "state bank of india" can't also count as "bank of india".
    for ph in sorted(m["phrases"], key=len, reverse=True):
        i = text.find(f" {ph}")
        if i >= 0:
            hits.add(m["phrases"][ph])
            text = text[:i + 1] + "#" * len(ph) + text[i + 1 + len(ph):]
    hits |= {sym for wd, sym in m["words"].items() if f" {wd} " in text}
    hits |= {s for s in m["symbols"] if len(s) >= 3 and s.isalpha() and re.search(rf"\b{s}\b", title)}
    return hits


def fetch_headlines() -> List[Any]:
    """Today's headlines from the news skill's RSS feeds (Moneycontrol, ET, Mint, BS, NDTV
    Profit) — parsed and de-duplicated by the skill. Needs feedparser."""
    try:
        sys.path.insert(0, str(_SKILL))
        import news_fetcher as nf
        if not nf.HAS_FEEDPARSER:
            return []
        return nf.fetch_rss_feeds(days_back=1)
    except Exception:
        return []


def _rss_ts(published: str) -> str:
    try:
        return parsedate_to_datetime(published).astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def sweep(days: int = 3) -> Dict[str, Any]:
    """Pull NSE filings + RSS headlines, keep F&O names, tag impact, store (deduped)."""
    from dashboard.fno_scanner import fno_universe
    universe = set(fno_universe())
    items = fetch_filings(days)
    heads = fetch_headlines()
    swept = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    added = high = tagged = 0
    with _conn() as c:
        def put(ts, sym, cat, text, url, imp):
            nonlocal added, high
            cur = c.execute("INSERT OR IGNORE INTO news_items (an_ts, symbol, category, text, url, impact, swept_ts) "
                            "VALUES (?,?,?,?,?,?,?)", (ts, sym, cat, text[:400], url, imp, swept))
            added += cur.rowcount
            high += cur.rowcount and imp == "HIGH"
        for x in items:
            sym, ts = x.get("symbol"), _ts(x.get("an_dt", ""))
            if sym in universe and ts:
                cat, text = x.get("desc") or "", x.get("attchmntText") or ""
                put(ts, sym, cat, text, x.get("attchmntFile"), _impact(cat, text))
        for h in heads:
            syms = _tag(h.title, h.summary)
            tagged += bool(syms)
            text = f"{h.title} — {h.summary}" if h.summary else h.title
            for sym in syms:
                put(_rss_ts(h.published), sym, f"Headline · {h.source}", text, h.link, _impact("", text))
    _LAST["t"] = time.time()
    return {"filings": len(items), "headlines": len(heads), "headlines_on_fno": tagged,
            "fno_new": added, "high_new": high}


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
    assert _impact("", "Jefferies upgrades Bosch, raises target price") == "HIGH"
    # tagging against a fixed map (no network)
    _NAMES.update({"day": date.today().isoformat(), "symbols": {"DIXON", "IEX", "BOSCHLTD", "SBIN", "BANKINDIA"},
                   "phrases": {"dixon techno": "DIXON", "indian energy exc": "IEX",
                               "state bank of india": "SBIN", "bank of india": "BANKINDIA"},
                   "words": {"bosch": "BOSCHLTD"}})
    assert _tag("Dixon Technologies shares jump 12% on Q2 beat") == {"DIXON"}
    assert _tag("Indian Energy Exchange volumes rise") == {"IEX"}
    assert _tag("State Bank of India raises lending rates") == {"SBIN"}          # longer name wins
    assert _tag("Bank of India Q2 profit jumps") == {"BANKINDIA"}
    assert _tag("Reserve Bank of India holds repo rate") == set()                # RBI is not BANKINDIA
    assert _tag("Goldman expects Bank of England to raise rates") == set()
    assert _impact("", "Marico Q2 Results: Profit Jumps 31%") == "HIGH"
    assert _tag("Bosch Q2 results") == {"BOSCHLTD"}
    assert _tag("Boschetti opens restaurant") == set()          # whole-word only
    assert _tag("Markets: IEX, DIXON lead gains") == {"IEX", "DIXON"}   # bare tickers in caps
    _NAMES["day"] = None
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        print(sweep())
        for n in since_last_close()[:15]:
            print(f"  {n['an_ts'][5:16]}  {n['symbol']:<11} {n['category'][:36]:<36} | {n['text'][:70]}")
