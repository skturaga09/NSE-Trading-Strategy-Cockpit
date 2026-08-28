#!/usr/bin/env python3
"""
Trade Outcome Journal — the immutable analytics record behind signal evaluation.

Separate from trade_book.json (live positions): this SQLite journal captures each
trade's SIGNAL FEATURES at entry and resolves its OUTCOME over time (R-multiple,
max favorable/adverse excursion, hold time, win/loss). It's the ground truth the
attribution + calibration harness needs — you can't auto-correct what you don't
measure.

Everything is in R-multiples where possible (R = risk per share = entry − stop),
so edge is comparable across symbols and price levels. Expectancy in R is the
honest edge metric; win rate alone is not.
"""

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "journal.db"
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_journal (
    order_id            TEXT PRIMARY KEY,
    ts_entry            TEXT,
    source              TEXT,
    symbol              TEXT,
    is_option           INTEGER,
    plan_type           TEXT,          -- positional | intraday
    entry_price         REAL,
    stop                REAL,
    target              REAL,
    qty                 INTEGER,
    -- signal snapshot at entry
    conviction          REAL,
    composite_score     REAL,
    trend_score         REAL,
    rs                  REAL,
    distance_to_pivot_pct REAL,
    sector              TEXT,
    regime              TEXT,
    bias_score          REAL,
    is_live             INTEGER,
    -- resolved outcome
    ts_exit             TEXT,
    exit_price          REAL,
    exit_reason         TEXT,          -- TARGET | STOP | MANUAL | TIME
    r_multiple          REAL,
    net_pnl             REAL,
    net_pnl_pct         REAL,
    mfe_r               REAL,          -- max favorable excursion, in R
    mae_r               REAL,          -- max adverse excursion, in R (<=0)
    holding_mins        REAL,
    outcome             TEXT,          -- WIN | LOSS | BREAKEVEN
    status              TEXT DEFAULT 'OPEN',
    peak_price          REAL,
    trough_price        REAL
);

-- Decision log for the intraday discipline console: every verdict (including
-- NO TRADE / WAIT / STOP), not just executed trades. A disciplined NO-TRADE is
-- a successful outcome, so the process-quality record must capture it.
CREATE TABLE IF NOT EXISTS decision_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT,
    underlying      TEXT,
    expiry          TEXT,
    regime          TEXT,
    setup           TEXT,
    direction       TEXT,
    verdict         TEXT,          -- STOP_DAY | INSUFFICIENT_DATA | NO_TRADE | WAIT | CANDIDATE
    decision        TEXT,          -- human label
    gates_failed    TEXT,
    planned_entry   REAL,
    planned_stop    REAL,
    planned_target  REAL,
    planned_risk    REAL,
    permitted_lots  INTEGER
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
    c.row_factory = sqlite3.Row
    # Ensure the schema on every connection (idempotent) so the journal stays
    # resilient if journal.db is deleted/reset while the server is running.
    c.executescript(_SCHEMA)
    return c


def init() -> None:
    with _LOCK, _conn() as c:
        c.executescript(_SCHEMA)


init()


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def record_entry(order_id: str, symbol: str, entry_price: float, stop: Optional[float],
                 target: Optional[float], qty: int, source: str, is_option: bool,
                 signal: Optional[Dict[str, Any]] = None) -> None:
    """Insert a journal row at trade placement, snapshotting the signal features."""
    sig = signal or {}
    row = {
        "order_id": order_id,
        "ts_entry": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source, "symbol": symbol, "is_option": int(is_option),
        "plan_type": sig.get("plan_type", "positional"),
        "entry_price": entry_price, "stop": stop, "target": target, "qty": qty,
        "conviction": _num(sig.get("conviction")), "composite_score": _num(sig.get("composite_score")),
        "trend_score": _num(sig.get("trend_score")), "rs": _num(sig.get("rs")),
        "distance_to_pivot_pct": _num(sig.get("distance_to_pivot_pct")),
        "sector": sig.get("sector"), "regime": sig.get("regime"),
        "bias_score": _num(sig.get("bias_score")), "is_live": int(bool(sig.get("is_live", False))),
        "peak_price": entry_price, "trough_price": entry_price, "status": "OPEN",
    }
    cols = ", ".join(row.keys())
    ph = ", ".join(["?"] * len(row))
    with _LOCK, _conn() as c:
        c.execute(f"INSERT OR IGNORE INTO trade_journal ({cols}) VALUES ({ph})", list(row.values()))


def update_excursion(order_id: str, ltp: float) -> None:
    """Track the running high/low while a trade is open (for MFE/MAE)."""
    if not ltp or ltp <= 0:
        return
    with _LOCK, _conn() as c:
        c.execute(
            "UPDATE trade_journal SET peak_price=MAX(peak_price, ?), trough_price=MIN(trough_price, ?) "
            "WHERE order_id=? AND status='OPEN'",
            (ltp, ltp, order_id),
        )


