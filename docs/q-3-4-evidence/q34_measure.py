"""Q-3-4: tick-built 1m candle volume (recording) vs Kite historical minute volume, 2026-11-06. Read-only."""
import csv, gzip, json, statistics, sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path.cwd()))
from engine.backfill import TokenBucket
from engine.broker import KiteSession
from engine.config import load_config

DAY = "2026-11-06"
ROOT = Path("data/engine") / DAY
OUT = Path(sys.argv[1])
IST = timezone(timedelta(hours=5, minutes=30))

master = {}
with gzip.open(ROOT / "instruments.csv.gz", "rt") as f:
    for r in csv.DictReader(f):
        master[int(r["instrument_token"])] = r

# tick-built 1m candles: every COMPLETE candle with a numeric volume
tick = defaultdict(dict)   # token -> {ist 'YYYY-MM-DDTHH:MM': (volume, quality status, time_basis)}
bases = defaultdict(int)
t = pq.read_table(ROOT / "parquet/snapshots/part-0.parquet").to_pylist()
for row in t:
    if row["kind"] != "candle" or not row["key"].endswith(":1m"):
        continue
    c = json.loads(row["payload"])
    if c["completeness"] != "COMPLETE" or not isinstance(c["volume"], int):
        continue
    m = datetime.fromtimestamp(c["start_ns"] / 1e9, IST).strftime("%Y-%m-%dT%H:%M")
    tick[c["token"]][m] = (c["volume"], c["quality"]["status"], c["time_basis"])
    bases[(master[c["token"]]["segment"], c["time_basis"])] += 1
print("candles by (segment, time_basis):", dict(bases))

cfg = load_config()
s, bucket = KiteSession.load(), TokenBucket(cfg.get("historical.rate_per_s"))
hist, failed = {}, {}
for tok in sorted(tick):
    bucket.take()
    try:
        rows = s.historical(tok, "minute", f"{DAY} 09:15:00", f"{DAY} 15:30:00", False)
    except Exception as e:  # noqa: BLE001
        failed[tok] = repr(e)[:200]
        continue
    hist[tok] = {r[0][:16]: r[5] for r in rows}
print(f"tokens: {len(tick)} with candles, {len(hist)} fetched, {len(failed)} failed")


def pairs(shift_min=0, status=None):
    out = []
    for tok, mins in tick.items():
        h = hist.get(tok)
        if not h:
            continue
        for m, (v, st, _) in mins.items():
            if status and st != status:
                continue
            k = (datetime.fromisoformat(m) + timedelta(minutes=shift_min)).strftime("%Y-%m-%dT%H:%M")
            if k in h:
                out.append((tok, m, v, h[k]))
    return out


def summary(ps, label):
    seg = defaultdict(list)
    for tok, m, v, hv in ps:
        seg[master[tok]["segment"]].append((v, hv))
    lines = [f"## {label}"]
    for sg, vs in sorted(seg.items()):
        both = [(v, hv) for v, hv in vs if hv > 0]
        eq = sum(1 for v, hv in vs if v == hv)
        within1 = sum(1 for v, hv in both if abs(v - hv) <= 0.01 * hv)
        ratios = sorted(v / hv for v, hv in both)
        q = (lambda p: ratios[min(len(ratios) - 1, int(p * len(ratios)))]) if ratios else (lambda p: None)
        tv, hvs = sum(v for v, _ in vs), sum(hv for _, hv in vs)
        lines.append(
            f"{sg}: minutes={len(vs)} hist_zero={len(vs) - len(both)} exact_equal={eq} ({eq / len(vs):.1%}) "
            f"within_1pct={within1}/{len(both)} ratio tick/hist p05={q(.05)} p25={q(.25)} median={q(.5)} "
            f"p75={q(.75)} p95={q(.95)} | sum tick={tv} sum hist={hvs} sum ratio={tv / hvs if hvs else None:.4f}")
    return lines


report = [f"# Q-3-4 measurement, {DAY} (run {datetime.now(IST).isoformat(timespec='seconds')})",
          f"candles by (segment, time_basis): {dict(bases)}",
          f"tokens with COMPLETE 1m candles: {len(tick)}; historical fetched: {len(hist)}; failed: {failed}"]
report += summary(pairs(0), "same minute, all COMPLETE candles")
report += summary(pairs(0, "OK"), "same minute, COMPLETE and quality OK")
for sh in (-1, 1):
    report += summary(pairs(sh), f"alignment check: tick minute vs historical minute {sh:+d}")

# per-token daily totals over matched minutes (futures, OK)
tot = defaultdict(lambda: [0, 0])
for tok, m, v, hv in pairs(0, "OK"):
    tot[tok][0] += v; tot[tok][1] += hv
rat = sorted((a / b, master[tok]["tradingsymbol"]) for tok, (a, b) in tot.items() if b)
report.append("## per-token sum ratio (COMPLETE+OK minutes), lowest 5 / highest 5")
report += [f"{sym}: {r:.4f}" for r, sym in rat[:5]] + ["..."] + [f"{sym}: {r:.4f}" for r, sym in rat[-5:]]

# BOSCHLTD 14:36 (the 60x RVOL case from Phase 5): show its minutes around then
bosch = [tok for tok in tick if master[tok]["tradingsymbol"].startswith("BOSCHLTD") and master[tok]["segment"] == "NFO-FUT"]
for tok in bosch:
    report.append(f"## {master[tok]['tradingsymbol']} 14:30-14:40 tick vs hist")
    for mm in range(30, 41):
        k = f"{DAY}T14:{mm:02d}"
        report.append(f"{k} tick={tick[tok].get(k)} hist={hist.get(tok, {}).get(k)}")

OUT.write_text("\n".join(report) + "\n")
json.dump({"tick": {str(k): v for k, v in tick.items()}, "hist": {str(k): v for k, v in hist.items()}},
          open(OUT.with_suffix(".json"), "w"))
print("\n".join(report))
