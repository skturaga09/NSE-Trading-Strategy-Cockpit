#!/usr/bin/env python3
"""
Early-vs-EOD comparison for the intraday ignition radar.

Question it answers: for names the radar flagged INTRADAY (early) that ALSO showed up
on the EOD swing/ignition board (late), did entering early actually get a better price
and/or outcome than waiting for the close?

Two parts:
  1. ENTRY ADVANTAGE (same-day, immediate): the radar's first-fire price vs the EOD
     board price, direction-adjusted — how much the early entry beat the late one.
  2. NEXT-DAY OUTCOME (after the next session settles): P&L from the early entry vs the
     EOD entry, using the next day's settled close.

Data sources (both already logged automatically): radar fires in logs/ignite_fires.jsonl,
EOD board in the swing_signals table. Read-only; no orders, no interference.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_DIR = Path(__file__).parent
_LOG = _DIR / "logs" / "ignite_fires.jsonl"


def _first_fires() -> Dict[tuple, Dict[str, Any]]:
    """Earliest radar fire per (date, symbol) — that's the 'early entry' timestamp/price."""
    out: Dict[tuple, Dict[str, Any]] = {}
    if not _LOG.exists():
        return out
    for line in _LOG.read_text().splitlines():
        try:
            f = json.loads(line)
        except Exception:
            continue
        day = f.get("ts", "")[:10]
        key = (day, f.get("symbol"))
        if key[1] and (key not in out or f["ts"] < out[key]["ts"]):
            out[key] = f
    return out


def compare() -> Dict[str, Any]:
    """Join radar early-fires with the EOD board and compute the early-vs-EOD deltas.
    Uses the swing_signals table for the EOD price + (once available) the next-day close."""
    from dashboard import swing_journal
    fires = _first_fires()
    with swing_journal._LOCK, swing_journal._conn() as c:
        rows = c.execute(
            "SELECT signal_date, symbol, bias, ref_price, status, next_close, next_open "
            "FROM swing_signals").fetchall()
    eod = {(r["signal_date"], r["symbol"]): r for r in rows}

    pairs: List[Dict[str, Any]] = []
    for (day, sym), f in fires.items():
        e = eod.get((day, sym))
        if not e or not e["ref_price"] or not f.get("ltp"):
            continue
        d = 1 if f.get("bias") == "LONG" else -1
        early, late = f["ltp"], e["ref_price"]
        # entry advantage: how much cheaper (long) / dearer (short) the early entry was
        adv = round((late - early) / early * 100 * d, 2)
        row: Dict[str, Any] = {
            "date": day, "symbol": sym, "bias": f.get("bias"),
            "radar_time": f["ts"][11:16], "radar_price": early, "eod_price": late,
            "entry_advantage_pct": adv, "resolved": e["status"] == "RESOLVED",
        }
        if e["status"] == "RESOLVED" and e["next_close"]:
            nxt = e["next_close"]
            row["early_outcome_pct"] = round((nxt - early) / early * 100 * d, 2)
            row["eod_outcome_pct"] = round((nxt - late) / late * 100 * d, 2)
            row["early_edge_pct"] = round(row["early_outcome_pct"] - row["eod_outcome_pct"], 2)
        pairs.append(row)

    pairs.sort(key=lambda r: (r["date"], r["symbol"]), reverse=True)
    resolved = [p for p in pairs if p.get("resolved")]
    n = len(pairs)
    summary = {
        "overlap_count": n,                       # names caught early AND on the EOD board
        "avg_entry_advantage_pct": round(sum(p["entry_advantage_pct"] for p in pairs) / n, 2) if n else None,
        "resolved_count": len(resolved),
        "avg_early_edge_pct": round(sum(p["early_edge_pct"] for p in resolved) / len(resolved), 2) if resolved else None,
        "early_better_rate": round(sum(1 for p in resolved if p["early_edge_pct"] > 0) / len(resolved) * 100, 1) if resolved else None,
        "total_fires_logged": len(fires),
        "min_sample": 20,   # below this, no verdict — just accumulating
    }
    return {"summary": summary, "pairs": pairs[:60]}


def push_weekly() -> Dict[str, Any]:
    """Friday phone push: the running early-vs-EOD tally. Honest and sample-gated —
    reports 'accumulating' until there are enough resolved pairs to say anything."""
    from dashboard import exit_monitor
    r = compare()
    s = r["summary"]
    if s["overlap_count"] == 0:
        body = (f"No early/EOD overlaps yet · {s['total_fires_logged']} radar fires logged.\n"
                f"Fills in as radar names also appear on the EOD board. Nothing to read yet.")
    elif s["resolved_count"] < s["min_sample"]:
        body = (f"Overlaps: {s['overlap_count']} · avg entry advantage {s['avg_entry_advantage_pct']:+}%\n"
                f"Accumulating: {s['resolved_count']}/{s['min_sample']} resolved — no next-day verdict yet.\n"
                f"(entry advantage = how much better the early price was vs EOD.)")
    else:
        verdict = "EARLY is beating EOD" if (s["avg_early_edge_pct"] or 0) > 0 else "EOD is (so far) as good or better"
        body = (f"Overlaps: {s['overlap_count']} · avg entry advantage {s['avg_entry_advantage_pct']:+}%\n"
                f"Resolved {s['resolved_count']}: early edge {s['avg_early_edge_pct']:+}% next-day "
                f"({s['early_better_rate']}% of the time).\n"
                f"→ {verdict}. Measured, not advice.")
    return exit_monitor.notify("📏 Radar week — early vs EOD", body, tags=["straight_ruler"], priority=3)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "push":
        print(json.dumps(push_weekly()))
    else:
        print(json.dumps(compare(), indent=2, default=str))
