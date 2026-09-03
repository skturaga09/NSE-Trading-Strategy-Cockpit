#!/usr/bin/env python3
"""
Journal LEARNING layer for the overnight OI-buildup swing signal.

Records EVERY overnight candidate the board surfaces (traded or not), then resolves its
next-day outcome — did it gap in the signalled direction, and how far did it run — so the
platform can measure whether the signal has real edge, split by tier (strong/notable) and
side (long/short).

Design honesty (anti-overfitting):
  - Tracks the SIGNAL, not just executed trades, so the sample grows every session and
    measures the edge cleanly, independent of what you happened to trade.
  - Reports are SAMPLE-SIZE GATED: below MIN_SAMPLE the harness says "accumulating", never
    a verdict — a handful of lucky/unlucky days must not masquerade as an edge.
  - Resolution uses only FULLY SETTLED next-day candles (never a partial, mid-session one).
  - It MEASURES; it does NOT auto-tune the thresholds. Turning a measured edge into a
    changed rule stays a deliberate, human decision.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "journal.db"
_LOCK = threading.Lock()
MIN_SAMPLE = 30   # below this many resolved signals, report "accumulating", not a verdict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS swing_signals (
    signal_date    TEXT,
    symbol         TEXT,
    bias           TEXT,     -- LONG | SHORT
    oi_chg_pct     REAL,
    tier           TEXT,     -- strong | notable
    close_pct      REAL,     -- day % change at signal
    vs_vwap_pct    REAL,
    range_pos      REAL,
    ref_price      REAL,     -- price when surfaced (near close)
    rel_volume     REAL,     -- today's volume / ~20-day avg (ignition footprint)
    ignition_score REAL,     -- 0..100 ignition composite, when it was an ignition pick
    is_ignition    INTEGER DEFAULT 0,
    created_at     TEXT,
    status         TEXT DEFAULT 'OPEN',   -- OPEN | RESOLVED
    next_date      TEXT,
    next_open      REAL, next_high REAL, next_low REAL, next_close REAL,
    gap_pct        REAL,     -- direction-adjusted open gap vs ref
    fwd_return_pct REAL,     -- direction-adjusted close-to-close
    mfe_pct        REAL,     -- direction-adjusted best excursion next day (max opportunity)
    worked         INTEGER,  -- 1 if gap_pct > 0 (gapped in your favour)
    resolved_at    TEXT,
    PRIMARY KEY (signal_date, symbol, bias)
);
"""


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


def init() -> None:
    with _LOCK, _conn() as c:
        c.executescript(_SCHEMA)
        # Migrate older DBs that predate the ignition columns (ADD COLUMN is a no-op
        # error once present, so swallow it).
        for col, decl in (("rel_volume", "REAL"), ("ignition_score", "REAL"),
                          ("is_ignition", "INTEGER DEFAULT 0")):
            try:
                c.execute(f"ALTER TABLE swing_signals ADD COLUMN {col} {decl}")
            except Exception:
                pass


init()


def record_signals(scan: Dict[str, Any]) -> int:
    """Snapshot today's overnight board as OPEN signals. Idempotent per day (first write
    per symbol+side wins), so the 15:15 EOD job and any on-demand test coexist safely."""
    if not scan or not scan.get("is_live"):
        return 0
    today = date.today().isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    # The primary OI-bar boards keep their OI tier (strong/notable); the secondary
    # "building" boards (fresh buildup under the bar + strong close, e.g. SOLARINDS) are
    # tagged tier='building' so the learning can measure that group on its own.
    groups = (
        ("LONG", "overnight_longs", None), ("SHORT", "overnight_shorts", None),
        ("LONG", "building_longs", "building"), ("SHORT", "building_shorts", "building"),
    )
    with _LOCK, _conn() as c:
        for bias, key, tier_override in groups:
            for cand in scan.get(key) or []:
                b = cand.get("buildup") or {}
                cur = c.execute(
                    "INSERT OR IGNORE INTO swing_signals "
                    "(signal_date, symbol, bias, oi_chg_pct, tier, close_pct, vs_vwap_pct, "
                    " range_pos, ref_price, rel_volume, created_at, status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'OPEN')",
                    (today, cand["symbol"], bias, b.get("oi_chg_pct"), tier_override or b.get("tier"),
                     cand.get("pct_change"), cand.get("vs_vwap_pct"), cand.get("range_pos"),
                     cand.get("ltp"), b.get("rel_volume"), now))
                n += cur.rowcount
        # Ignition pass — UPSERT so an ignition name is flagged even when another board
        # already recorded it this day, and inserted fresh when it's ignition-only.
        for cand in scan.get("ignition") or []:
            ig = cand.get("ignition") or {}
            b = cand.get("buildup") or {}
            c.execute(
                "INSERT INTO swing_signals "
                "(signal_date, symbol, bias, oi_chg_pct, tier, close_pct, vs_vwap_pct, range_pos, "
                " ref_price, rel_volume, ignition_score, is_ignition, created_at, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?, 'OPEN') "
                "ON CONFLICT(signal_date, symbol, bias) DO UPDATE SET "
                " is_ignition=1, ignition_score=excluded.ignition_score, rel_volume=excluded.rel_volume",
                (today, cand["symbol"], ig.get("bias", "LONG"), b.get("oi_chg_pct"), b.get("tier"),
                 cand.get("pct_change"), cand.get("vs_vwap_pct"), cand.get("range_pos"),
                 cand.get("ltp"), ig.get("rel_volume"), ig.get("score"), now))
    return n


