"""Diagnostic only (not engine output): tick-vs-candle reconciliation and coverage on a recorded day."""
import sys
from engine.config import REPO, load_config
from engine import profile as P
from engine.candles import _ns
from engine.structure import load_day, near_candles, bar_of
cfg = load_config(REPO / "config/engine/v17.yaml")
d = sys.argv[1]
day, master, rows = load_day(cfg, cfg.root / d)
near = near_candles(rows, master, day, cfg)
ticks = P.load_ticks(cfg.root / d, [t for t, _ in near.values()])
open_, close = _ns(day, "09:15"), _ns(day, "15:40")
tot_ok = tot_match = 0
for u in ("NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY"):
    if u not in near: continue
    tok, cs = near[u]
    c1 = [p for p in cs["1m"] if open_ <= p["start_ns"] < close]
    ok = [p for p in c1 if P._ok(p)]
    m = P._tick_minutes(ticks[tok], c1, cfg)
    first = min((p["start_ns"] for p in c1), default=None)
    print(u, "tick rows", len(ticks[tok]), "1m candles", len(c1), "COMPLETE/EMPTY+OK", len(ok), "tick==candle", len(m),
          "first candle", P._hhmm(first) if first else None, "tick", master[tok][6],
          "coverage at close", round(len([x for x in m if x + 60e9 <= close]) / 385, 3))
for u, (tok, cs) in near.items():
    c1 = [p for p in cs["1m"] if open_ <= p["start_ns"] < close]
    tot_ok += sum(1 for p in c1 if P._ok(p)); tot_match += len(P._tick_minutes(ticks[tok], c1, cfg))
print("all near futures: usable candles", tot_ok, "reconciled tick==candle", tot_match)
