"""Phase 11 event gates: the NSE board-meeting calendar (F-EVT-1) and the pure option gate.

Edge: `fetch(cfg, now_ns)` GETs `events.url` with the self-identifying User-Agent (F-NSE-6, no cookies) and stores the raw
bytes + fetch time under `<root>/events/<date>.json`. `status_at(root, as_of, cfg)` reads the latest stored fetch made at or
before as_of (no look-ahead). Pure: `parse(raw)`, `gate(underlying, family, kind, day, status, cfg)`.

Rules (Q-11-8): every board meeting counts, not only results. A LONG OPTION on a stock whose meeting falls within
`events.option_block_trading_days` trading days from the decision day (the meeting day included) => EVENT_IV_RISK; a
future gets the same finding as a warning only. A calendar older than `events.max_age_days`, or none => EVENT_UNVERIFIED
and every option candidate is rejected, index options included. Index options are not gated on constituents' meetings.
A symbol absent from the calendar is NO_KNOWN_EVENT: the minimum notice a company must give is not verified (Q-EVT-1).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .candles import IST, S

VERIFIED, UNVERIFIED = "VERIFIED", "UNVERIFIED"


@dataclass(frozen=True)
class Event:
    symbol: str
    day: date
    purpose: str


@dataclass(frozen=True)
class EventStatus:
    status: str                     # VERIFIED | UNVERIFIED
    reason: str
    fetched_ns: int | None
    sha256: str | None
    source: str
    events: tuple                   # Event, ...


def parse(raw: bytes) -> tuple:
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("event calendar: expected a JSON list")
    return tuple(Event(r["symbol"], datetime.strptime(r["date"], "%d-%b-%Y").date(), r["purpose"]) for r in rows)


def _trading(d: date, cfg) -> bool:
    r = cfg.get("restrictions")
    return d.weekday() < 5 and all(h["date"] != d for h in r["holidays"]) and all(s["date"] != d for s in r["special_sessions"])


def window_end(day: date, cfg) -> date | None:
    """Last calendar day of the block window: `option_block_trading_days` trading days counted from `day` (a trading
    day counts itself). None when that runs into a year without a verified holiday circular."""
    n, d = cfg.get("events.option_block_trading_days"), day
    while True:
        if d.year not in cfg.get("restrictions.holiday_years"):
            return None
        if _trading(d, cfg):
            n -= 1
            if n <= 0:
                return d
        d += timedelta(1)


def gate(underlying: str, family: str, kind: str, day: date, st: EventStatus | None, cfg) -> tuple[str | None, str | None]:
    """-> (reason that rejects a long option, warning). kind: FUT | CE | PE; family: INDEX | STOCK."""
    opt = kind in ("CE", "PE")
    if st is None or st.status != VERIFIED:
        why = "no calendar supplied" if st is None else st.reason
        return (f"EVENT_UNVERIFIED: {why}", None) if opt else (None, f"EVENT_UNVERIFIED: {why}")
    if family == "INDEX":
        return None, None
    end = window_end(day, cfg)
    if end is None:
        why = f"EVENT_UNVERIFIED: block window from {day} runs into a year without a verified holiday circular"
        return (why, None) if opt else (None, why)
    hits = [e for e in st.events if e.symbol == underlying and day <= e.day <= end]
    if not hits:
        return None, None
    what = "; ".join(f"board meeting {e.day} ({e.purpose})" for e in sorted(hits, key=lambda e: e.day))
    msg = f"EVENT_IV_RISK: {what} within {cfg.get('events.option_block_trading_days')} trading days of {day}"
    return (msg, None) if opt else (None, msg + " (futures allowed: warning only)")


# ---------------------------------------------------------------- edge
def fetch(cfg, now_ns: int, get=None) -> Path:
    """GET the calendar and store it. `get(url, headers, timeout) -> (status, bytes)` is injectable for tests."""
    if get is None:
        import requests

        def get(url, headers, timeout):
            r = requests.get(url, headers=headers, timeout=timeout)
            return r.status_code, r.content
    status, raw = get(cfg.get("events.url"), {"User-Agent": cfg.get("http.user_agent")}, cfg.get("http.timeout_s"))
    if status != 200:
        raise RuntimeError(f"event calendar HTTP {status}")
    parse(raw)                                  # refuse to store something that does not parse
    day = datetime.fromtimestamp(now_ns / S, IST).date()
    out = cfg.root / "events" / f"{day}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_ns": now_ns, "url": cfg.get("events.url"), "sha256": hashlib.sha256(raw).hexdigest(),
                               "raw": raw.decode("utf-8")}))
    tmp.replace(out)
    return out


def status_at(root: Path, as_of: int, cfg) -> EventStatus:
    day = datetime.fromtimestamp(as_of / S, IST).date()
    oldest = day - timedelta(cfg.get("events.max_age_days"))
    src = cfg.get("events.url")
    for f in sorted((Path(root) / "events").glob("*.json"), reverse=True):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d["fetched_ns"] > as_of:
            continue
        fetched = datetime.fromtimestamp(d["fetched_ns"] / S, IST).date()
        if fetched < oldest:
            break
        try:
            evs = parse(d["raw"].encode())
        except (ValueError, KeyError) as e:
            return EventStatus(UNVERIFIED, f"stored calendar {f.name} does not parse: {e}", d["fetched_ns"], d.get("sha256"), src, ())
        return EventStatus(VERIFIED, f"NSE event calendar fetched {datetime.fromtimestamp(d['fetched_ns'] / S, IST):%Y-%m-%d %H:%M} IST",
                           d["fetched_ns"], d["sha256"], src, evs)
    return EventStatus(UNVERIFIED, f"no calendar fetched between {oldest} and the decision time", None, None, src, ())


def main(argv=None) -> int:
    import argparse
    import time

    from .options import load
    ap = argparse.ArgumentParser(prog="engine.events", description="fetch and store today's NSE event calendar")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    cfg = load(a.config) if a.config else load()
    p = fetch(cfg, time.time_ns())
    print(json.dumps({"stored": str(p), "events": len(parse(json.loads(p.read_text())["raw"].encode()))}))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
