"""NSE reference files: index constituents, F&O ban list, holiday circulars (edge fetch + pure parse).

URLs and circular checksums come from config (facts F-NSE-2..6). Parsers accept only the format
measured in Phase 2 (verified-facts F-NSE-2..4); anything else raises, so the caller records the source as unverified.
"""

import csv
import io
from datetime import date, datetime

import requests

BAN_HEADER = "Securities in Ban For Trade Date "


def fetch(url: str, user_agent: str, timeout_s: float) -> bytes:
    r = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout_s)
    r.raise_for_status()
    return r.content


def parse_constituents(raw: bytes) -> list[str]:
    """ind_nifty*list.csv: `Company Name,Industry,Symbol,Series,ISIN Code` (F-NSE-2/3) -> symbols."""
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows or "Symbol" not in rows[0]:
        raise ValueError("constituent CSV has no Symbol column")
    syms = [r["Symbol"].strip() for r in rows]
    if not all(syms) or len(set(syms)) != len(syms):
        raise ValueError("constituent CSV has blank or duplicate symbols")
    return syms


def parse_ban(raw: bytes) -> tuple[date, list[str]]:
    """fo_secban.csv (F-NSE-4): `Securities in Ban For Trade Date DD-MON-YYYY:` then `n,SYMBOL` lines."""
    lines = [ln.strip() for ln in raw.decode("utf-8-sig").splitlines() if ln.strip()]
    if not lines or not lines[0].startswith(BAN_HEADER):
        raise ValueError(f"unexpected ban-list header: {lines[:1]}")
    trade_date = datetime.strptime(lines[0][len(BAN_HEADER):].rstrip(":").strip(), "%d-%b-%Y").date()
    syms = []
    for ln in lines[1:]:
        n, _, sym = ln.partition(",")
        if not n.strip().isdigit() or not sym.strip():
            raise ValueError(f"unexpected ban-list row: {ln!r}")  # e.g. an unseen 'NIL' form (Q-UNI-1)
        syms.append(sym.strip())
    return trade_date, syms