def resolve_due() -> int:
    """Resolve OPEN signals whose next trading day has FULLY SETTLED, using that day's
    OHLC. Never uses a partial (still-forming) candle. Cheap & idempotent — only touches
    unresolved rows, and daily candles are cached per day."""
    from dashboard import swing_scan
    today = date.today().isoformat()
    market_open = swing_scan._market_open_now()
    with _LOCK, _conn() as c:
        due = c.execute("SELECT * FROM swing_signals WHERE status='OPEN' AND signal_date < ?",
                        (today,)).fetchall()
    if not due:
        return 0
    futmap = swing_scan._futures_map()
    bysym: Dict[str, List[sqlite3.Row]] = {}
    for r in due:
        bysym.setdefault(r["symbol"], []).append(r)

    updates: List[tuple] = []
    for sym, rows in bysym.items():
        fut = futmap.get(sym)
        if not fut:
            continue
        candles = swing_scan._daily_candles(fut["token"], days=30)  # [ts,o,h,l,c,vol,oi]
        by_date = {cd[0][:10]: cd for cd in candles if cd and cd[0]}
        dates_sorted = sorted(by_date)
        for r in rows:
            nxt = next((d for d in dates_sorted if d > r["signal_date"]), None)
            if not nxt:
                continue                       # next session not traded yet
            # Only resolve on a fully-settled day: a past date, or today AFTER close.
            if nxt == today and market_open:
                continue
            if nxt > today:
                continue
            cd = by_date[nxt]
            o, h, l, cl = cd[1], cd[2], cd[3], cd[4]
            ref = r["ref_price"]
            if not ref:
                continue
            d = 1 if r["bias"] == "LONG" else -1
            gap = (o - ref) / ref * 100 * d
            fwd = (cl - ref) / ref * 100 * d
            mfe = ((h - ref) if d == 1 else (ref - l)) / ref * 100
            updates.append((nxt, o, h, l, cl, round(gap, 2), round(fwd, 2), round(mfe, 2),
                            1 if gap > 0 else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            r["signal_date"], r["symbol"], r["bias"]))
    if not updates:
        return 0
    with _LOCK, _conn() as c:
        c.executemany(
            "UPDATE swing_signals SET status='RESOLVED', next_date=?, next_open=?, next_high=?, "
            "next_low=?, next_close=?, gap_pct=?, fwd_return_pct=?, mfe_pct=?, worked=?, resolved_at=? "
            "WHERE signal_date=? AND symbol=? AND bias=?", updates)
    return len(updates)


def _agg(rows: List[sqlite3.Row]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "hit_rate": None, "avg_gap": None, "avg_fwd": None, "avg_mfe": None,
                "sufficient": False}
    worked = sum(1 for r in rows if r["worked"])
    return {
        "n": n,
        "hit_rate": round(worked / n * 100, 1),           # % that gapped in your favour
        "avg_gap": round(sum(r["gap_pct"] or 0 for r in rows) / n, 2),
        "avg_fwd": round(sum(r["fwd_return_pct"] or 0 for r in rows) / n, 2),
        "avg_mfe": round(sum(r["mfe_pct"] or 0 for r in rows) / n, 2),
        "sufficient": n >= MIN_SAMPLE,
    }


def stats() -> Dict[str, Any]:
    """Aggregate resolved signals. hit_rate = % that gapped in the signalled direction
    (the core assumption); compare to a 50% coin-flip. Split by tier and side."""
    with _LOCK, _conn() as c:
        res = c.execute("SELECT * FROM swing_signals WHERE status='RESOLVED'").fetchall()
        open_n = c.execute("SELECT COUNT(*) AS n FROM swing_signals WHERE status='OPEN'").fetchone()["n"]
    return {
        "min_sample": MIN_SAMPLE,
        "coinflip": 50.0,
        "overall": _agg(res),
        "by_tier": {t: _agg([r for r in res if r["tier"] == t]) for t in ("strong", "notable", "building")},
        "by_bias": {b: _agg([r for r in res if r["bias"] == b]) for b in ("LONG", "SHORT")},
        "ignition": _agg([r for r in res if (r["is_ignition"] if "is_ignition" in r.keys() else 0)]),
        "open_pending": open_n,
    }


def recent(limit: int = 40) -> List[Dict[str, Any]]:
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT * FROM swing_signals ORDER BY signal_date DESC, worked DESC, symbol LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]
