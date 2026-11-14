"""Phase 3 report per recorded day: feed latency (receive_ts - exchange_ts), staleness incidents,
allocator usage per tier, gaps.  python3 -m engine.feed_report YYYY-MM-DD  (engine.eod writes it too)

Latency uses every packet in the raw frames log that carries an exchange timestamp (full mode). The exchange
timestamp is whole epoch seconds (F-WS-5), so each value is biased upward by 0-1 s (truncation).
"""

import argparse
import json
import mmap
import sqlite3
import statistics
import sys
from pathlib import Path

import numpy as np

from .config import load_config
from .replay import frames_bytes, iter_frames_events, parquet_events
from .snapshots import read_snapshots
from .store import EVENT_COLS, GAP_COLS, conn_event, gap_event, sort_key


def _pct(xs, q: float) -> float | None:
    """xs: sorted numpy array."""
    if not len(xs):
        return None
    return round(float(xs[min(len(xs) - 1, int(q * len(xs)))]), 3)


def _frames(day_dir: Path):
    """The raw frames log, memory-mapped before compaction (pages come from disk, never all in RAM)."""
    p = day_dir / "frames.bin"
    if p.exists() and p.stat().st_size:
        with open(p, "rb") as f:
            return mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    return frames_bytes(day_dir) if p.exists() or (day_dir / "frames.bin.zst").exists() else b""


def _control(day_dir: Path) -> list:
    """Only the 'conn' / 'gap' events (the tick and depth tables are never loaded)."""
    if (day_dir / "buffer.sqlite").exists():
        db = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
        try:
            ev = [conn_event(r) for r in db.execute(f"SELECT {','.join(EVENT_COLS)} FROM events ORDER BY rowid")]
            ev += [gap_event(r) for r in db.execute(f"SELECT {','.join(GAP_COLS)} FROM gaps ORDER BY rowid")]
        finally:
            db.close()
    else:
        ev = [e for e in parquet_events(day_dir, control=True, data=False)]
    return sorted(ev, key=sort_key)


def report(day_dir: Path) -> dict:
    day_dir = Path(day_dir)
    lat = np.sort(np.fromiter(((e.receive_ns - e.exchange_ts * 1_000_000_000) / 1e9 for e in iter_frames_events(_frames(day_dir))
                               if e.kind == "tick" and e.exchange_ts), dtype=float))
    control = _control(day_dir)
    events = [dict(e.data) for e in control if e.kind == "conn"]
    plans = [json.loads(d["detail"]) for d in events if d["event"] == "tier_plan"]
    drops = [json.loads(d["detail"]) for d in events if d["event"] == "tier_drop"]
    gaps = [dict(e.data) for e in control if e.kind == "gap"]
    stale, open_since = [], {}
    for kind, key, ts, payload in read_snapshots(day_dir, kind="quality"):
        status = json.loads(payload)["quality"]["status"]
        if status == "STALE":
            open_since.setdefault(key, ts)
        elif key in open_since:
            stale.append((key, open_since.pop(key), ts))
    durations = [(b - a) / 1e9 for _, a, b in stale]
    status_json = day_dir / "status.json"
    return {
        "date": day_dir.name,
        "latency_s": {"packets": len(lat), "median": round(float(np.median(lat)), 3) if len(lat) else None,
                      "p90": _pct(lat, 0.9), "p99": _pct(lat, 0.99),
                      "note": "exchange_ts is whole seconds: values biased up by 0-1 s"},
        "staleness": {"incidents_recovered": len(stale), "instruments": len({k for k, _, _ in stale}),
                      "median_duration_s": round(statistics.median(durations), 1) if durations else None,
                      "max_duration_s": round(max(durations), 1) if durations else None,
                      "still_stale_at_end": len(open_since)},
        "allocator": {"plans": len(plans), "last_usage": plans[-1]["usage"] if plans else None, "drops": len(drops)},
        "gaps": [{k: g[k] for k in ("kind", "start_ns", "end_ns", "reason", "count")} for g in gaps],
        "max_frame_gap_s": json.loads(status_json.read_text()).get("max_frame_gap_s") if status_json.exists() else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.feed_report")
    ap.add_argument("date")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    cfg = load_config(a.config) if a.config else load_config()
    print(json.dumps(report(cfg.root / a.date), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
