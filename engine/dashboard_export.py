"""Phase 10 dashboard read model (edge): `<date>/dashboard.sqlite`, derived from the recorded day.

  python3 -m engine.dashboard_export DATE [...] [--config config/engine/v13.yaml]

Phase 4 states are not persisted (Q-4-6), and the positioning map, market overview and signal chart need them over the
whole day. This recomputes them with the Phase 3–8 functions as they are (structure.load_day / near_candles /
evaluate_day, positioning.run_day, signals.market_context — the same calls engine.signal_report makes) and stores, at every
`dashboard.scrub_step_min` mark: each underlying's primary (residual) and raw positioning views, the market context, and
every near-month future 1m candle payload exactly as Phase 3 published it. Nothing is filled: an UNAVAILABLE input stays
UNAVAILABLE with its reason. Append-only (INSERT OR IGNORE on natural key + config version), like every engine store.
"""

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from . import signals as G
from .candles import MIN, _ns
from .opportunity import CADENCE_PATH, load_cadence
from .paper import load as load_v11
from .positioning import history_reader, run_day
from .snapshots import jsonable
from .structure import bar_of, evaluate_day as structure_day, load_day, near_candles

DEFAULT_CONFIG = G.REPO / "config" / "engine" / "v13.yaml"
REQUIRED = ["dashboard.scrub_step_min", "dashboard.stale_after_s", "dashboard.sse_interval_s", "dashboard.vix_underlying", "dashboard.eod_step_timeout_s"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS positioning (underlying TEXT, ts_ns INTEGER, view TEXT, hypothesis TEXT, reasons TEXT,
  suppressed TEXT, price_chg_pct TEXT, oi_chg_pct TEXT, rvol TEXT, config_version TEXT,
  PRIMARY KEY (underlying, ts_ns, view, config_version));
CREATE TABLE IF NOT EXISTS market (ts_ns INTEGER, payload TEXT, config_version TEXT, PRIMARY KEY (ts_ns, config_version));
CREATE TABLE IF NOT EXISTS candles (underlying TEXT, token INTEGER, symbol TEXT, end_ns INTEGER, payload TEXT,
  config_version TEXT, PRIMARY KEY (token, end_ns, config_version));
CREATE TABLE IF NOT EXISTS runs (config_version TEXT PRIMARY KEY, created_ns INTEGER, step_min INTEGER, states INTEGER,
  marks INTEGER, underlyings INTEGER);
"""


def load(path=DEFAULT_CONFIG):
    from .costs import require
    return require(load_v11(path), REQUIRED, path)


def _j(x) -> str:
    return json.dumps(jsonable(x), sort_keys=True, separators=(",", ":"), default=str)


def _feat(state, name):
    f = next((f for f in state.features if f.name == name), None)
    return {"UNAVAILABLE": f"FEATURE_MISSING: {name}"} if f is None else jsonable(f.value)


def build(cfg, d: str, hist, cadence) -> dict:
    """-> rows for the read model (pure apart from the reads in load_day / history)."""
    day_dir = cfg.root / d
    day, master, rows = load_day(cfg, day_dir)
    near = near_candles(rows, master, day, cfg)
    dets = structure_day(near, hist(day), cfg, day)
    states, _ = run_day(cfg, day_dir, hist(day), cadence)
    step, fw = cfg.get("dashboard.scrub_step_min") * MIN, cfg.get("positioning.feature_window_min")
    open_ = _ns(day, cfg.get("sessions.fno.open"))
    pst = defaultdict(dict)
    for st in states:
        pst[st.underlying][st.ts_ns] = st
    pos = []
    for st in states:
        if (st.ts_ns - open_) % step:
            continue
        for view in ("primary", "raw"):
            v = getattr(st, view)
            pos.append((st.underlying, st.ts_ns, view, v.positioning_hypothesis, _j(v.reasons), v.suppressed_hypothesis,
                        _j(_feat(st, f"fut_price_chg_{fw}m_pct" if view == "raw" else f"residual_chg_{fw}m_pct")),
                        _j(_feat(st, f"combined_oi_chg_{fw}m_pct")), _j(_feat(st, f"rvol_{fw}m")), cfg.version))
    idx = cfg.get("positioning.beta.index_underlying")
    usable = {u: {b.end: (b.c, b.vwap) for b in map(bar_of, cs["1m"]) if b.ok and b.vwap is not None}
              for u, (_, cs) in near.items()}
    marks = sorted({t for u in pst.values() for t in u if not (t - open_) % step})
    market = []
    for t in marks:
        ctx = G.market_context(t, tuple(dets.get(idx, [])), pst.get(idx, {}).get(t),
                               tuple(m[t] for m in usable.values() if t in m), cfg)
        market.append((t, _j(ctx), cfg.version))
    candles = [(u, tok, master[tok][1], p["end_ns"], json.dumps(p, sort_keys=True), cfg.version)
               for u, (tok, cs) in near.items() for p in cs["1m"]]
    return {"positioning": pos, "market": market, "candles": candles, "states": len(states), "marks": len(marks),
            "underlyings": len(near)}


def write(day_dir: Path, rows: dict, cfg) -> int:
    db = sqlite3.connect(Path(day_dir) / "dashboard.sqlite")
    try:
        db.executescript(SCHEMA)
        n = db.total_changes
        db.executemany("INSERT OR IGNORE INTO positioning VALUES (?,?,?,?,?,?,?,?,?,?)", rows["positioning"])
        db.executemany("INSERT OR IGNORE INTO market VALUES (?,?,?)", rows["market"])
        db.executemany("INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?)", rows["candles"])
        db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,?)", (cfg.version, time.time_ns(),
                   cfg.get("dashboard.scrub_step_min"), rows["states"], rows["marks"], rows["underlyings"]))
        db.commit()
        return db.total_changes - n
    finally:
        db.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m engine.dashboard_export")
    ap.add_argument("dates", nargs="+")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--cadence", default=str(CADENCE_PATH))
    a = ap.parse_args(argv)
    cfg = load(a.config)
    cadence, hist = load_cadence(cfg, a.cadence), history_reader(cfg)
    for d in a.dates:
        rows = build(cfg, d, hist, cadence)
        n = write(cfg.root / d, rows, cfg)
        print(json.dumps({"date": d, "rows_written": n, "states": rows["states"], "marks": rows["marks"],
                          "underlyings": rows["underlyings"], "config_version": cfg.version}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
