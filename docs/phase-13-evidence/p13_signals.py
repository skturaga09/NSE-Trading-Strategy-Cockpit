"""Phase 8 path under v17 vs v16 on 2026-11-06, in memory (nothing written): profile_depth parts and score equality."""
from collections import Counter
from engine import signal_report as SR, signals as G
from engine.opportunity import load_cadence, CADENCE_PATH
from engine.positioning import history_reader
from engine.config import REPO
res = {}
for v in ("v16", "v17"):
    cfg = G.load(REPO / f"config/engine/{v}.yaml")
    results, obs, info = SR.run_date(cfg, "2026-11-06", history_reader(cfg), load_cadence(cfg, CADENCE_PATH))
    recs = {r.recommendation_id: r for _, rs in results.values() for r, _ in rs}
    res[v] = recs
    parts = Counter()
    for r in recs.values():
        f = next(f for f in r.score.headline.factors if f.name == "profile_depth")
        for p in f.parts:
            parts[(p.name, p.max_points, getattr(p.points, "reason", "value").split(":")[0])] += 1
    print(v, "recommendations", len(recs), "profile_depth parts", dict(parts))
a, b = res["v16"], res["v17"]
same_ids = set(a) == set(b)
diff = [k for k in a if k in b and (a[k].score.headline.points, a[k].score.headline.available_max, a[k].status, a[k].classification)
        != (b[k].score.headline.points, b[k].score.headline.available_max, b[k].status, b[k].classification)]
print("same recommendation ids:", same_ids, "| score/status/classification differences:", len(diff))
