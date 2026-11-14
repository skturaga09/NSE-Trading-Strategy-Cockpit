"""Phase 3 baselines (pure). Inputs are Kite historical rows [ts, open, high, low, close, volume(, oi)]
with ts like '2026-11-05T09:15:00+0530' (F-HIST-2); minute-of-day keys are the bucket start 'HH:MM' IST.

- volume_baseline: per minute-of-day, the median volume over the last N sessions before `as_of`
  (sessions = distinct dates present in the data; holidays are simply absent).
- oi_change_distribution: per window w (minutes), every % change oi[t]/oi[t-w] - 1 inside one session,
  over the last N sessions, sorted. OI <= 0 is skipped (Q-HIST-5: zero OI may mean missing).
- percentile_rank / relative_volume read them. Nothing is filled: a missing baseline is Unavailable.
"""

import bisect
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from .candles import Unavailable


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def last_sessions(rows, as_of: date, n: int) -> list[date]:
    return sorted({_parse(r[0]).date() for r in rows if _parse(r[0]).date() < as_of})[-n:]


def volume_baseline(rows, as_of: date, n: int) -> dict:
    keep = set(last_sessions(rows, as_of, n))
    by_min = defaultdict(list)
    for r in rows:
        t = _parse(r[0])
        if t.date() in keep:
            by_min[t.strftime("%H:%M")].append(r[5])
    return {"sessions": [d.isoformat() for d in sorted(keep)],
            "minutes": {m: [statistics.median(v), len(v)] for m, v in sorted(by_min.items())}}


def oi_change_distribution(rows, as_of: date, n: int, windows) -> dict:
    keep = set(last_sessions(rows, as_of, n))
    by_day = defaultdict(dict)
    for r in rows:
        t = _parse(r[0])
        if t.date() in keep and len(r) > 6 and r[6] and r[6] > 0:
            by_day[t.date()][t] = r[6]
    out = {}
    for w in windows:
        d = timedelta(minutes=w)
        out[str(w)] = sorted(round((oi / day[t - d] - 1) * 100, 6) for day in by_day.values()
                             for t, oi in day.items() if t - d in day)
    return {"sessions": [x.isoformat() for x in sorted(keep)], "windows": out}


def percentile_rank(dist: list[float], x: float) -> float | Unavailable:
    if not dist:
        return Unavailable("empty baseline distribution")
    return bisect.bisect_right(dist, x) / len(dist)


def relative_volume(volume, minute: str, baseline: dict) -> float | Unavailable:
    if isinstance(volume, Unavailable):
        return volume
    med = baseline["minutes"].get(minute)
    if not med or not med[0]:
        return Unavailable(f"no non-zero baseline volume for {minute}")
    return volume / med[0]