def finalize(order_id: str, exit_price: float, exit_reason: str) -> None:
    """Resolve a trade's outcome: R-multiple, MFE/MAE in R, P&L, win/loss, hold time."""
    with _LOCK, _conn() as c:
        r = c.execute("SELECT * FROM trade_journal WHERE order_id=? AND status='OPEN'", (order_id,)).fetchone()
        if not r:
            return
        entry = r["entry_price"]
        stop = r["stop"] if r["stop"] else entry * 0.98  # fallback risk if no stop set
        risk = max(entry - stop, 1e-9)  # per-share risk (long)
        qty = r["qty"] or 1
        peak = r["peak_price"] or exit_price
        trough = r["trough_price"] or exit_price
        r_mult = (exit_price - entry) / risk
        mfe_r = (peak - entry) / risk
        mae_r = (trough - entry) / risk
        net_pnl = (exit_price - entry) * qty
        net_pnl_pct = (exit_price / entry - 1.0) * 100.0 if entry else 0.0
        outcome = "WIN" if net_pnl > 0 else ("LOSS" if net_pnl < 0 else "BREAKEVEN")
        try:
            t0 = datetime.strptime(r["ts_entry"], "%Y-%m-%d %H:%M:%S")
            holding = (datetime.now() - t0).total_seconds() / 60.0
        except Exception:
            holding = None
        c.execute(
            "UPDATE trade_journal SET status='CLOSED', ts_exit=?, exit_price=?, exit_reason=?, "
            "r_multiple=?, net_pnl=?, net_pnl_pct=?, mfe_r=?, mae_r=?, holding_mins=?, outcome=? "
            "WHERE order_id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), round(exit_price, 2), exit_reason,
             round(r_mult, 3), round(net_pnl, 2), round(net_pnl_pct, 3), round(mfe_r, 3),
             round(mae_r, 3), round(holding, 1) if holding is not None else None, outcome, order_id),
        )


