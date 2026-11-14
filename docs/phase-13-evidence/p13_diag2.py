"""DIAGNOSTIC ONLY (min_coverage forced to 0; not engine output): NIFTY near-future profile at the close, both methods."""
from dataclasses import replace
from decimal import Decimal
from engine.config import REPO, load_config
from engine import profile as P
from engine.candles import _ns
from engine.structure import load_day, near_candles
cfg = load_config(REPO / "config/engine/v17.yaml")
diag = replace(cfg, values={**cfg.values, "profile": {**cfg.values["profile"], "min_coverage": 0.0}})
day, master, rows = load_day(cfg, cfg.root / "2026-11-06")
near = near_candles(rows, master, day, cfg)
tok, cs = near["NIFTY"]
tk = P.load_ticks(cfg.root / "2026-11-06", [tok])[tok]
tick = int(Decimal(master[tok][6]) * 100)
close = _ns(day, "15:40")
for name, t in (("TICK_BASED", tk), ("APPROXIMATE", None)):
    p = P.profile_at("NIFTY", tok, cs["1m"], t, tick, close, day, diag)
    print(name, master[tok][1], "bin", p.bin / 100, "POC", p.poc / 100, "VAL", p.val / 100, "VAH", p.vah / 100,
          "HVN", [x / 100 for x in p.hvn], "LVN", [x / 100 for x in p.lvn], "coverage", p.coverage, "volume", round(p.total))
print("engine output at min_coverage 0.95:", P.profile_at("NIFTY", tok, cs["1m"], tk, tick, close, day, cfg))
