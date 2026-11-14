"""Phase 3 historical backfill: Kite historical candles -> <root>/history.sqlite, then baselines.

  python3 -m engine.backfill [--date YYYY-MM-DD] [--limit N]

Tokens: tier A of that date's universe; spots and futures (an index has no volume). Interval `minute`;
oi=1 only for NFO futures (F-HIST-3). Every row has source='HISTORICAL_API' and lives only in this file,
never next to tick-built candles. Requests go through a token bucket at historical.rate_per_s (F-RATE-2)
and a range check against historical.max_days (F-HIST-5).
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from math import ceil
from typing import Callable

from .baselines import oi_change_distribution, volume_baseline
from .config import EngineConfig, load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS hist_candles (token INTEGER, interval TEXT, ts TEXT, open REAL, high REAL, low REAL,
  close REAL, volume INTEGER, oi INTEGER, source TEXT NOT NULL, fetched_ns INTEGER, PRIMARY KEY (token, interval, ts));
CREATE TABLE IF NOT EXISTS baselines (token INTEGER, as_of TEXT, kind TEXT, n_sessions INTEGER, payload TEXT,
  source TEXT NOT NULL, config_version TEXT, PRIMARY KEY (token, as_of, kind));
"""


class TokenBucket:
    def __init__(self, rate: float, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.rate, self.clock, self.sleep = rate, clock, sleep
        self.tokens, self.t = 1.0, clock()  # capacity 1: never a burst above the rate

    def take(self) -> None:
        now = self.clock()
        self.tokens = min(1.0, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens < 1:
            self.sleep((1 - self.tokens) / self.rate)
            self.t, self.tokens = self.clock(), 1.0
        self.tokens -= 1


def window(cfg: EngineConfig, as_of: date, interval: str = "minute") -> tuple[str, str]:
    """Enough calendar days for N sessions (5 per 7 days, +10 for holidays), within the measured cap."""
    days = ceil(cfg.get("baselines.sessions") * 7 / 5) + 10
    cap = cfg.get("historical.max_days")[interval]
    if days > cap:
        raise ValueError(f"{days} days of {interval} exceed the per-request cap {cap} (F-HIST-5)")
    return (as_of - timedelta(days=days)).isoformat() + " 09:00:00", (as_of - timedelta(days=1)).isoformat() + " 23:59:59"


def backfill(cfg: EngineConfig, session, as_of: date, tokens: dict[int, str], bucket: TokenBucket,
             db: sqlite3.Connection, clock_ns: Callable[[], int] = time.time_ns) -> dict:
    """tokens: {token: kind} with kind 'FUT' or 'EQ'. Returns counts; failures are recorded, never retried silently."""
    db.executescript(SCHEMA)
    start, end = window(cfg, as_of)
    out = {"from": start, "to": end, "ok": 0, "failed": {}, "rows": 0}
    for tok, kind in sorted(tokens.items()):
        oi = kind == "FUT" and "minute" in cfg.get("historical.oi_intervals")
        bucket.take()
        try:
            rows = session.historical(tok, "minute", start, end, oi)
        except Exception as e:  # noqa: BLE001  (recorded per token; the run goes on)
            out["failed"][tok] = repr(e)[:200]
            continue
        now = clock_ns()
        db.executemany("INSERT OR IGNORE INTO hist_candles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       [(tok, "minute", r[0], *r[1:6], r[6] if oi and len(r) > 6 else None, "HISTORICAL_API", now)
                        for r in rows])
        stored = db.execute("SELECT ts, open, high, low, close, volume, oi FROM hist_candles WHERE token=? AND interval='minute'",
                            (tok,)).fetchall()
        n = cfg.get("baselines.sessions")
        vb = volume_baseline(stored, as_of, n)
        put = [(tok, as_of.isoformat(), "volume_by_minute", len(vb["sessions"]), json.dumps(vb))]
        if oi:
            od = oi_change_distribution(stored, as_of, n, cfg.get("baselines.oi_change_windows_min"))
            put.append((tok, as_of.isoformat(), "oi_change_pct", len(od["sessions"]), json.dumps(od)))
        db.executemany("INSERT OR REPLACE INTO baselines VALUES (?,?,?,?,?,'HISTORICAL_API',?)",
                       [(*p, cfg.version) for p in put])
        db.commit()
        out["ok"] += 1
        out["rows"] += len(rows)
    return out


def main(argv=None) -> int:
    from .broker import KiteSession
    from .tiers import tier_a_requests
    from .universe import Registry
    ap = argparse.ArgumentParser(prog="engine.backfill")
    ap.add_argument("--date", default=None)
    ap.add_argument("--limit", type=int, default=None, help="only the first N tokens (smoke runs)")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config) if a.config else load_config()
    as_of = date.fromisoformat(a.date) if a.date else datetime.now().date()
    reg = Registry(cfg)
    try:
        u = reg.get_universe(as_of)
        if "NO_MASTER" in u.flags:
            raise SystemExit(f"no instrument master applied for {as_of}")
        reqs = tier_a_requests(u, lambda t: reg.get_contract(t, as_of), cfg)
    finally:
        reg.close()
    tokens = {r.token: r.kind for r in reqs if r.kind in ("FUT", "EQ")}
    if a.limit:
        tokens = dict(sorted(tokens.items())[:a.limit])
    db = sqlite3.connect(cfg.root / "history.sqlite")
    t0 = time.monotonic()
    res = backfill(cfg, KiteSession.load(), as_of, tokens, TokenBucket(cfg.get("historical.rate_per_s")), db)
    db.close()
    res["seconds"] = round(time.monotonic() - t0, 1)
    res["tokens"] = len(tokens)
    print(json.dumps(res, indent=2, default=str))
    return 0 if not res["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