def record_external(order_id: str, symbol: str, source: str, entry_price: float,
                    qty: int, is_option: bool, status: str, plan_type: str = "positional",
                    exit_price: Optional[float] = None, net_pnl: Optional[float] = None,
                    ts_entry: Optional[str] = None) -> None:
    """Upsert a trade sourced from the live broker (real fills imported from Kite),
    where the entry SIGNAL features and the protective STOP are unknown. net_pnl and
    win/loss are exact; r_multiple / MFE / MAE are left NULL (risk unknown) so these
    never pollute the R-based expectancy that dashboard signals feed. Re-importing
    updates the same row (idempotent on order_id)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outcome = net_pnl_pct = ts_exit = None
    if status == "CLOSED" and exit_price is not None:
        outcome = "WIN" if (net_pnl or 0) > 0 else ("LOSS" if (net_pnl or 0) < 0 else "BREAKEVEN")
        net_pnl_pct = round((exit_price / entry_price - 1.0) * 100.0, 3) if entry_price else None
        ts_exit = now
    with _LOCK, _conn() as c:
        c.execute(
            """INSERT INTO trade_journal
                 (order_id, ts_entry, source, symbol, is_option, plan_type, entry_price, qty,
                  status, ts_exit, exit_price, exit_reason, net_pnl, net_pnl_pct, outcome)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(order_id) DO UPDATE SET
                  status=excluded.status, ts_exit=excluded.ts_exit, exit_price=excluded.exit_price,
                  exit_reason=excluded.exit_reason, net_pnl=excluded.net_pnl,
                  net_pnl_pct=excluded.net_pnl_pct, outcome=excluded.outcome""",
            (order_id, ts_entry or now, source, symbol, int(is_option), plan_type,
             entry_price, qty, status, ts_exit, exit_price, "BROKER" if status == "CLOSED" else None,
             net_pnl, net_pnl_pct, outcome),
        )


def record_decision(d: Dict[str, Any]) -> int:
    """Append one intraday-console decision (any verdict) to the decision log.
    Returns the new row id. Result fields stay in the trade journal; this table
    is the process-quality record of every go/no-go call."""
    row = {
        "ts": d.get("ts") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "underlying": d.get("underlying"), "expiry": d.get("expiry"),
        "regime": d.get("regime"), "setup": d.get("setup"), "direction": d.get("direction"),
        "verdict": d.get("verdict"), "decision": d.get("decision"),
        "gates_failed": d.get("gates_failed"),
        "planned_entry": _num(d.get("planned_entry")), "planned_stop": _num(d.get("planned_stop")),
        "planned_target": _num(d.get("planned_target")), "planned_risk": _num(d.get("planned_risk")),
        "permitted_lots": d.get("permitted_lots"),
    }
    cols = ", ".join(row.keys())
    ph = ", ".join(["?"] * len(row))
    with _LOCK, _conn() as c:
        cur = c.execute(f"INSERT INTO decision_log ({cols}) VALUES ({ph})", list(row.values()))
        return cur.lastrowid


def decisions(limit: int = 100) -> List[Dict[str, Any]]:
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT * FROM decision_log ORDER BY ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def decision_summary() -> Dict[str, Any]:
    """Counts by verdict — the discipline scorecard (NO-TRADE rejection rate)."""
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT verdict, COUNT(*) n FROM decision_log GROUP BY verdict").fetchall()
    counts = {r["verdict"]: r["n"] for r in rows}
    total = sum(counts.values())
    rejected = total - counts.get("CANDIDATE", 0)
    return {
        "total": total, "counts": counts,
        "candidates": counts.get("CANDIDATE", 0),
        "rejected": rejected,
        "rejection_rate": round(rejected / total * 100, 1) if total else None,
    }


def _expectancy(rows: List[sqlite3.Row]) -> Dict[str, Any]:
    """Realized edge stats for a set of closed trades. Win-rate and net P&L cover
    ALL rows; R-based stats (expectancy_r, avg win/loss R, MFE/MAE) are computed
    ONLY over rows with a known R — imported broker trades have no stop, so their
    R is NULL and must not pollute the R metrics. `r_sample` = the R-known count."""
    n = len(rows)
    if n == 0:
        return {"trades": 0}
    wins = [r for r in rows if r["outcome"] == "WIN"]
    losses = [r for r in rows if r["outcome"] == "LOSS"]
    win_rate = round(len(wins) / n * 100, 1)
    # R-based stats only over trades that actually have an R (a known risk).
    rk = [r for r in rows if r["r_multiple"] is not None]
    rk_wins = [r for r in rk if r["outcome"] == "WIN"]
    rk_losses = [r for r in rk if r["outcome"] == "LOSS"]
    avg_win_r = round(sum(r["r_multiple"] for r in rk_wins) / len(rk_wins), 3) if rk_wins else 0.0
    avg_loss_r = round(sum(r["r_multiple"] for r in rk_losses) / len(rk_losses), 3) if rk_losses else 0.0
    exp_r = round(sum(r["r_multiple"] for r in rk) / len(rk), 3) if rk else None  # expectancy in R
    return {
        "trades": n,
        "r_sample": len(rk),
        "win_rate": win_rate,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "expectancy_r": exp_r,
        "avg_mfe_r": round(sum(r["mfe_r"] for r in rk) / len(rk), 3) if rk else None,
        "avg_mae_r": round(sum(r["mae_r"] for r in rk) / len(rk), 3) if rk else None,
        "net_pnl": round(sum((r["net_pnl"] or 0) for r in rows), 2),
    }


def attribution(min_sample: int = 50) -> Dict[str, Any]:
    """Realized expectancy by signal source, conviction bucket, and regime.

    Below `min_sample` closed trades a group is flagged statistically insufficient —
    the harness must not claim edge from noise.
    """
    with _LOCK, _conn() as c:
        closed = c.execute("SELECT * FROM trade_journal WHERE status='CLOSED'").fetchall()
        open_n = c.execute("SELECT COUNT(*) n FROM trade_journal WHERE status='OPEN'").fetchone()["n"]

    def group(key_fn):
        buckets: Dict[str, List[sqlite3.Row]] = {}
        for r in closed:
            k = key_fn(r)
            buckets.setdefault(k, []).append(r)
        out = []
        for k, rows in buckets.items():
            stat = _expectancy(rows)
            stat["group"] = k
            stat["sufficient"] = stat["trades"] >= min_sample
            out.append(stat)
        # expectancy_r may be None (R-unknown groups) — sort those last.
        return sorted(out, key=lambda s: (s.get("expectancy_r") is not None, s.get("expectancy_r") or 0), reverse=True)

    def conv_bucket(r) -> str:
        c_ = r["conviction"]
        if c_ is None:
            return "n/a"
        return "85+" if c_ >= 85 else "70-85" if c_ >= 70 else "55-70" if c_ >= 55 else "<55"

    overall = _expectancy(closed)
    overall["sufficient"] = overall["trades"] >= min_sample
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "min_sample": min_sample,
        "open_trades": open_n,
        "overall": overall,
        "by_source": group(lambda r: r["source"] or "Manual"),
        "by_conviction": group(conv_bucket),
        "by_regime": group(lambda r: r["regime"] or "unknown"),
    }


def recent(limit: int = 100) -> List[Dict[str, Any]]:
    with _LOCK, _conn() as c:
        rows = c.execute("SELECT * FROM trade_journal ORDER BY ts_entry DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import json
    print("Journal DB:", DB_PATH)
    print(json.dumps(attribution(), indent=2, default=str))
