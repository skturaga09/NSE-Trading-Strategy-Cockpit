"""Phase 13 real-data run on 2026-11-06 (read-only): profile detections per underlying."""
import sys, time
from collections import Counter
from engine.config import REPO, load_config
from engine import profile as P
from engine.structure import load_day, near_candles, evaluate_day
from engine.positioning import history_reader

cfg = load_config(REPO / "config/engine/v17.yaml")
d = sys.argv[1]
t0 = time.time()
day, master, rows = load_day(cfg, cfg.root / d)
near = near_candles(rows, master, day, cfg)
print("underlyings", len(near), "depth snapshot rows", sum(1 for r in rows if r[0] == "depth"))
dets = evaluate_day(near, history_reader(cfg)(day), cfg, day)
out = P.add_profile(dets, near, master, rows, cfg.root / d, cfg, day)
c = Counter(); methods = Counter(); reasons = Counter()
for u, ds in out.items():
    for x in ds:
        if x.type.startswith("PROFILE_") or x.type in ("HVZ_REJECTION", "DEPTH_BEHAVIOUR"):
            c[x.type] += 1
            methods[(x.type, x.label)] += 1
            if x.type == "PROFILE_UNAVAILABLE":
                reasons[x.attrs["reason"].split(":")[0]] += 1
print("detections", dict(sorted(c.items())))
print("labels", dict(sorted(methods.items())))
print("unavailable reasons", dict(reasons))
n = next(u for u in ("NIFTY",) if u in out)
last = [x for x in out[n] if x.type in P.LEVEL_TYPES]
if last:
    ts = max(x.confirmed_ts for x in last)
    print("NIFTY latest snapshot", P._hhmm(ts), [(x.type, x.level / 100, x.label, x.attrs["coverage"]) for x in last if x.confirmed_ts == ts])
print("runtime_s", round(time.time() - t0, 1))
