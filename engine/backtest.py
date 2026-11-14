"""Phase 12: event-driven backtesting, timing studies, walk-forward validation (pure). SIMULATED / HYPOTHETICAL only;
advisory: nothing here places, modifies or cancels an order.

Pure core (no clock, disk or network; time is always an input). The edge (loading recorded sessions, the HISTORICAL_CANDLES
files, the Phase 9 paper broker run, writing results) is engine.backtest_report. Thresholds: config v16 `backtest.*`
(owner D-54..D-57, ledger Q-12-*).

- Session quality: GOOD = recorder coverage of the `sessions.fno` window >= `backtest.sessions.min_coverage` and no uncovered
  stretch longer than `edge_max_gap_s` in the first / last `edge_window_min` minutes. Coverage comes from the recorder's own
  connection events and gap rows (derived data, never archived), plus the last received packet.
- Stage from the GOOD-session count: BELOW_SYSTEM_CHECK < SYSTEM_CHECK < TENTATIVE < FINAL.
- Split (fixed in config before any data is read): development = good sessions #1..#(W-N) (walk-forward train/test windows),
  holdout = #(W-N+1)..#W, post-window sessions are not read. The holdout may be read only at FINAL, once (logged by the edge).
- Price path (Q-12-16): a hypothetical entry at an anchor price; exit on the first bar that touches the stop (a bar opening
  beyond the stop exits at that open: gap-through at the first available price) or the target (exit at the target; a bar
  touching both exits at the stop), else at the last bar ending by the square-off cutoff. No fills, no costs: GROSS R.
  The Phase 9 paper broker and the Phase 7 cost model produce the recorded trades (engine.backtest_report).
- Segments are measured per event from its own exit time: IMMEDIATE_1_5 / CONTINUATION_5_30 / MID_30_90 (target hit that many
  minutes after the anchor), MULTI_SESSION (target hit on a later session within `multi_session_days`), FAILED (stop first),
  INCONCLUSIVE (anything else, incl. a target after 90 min the same session; the time-to-exit distribution is reported).
- Half-life (Q-12-17): expectancy (gross R) of a fresh entry at each age bucket after confirmation; half-life = the lower edge
  of the first bucket whose expectancy is <= half the age-0 expectancy. Keyed by Phase 6 setup type.
"""

import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Mapping, Sequence

from .candles import IST, MIN, S, Unavailable, _ns
from .opportunity import LATE, TIMELY, Setup, Snapshot, anchors, pre_signal, setups_from_structure, track
from .structure import (KEY_LEVELS, Bar, Detector, Detection, bar_of, history_levels, level_map, prev_session, seed)

TITLE = "SIMULATED / HYPOTHETICAL"
BELOW, SYSTEM_CHECK, TENTATIVE, FINAL = "BELOW_SYSTEM_CHECK", "SYSTEM_CHECK", "TENTATIVE", "FINAL"
KEEP, REVISE, DROP, INSUFFICIENT = "KEEP", "REVISE", "DROP", "INSUFFICIENT_SAMPLE"
STOP, TARGET, END, GAP, NO_DATA = "STOP", "TARGET", "END", "DATA_GAP", "NO_DATA"
SEGMENTS = ("IMMEDIATE_1_5", "CONTINUATION_5_30", "MID_30_90", "MULTI_SESSION", "FAILED", "INCONCLUSIVE")
DOWN = {"close", "error", "stall", "shutdown"}
NOT_REPRESENTABLE = "NOT_REPRESENTABLE"


def _u(x) -> bool:
    return isinstance(x, Unavailable)


def _date(ns: int) -> date:
    return datetime.fromtimestamp(ns / S, IST).date()


# ---------------------------------------------------------------- session quality
@dataclass(frozen=True)
class SessionQuality:
    day: str
    good: bool
    coverage: float
    max_edge_gap_s: float
    reasons: tuple
    uncovered: tuple               # ((start_ns, end_ns), ...) inside the session window


def _merge(iv):
    out = []
    for a, b in sorted(x for x in iv if x[1] > x[0]):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _minus(iv, holes):
    out = []
    for a, b in iv:
        segs = [(a, b)]
        for h0, h1 in holes:
            segs = [p for s0, s1 in segs for p in ((s0, min(s1, h0)), (max(s0, h1), s1)) if p[1] > p[0]]
        out += segs
    return out


def session_quality(day: date, events: Iterable[tuple], gaps: Iterable[tuple], last_packet_ns: int | None, cfg) -> SessionQuality:
    """events: (receive_ns, conn, kind) rows of the recorder `events` table; gaps: (start_ns, end_ns) rows of `gaps`.
    A connection is live from its `connect` to its close / error / stall / shutdown; one never closed is live up to the
    last received packet (or its own last event when that is unknown). Gap rows are subtracted."""
    g = lambda k: cfg.get(f"backtest.sessions.{k}")  # noqa: E731
    o, c = _ns(day, cfg.get("sessions.fno.open")), _ns(day, cfg.get("sessions.fno.close"))
    ev = sorted(events)
    live, opened, last_ev = [], {}, defaultdict(int)
    for rns, conn, kind in ev:
        last_ev[conn] = rns
        if kind == "connect":
            opened.setdefault(conn, rns)
        elif kind in DOWN and conn in opened:
            live.append((opened.pop(conn), rns))
    for conn, t0 in opened.items():
        live.append((t0, last_packet_ns if last_packet_ns is not None else last_ev[conn]))
    covered = [(max(a, o), min(b, c)) for a, b in _minus(_merge(live), _merge(gaps)) if b > o and a < c]
    covered = _merge(covered)
    unc = _minus([(o, c)], covered)
    cov = sum(b - a for a, b in covered) / (c - o)
    w = g("edge_window_min") * MIN
    edge = max([min(b, o + w) - max(a, o) for a, b in unc if a < o + w] +
               [min(b, c) - max(a, c - w) for a, b in unc if b > c - w] + [0]) / S
    why = []
    if cov < g("min_coverage"):
        why.append(f"COVERAGE {cov:.1%} < {g('min_coverage'):.0%}")
    if edge > g("edge_max_gap_s"):
        why.append(f"EDGE_GAP {edge:.0f} s > {g('edge_max_gap_s')} s in the first/last {g('edge_window_min')} min")
    return SessionQuality(str(day), not why, round(cov, 6), round(edge, 3), tuple(why), tuple(unc))


def stage(n_good: int, cfg) -> str:
    st = cfg.get("backtest.stages")
    return FINAL if n_good >= st["FINAL"] else TENTATIVE if n_good >= st["TENTATIVE"] else \
        SYSTEM_CHECK if n_good >= st["SYSTEM_CHECK"] else BELOW


def split(good_days: Sequence[str], cfg) -> dict:
    """good_days in session order -> development / holdout / post_window (fixed rule, config backtest.holdout)."""
    w, n = cfg.get("backtest.holdout.window_good_sessions"), cfg.get("backtest.holdout.last_n")
    days = list(good_days)
    return {"development": days[:w - n], "holdout": days[w - n:w], "post_window": days[w:]}


def holdout_read_allowed(st: str, previous_reads: int) -> tuple[bool, str]:
    if st != FINAL:
        return False, f"HOLDOUT_LOCKED: stage {st}; the holdout is read only at FINAL"
    if previous_reads:
        return False, f"HOLDOUT_ALREADY_READ: {previous_reads} logged read(s); it is read exactly once"
    return True, "HOLDOUT_READ: first and only read at FINAL"


# ---------------------------------------------------------------- price path (gross, no fills)
def walk(d: int, t0: int, stop: int, target, bars: Sequence[Bar], end_ns: int) -> tuple[str, int | None, int | None]:
    """(reason, ts, exit price) of a hypothetical position from t0 over `bars` (sorted, start >= t0 used) to end_ns."""
    prev = None
    for b in bars:
        if b.start < t0:
            continue
        if b.end > end_ns:
            break
        if not b.ok or (prev is not None and b.start != prev.end and _date(b.start) == _date(prev.end)):
            return GAP, b.start, None
        if prev is None and b.start != t0 and _date(b.start) == _date(t0):
            return GAP, t0, None
        if d * (b.o - stop) <= 0:
            return STOP, b.start, b.o                       # gap through the stop: the open, not the stop
        if (b.l <= stop) if d > 0 else (b.h >= stop):
            return STOP, b.end, stop                        # touching both in one bar: the stop (conservative)
        if target is not None and ((b.h >= target) if d > 0 else (b.l <= target)):
            return TARGET, b.end, target
        prev = b
    return (END, prev.end, prev.c) if prev else (NO_DATA, None, None)


def r_multiple(d: int, entry: int, stop: int, exit_px: int) -> float | Unavailable:
    risk = (entry - stop) * d
    if risk <= 0:
        return Unavailable("NO_RISK: entry at or through the stop")
    return round((exit_px - entry) * d / risk, 6)


def excursions(d: int, t0: int, entry: int, by_start: Mapping[int, Bar], res_min: int, close_ns: int, risk, atr,
               horizons) -> dict:
    """MFE/MAE per horizon from the bars after t0 only (paise, ATR, R). A horizon below the bar size is UNAVAILABLE."""
    out = {}
    for h in horizons:
        if h % res_min:
            out[h] = Unavailable(f"BELOW_DATA_RESOLUTION: {res_min}m bars")
            continue
        win = [by_start.get(t0 + k * res_min * MIN) for k in range(h // res_min)]
        if t0 + h * MIN > close_ns:
            out[h] = Unavailable("horizon ends after the session close")
        elif any(b is None or not b.ok for b in win):
            out[h] = Unavailable("INSUFFICIENT_DATA: unusable bar inside the horizon")
        else:
            hi, lo = max(b.h for b in win), min(b.l for b in win)
            mfe, mae = (hi - entry, entry - lo) if d > 0 else (entry - lo, hi - entry)
            out[h] = {"mfe_paise": mfe, "mae_paise": mae,
                      "mfe_atr": None if _u(atr) else round(mfe / atr, 6), "mae_atr": None if _u(atr) else round(mae / atr, 6),
                      "mfe_r": None if _u(risk) else round(mfe / risk, 6), "mae_r": None if _u(risk) else round(mae / risk, 6)}
    return out


def segment(same_day: tuple, later: tuple, t0: int, cfg) -> str:
    sm = cfg.get("backtest.segments_min")
    r, ts, _ = same_day
    if r == TARGET:
        m = (ts - t0) / MIN
        return "IMMEDIATE_1_5" if m <= sm["immediate"] else "CONTINUATION_5_30" if m <= sm["continuation"] else \
            "MID_30_90" if m <= sm["mid"] else "INCONCLUSIVE"
    if r == STOP:
        return "FAILED"
    if r == END:                                    # MULTI_SESSION = a target on a LATER session, not after the cutoff
        if later[0] == TARGET and _date(later[1]) > _date(t0):
            return "MULTI_SESSION"
        return "FAILED" if later[0] == STOP else "INCONCLUSIVE"
    return "INCONCLUSIVE"


def outcome(s: Setup, anchor: str, a, target, bars: Sequence[Bar], res_min: int, atr_at: Callable, cutoff_ns: int,
            close_ns: int, later_end_ns: int, cfg, **labels) -> dict:
    """One event row: an anchor of one setup -> excursions, exit, gross R, segment. a = (ts, price) | Unavailable."""
    row = {"setup_id": s.id, "setup_type": s.source_type, "direction": s.direction, "timeframe": s.timeframe,
           "underlying": s.underlying, "anchor": anchor, "pre_signal_move_atr": None if _u(s.pre_signal_move_atr)
           else s.pre_signal_move_atr, **labels}
    if a is None or _u(a) or _u(a[1]) or _u(s.structural_stop):
        why = a if a is None or _u(a) else a[1] if _u(a[1]) else s.structural_stop
        return {**row, "unavailable": "anchor not reached" if why is None else why.reason}
    t0, p0 = a
    d, stop = s.direction, s.structural_stop
    tgt = None if _u(target) else target
    risk = (p0 - stop) * d if (p0 - stop) * d > 0 else Unavailable("NO_RISK")
    atr = atr_at(s.timeframe, t0)
    same = walk(d, t0, stop, tgt, bars, cutoff_ns)
    later = walk(d, t0, stop, tgt, bars, later_end_ns) if same[0] == END else (None, None, None)
    by_start = {b.start: b for b in bars}
    return {**row, "day": str(_date(t0)), "t0": t0, "entry": p0, "stop": stop, "target": tgt,
            "risk_paise": None if _u(risk) else risk, "atr": None if _u(atr) else atr,
            "excursions": excursions(d, t0, p0, by_start, res_min, close_ns, risk, atr, cfg.get("backtest.horizons_min")),
            "exit_reason": same[0], "exit_ts": same[1], "exit_px": same[2],
            "minutes_to_exit": None if same[1] is None else round((same[1] - t0) / MIN, 3),
            "r": None if same[2] is None or _u(risk) else r_multiple(d, p0, stop, same[2]),
            "later_reason": later[0], "segment": segment(same, later, t0, cfg),
            "target_unavailable": target.reason if _u(target) else None}


def age_entries(s: Setup, target, bars: Sequence[Bar], cutoff_ns: int, cfg) -> list[dict]:
    """Fresh hypothetical entries at each age bucket edge after confirmation (bar close at that time), while the setup is
    still open (no stop / target hit before) and the entry lies between stop and target. Gross R to the cutoff."""
    if _u(s.structural_stop) or _u(target):
        return []
    d, stop, out = s.direction, s.structural_stop, []
    ends = {b.end: b for b in bars}
    for edge in cfg.get("backtest.age_buckets_min"):
        t = s.confirmed_ts + edge * MIN
        b = ends.get(t)
        if t > cutoff_ns or b is None or not b.ok:
            continue
        if walk(d, s.confirmed_ts, stop, target, bars, t)[0] in (STOP, TARGET, GAP):
            break                                   # the setup is over (or the path is broken) by this age
        p = b.c
        if (p - stop) * d <= 0 or (target - p) * d <= 0:
            continue
        r, ts, px = walk(d, t, stop, target, bars, cutoff_ns)
        if px is not None:
            out.append({"setup_type": s.source_type, "age_min": edge, "day": str(_date(t)), "r": r_multiple(d, p, stop, px)})
    return out


def class_entries(s: Setup, evs, target, bars: Sequence[Bar], cutoff_ns: int) -> list[dict]:
    """Study 3: the first evaluation of each Opportunity Age class (TIMELY, VALID_BUT_LATE, RETEST = TIMELY in the retest
    zone) as a hypothetical entry at its price; gross R to the cutoff. evs: Phase 6 Evaluations (objects or payload dicts)."""
    if _u(s.structural_stop):
        return []
    g = (lambda e, k: e[k]) if evs and isinstance(evs[0], dict) else getattr
    seen, out = set(), []
    for e in evs:
        cls, why = g(e, "classification"), g(e, "reason")
        k = "RETEST" if cls == TIMELY and why == "RETEST" else cls
        px = g(e, "price")
        if k not in (TIMELY, LATE, "RETEST") or k in seen or not isinstance(px, int) or g(e, "as_of") > cutoff_ns:
            continue
        seen.add(k)
        r, ts, ex = walk(s.direction, g(e, "as_of"), s.structural_stop, None if _u(target) else target, bars, cutoff_ns)
        if ex is not None:
            out.append({"setup_type": s.source_type, "class": k, "day": str(_date(g(e, "as_of"))),
                        "r": r_multiple(s.direction, px, s.structural_stop, ex)})
    return out


# ---------------------------------------------------------------- metrics
def max_drawdown(values: Iterable[float]) -> float:
    peak = cum = dd = 0.0
    for v in values:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return round(dd, 6)


def _stats(vals: list[float]) -> dict:
    w, lo = [v for v in vals if v > 0], [v for v in vals if v <= 0]
    gl = -sum(lo)
    return {"n": len(vals), "win_rate": round(len(w) / len(vals), 6) if vals else None,
            "avg_win": round(statistics.fmean(w), 6) if w else None, "avg_loss": round(statistics.fmean(lo), 6) if lo else None,
            "expectancy": round(statistics.fmean(vals), 6) if vals else None,
            "profit_factor": round(sum(w) / gl, 6) if gl > 0 else None, "max_drawdown": max_drawdown(vals)}


def bootstrap(rows: list[dict], key: str, cfg) -> dict:
    """Day-clustered percentile CIs (resample whole days with replacement) for expectancy, win rate and profit factor."""
    b = cfg.get("backtest.bootstrap")
    per = defaultdict(lambda: [0.0, 0, 0, 0.0, 0.0])          # sum, n, wins, gross win, gross loss
    for r in rows:
        v, p = r[key], per[r["day"]]
        p[0] += v
        p[1] += 1
        p[2] += v > 0
        p[3] += max(v, 0)
        p[4] += -min(v, 0)
    days = list(per.values())
    if len(days) < 2:
        return {"method": "day-clustered bootstrap", "unavailable": "fewer than 2 days"}
    rnd, ex, wr, pf = random.Random(b["seed"]), [], [], []
    for _ in range(b["resamples"]):
        pick = rnd.choices(days, k=len(days))
        s, n, w, gw, gl = (sum(p[i] for p in pick) for i in range(5))
        ex.append(s / n)
        wr.append(w / n)
        if gl > 0:
            pf.append(gw / gl)
    def q(xs):                                  # PF is undefined in a resample with no losing day: too few => None
        if len(xs) < b["resamples"] * 0.9:
            return None
        xs, a = sorted(xs), (1 - b["ci"]) / 2
        return [round(xs[int(a * len(xs))], 6), round(xs[int((1 - a) * len(xs)) - 1], 6)]
    return {"method": f"day-clustered bootstrap, {b['resamples']} resamples, {b['ci']:.0%} percentile, seed {b['seed']}",
            "days": len(days), "expectancy": q(ex), "win_rate": q(wr), "profit_factor": q(pf)}


def metrics(rows: list[dict], cfg, key: str = "r", precision_rows: list[dict] | None = None) -> dict:
    """Per-family figures for rows with a numeric `key` (gross R for price-path rows; net INR / net R for paper trades)."""
    ok = [r for r in rows if isinstance(r.get(key), (int, float))]
    ok.sort(key=lambda r: (r["day"], r.get("t0") or r.get("entry_ns") or 0))
    out = {"key": key, **_stats([r[key] for r in ok]), "ci": bootstrap(ok, key, cfg)}
    pr = rows if precision_rows is None else precision_rows
    out["precision"] = round(sum(r.get("exit_reason") == TARGET for r in pr) / len(pr), 6) \
        if pr and any("exit_reason" in r for r in pr) else None           # rows with no target concept: no precision
    out["sample_ok"] = out["n"] >= cfg.get("backtest.min_trades")
    return out


def verdict(m: dict, st: str, cfg, go_live: Mapping | None = None) -> tuple[str, str]:
    """KEEP / REVISE / DROP / INSUFFICIENT_SAMPLE. Below FINAL nothing is concluded (Q-12-21); KEEP needs owner go-live
    criteria (none in decisions.md: Q-12-4)."""
    n, mn = m.get("n", 0), cfg.get("backtest.min_trades")
    if n < mn:
        return INSUFFICIENT, f"{n} trades < minimum {mn}"
    if st != FINAL:
        return INSUFFICIENT, f"stage {st}: no strategy conclusions before FINAL (>= {cfg.get('backtest.stages')['FINAL']} good sessions)"
    ci = (m.get("ci") or {}).get("expectancy")
    if ci and ci[1] <= 0:
        return DROP, f"expectancy CI upper bound {ci[1]} <= 0 after costs"
    if not go_live:
        return REVISE, "no go-live criteria in docs/decisions.md (Q-12-4): KEEP is not possible"
    return REVISE, "go-live criteria evaluation not implemented for the given criteria"


def half_life(entries: list[dict], cfg) -> dict:
    """entries: age_entries rows of ONE setup type -> buckets, status, half_life_s."""
    mn, edges = cfg.get("backtest.min_trades"), cfg.get("backtest.age_buckets_min")
    by = defaultdict(list)
    for e in entries:
        if isinstance(e["r"], (int, float)):
            by[e["age_min"]].append(e["r"])
    buckets = [{"age_min": a, "n": len(by[a]), "expectancy_r": round(statistics.fmean(by[a]), 6) if by[a] else None}
               for a in edges]
    base = buckets[0]
    res = {"buckets": buckets, "half_life_s": None, "basis": "gross price-path R (no fills, no costs)"}
    if base["n"] < mn:
        return {**res, "status": INSUFFICIENT, "why": f"{base['n']} fresh entries < minimum {mn}"}
    if base["expectancy_r"] <= 0:
        return {**res, "status": "NO_POSITIVE_EDGE", "why": f"age-0 expectancy {base['expectancy_r']} R <= 0"}
    for b in buckets[1:]:
        if b["n"] < mn:
            return {**res, "status": "NOT_REACHED_WITHIN_SAMPLE", "why": f"bucket {b['age_min']} min has {b['n']} < {mn}"}
        if b["expectancy_r"] <= base["expectancy_r"] / 2:
            return {**res, "status": "MEASURED", "half_life_s": b["age_min"] * 60,
                    "why": f"expectancy {b['expectancy_r']} <= half of {base['expectancy_r']} at {b['age_min']} min"}
    return {**res, "status": "NOT_REACHED_WITHIN_SAMPLE", "why": f"still above half beyond {edges[-1]} min"}


# ---------------------------------------------------------------- segmentation
def tod_bucket(ns: int, cfg) -> str:
    e = cfg.get("backtest.time_of_day_edges")
    hm = datetime.fromtimestamp(ns / S, IST).strftime("%H:%M")
    return next((f"{a}-{b}" for a, b in zip(e, e[1:]) if a <= hm < b), "OUTSIDE")


def regime(index_dets: Sequence[Detection], as_of: int, tf: int) -> str:
    """NIFTY structure regime: the latest Phase 5 TREND state on the tf timeframe confirmed by as_of."""
    st = [x for x in index_dets if x.type == "TREND" and x.timeframe == f"{tf}m" and x.confirmed_ts <= as_of]
    return max(st, key=lambda x: x.confirmed_ts).attrs.get("state", "UNKNOWN") if st else "UNAVAILABLE"


def expiry_label(day: date, near_expiry: date | None, cfg) -> str:
    """Expiry proximity with the Phase 4 rule: calendar days to the near-month expiry (0 = EXPIRY_DAY, 1..rollover_days =
    ROLLOVER_WINDOW)."""
    if near_expiry is None:
        return "UNAVAILABLE: no near-month future in the master"
    dte = (near_expiry - day).days
    return "EXPIRY_DAY" if dte == 0 else "ROLLOVER_WINDOW" if 0 < dte <= cfg.get("positioning.rollover_days") else "NORMAL"


def group(rows: list[dict], key: str) -> dict:
    out = defaultdict(list)
    for r in rows:
        out[str(r.get(key, "UNAVAILABLE"))].append(r)
    return dict(sorted(out.items()))


def factor_study(rows: list[dict], part: str, st: str, cfg, key: str = "r") -> dict:
    """Phase 13 (Q-13-8): event rows split by a score part's value ("1.0" / "0.0" / "UNAVAILABLE..."). The part adds value
    out-of-sample only at FINAL, with >= min_trades rows in both the 1.0 and the 0.0 group, when the 1.0 group's expectancy
    CI lower bound is above the 0.0 group's upper bound. Its weight is never changed here (config change + owner decision)."""
    m = {k: metrics(v, cfg, key) for k, v in group(rows, part).items()}
    hi, lo, mn = m.get("1.0", {"n": 0}), m.get("0.0", {"n": 0}), cfg.get("backtest.min_trades")
    if st != FINAL:
        v = (INSUFFICIENT, f"stage {st}: no conclusion before FINAL")
    elif min(hi["n"], lo["n"]) < mn:
        v = (INSUFFICIENT, f"{hi['n']} / {lo['n']} rows with value 1.0 / 0.0 < minimum {mn}")
    else:
        a, b = (hi.get("ci") or {}).get("expectancy"), (lo.get("ci") or {}).get("expectancy")
        v = ("ADDS_VALUE", "1.0 CI above 0.0 CI: a non-zero weight needs a new config version and an owner decision") \
            if a and b and a[0] > b[1] else ("NO_EVIDENCE", "CIs overlap or are unavailable")
    return {"part": part, "groups": m, "verdict": v[0], "why": v[1], "weight": "unchanged (0 in v17)"}


# ---------------------------------------------------------------- walk-forward
def windows(n: int, train: int, test: int, step: int) -> list[tuple[range, range]]:
    return [(range(i, i + train), range(i + train, i + train + test)) for i in range(0, n - train - test + 1, step)]


def month_windows(days: Sequence[str], train_m: int, test_m: int, step_m: int) -> list[tuple[list, list]]:
    ym = lambda d: int(d[:4]) * 12 + int(d[5:7]) - 1  # noqa: E731
    if not days:
        return []
    m0, m1, out = ym(days[0]), ym(days[-1]), []
    a = m0
    while a + train_m + test_m - 1 <= m1:
        tr = [d for d in days if a <= ym(d) < a + train_m]
        te = [d for d in days if a + train_m <= ym(d) < a + train_m + test_m]
        out.append((tr, te))
        a += step_m
    return out


def walk_forward(wins: Sequence[tuple], grid: Sequence, rows_for: Callable, cfg, key: str = "r") -> dict:
    """For each (train days, test days): pick the grid value with the best train expectancy among those with >= min_trades
    (ties: first in grid order), then score it on the test days only. rows_for(param, days) -> rows. OOS = test rows."""
    mn, out, oos = cfg.get("backtest.min_trades"), [], []
    for tr, te in wins:
        best = None
        for p in grid:
            v = [r[key] for r in rows_for(p, tr) if isinstance(r.get(key), (int, float))]
            if len(v) >= mn and (best is None or statistics.fmean(v) > best[1]):
                best = (p, statistics.fmean(v), len(v))
        if best is None:
            out.append({"train": [tr[0], tr[-1]] if tr else None, "test": [te[0], te[-1]] if te else None,
                        "chosen": None, "why": f"no grid value has >= {mn} train trades"})
            continue
        test = rows_for(best[0], te)
        oos += test
        out.append({"train": [tr[0], tr[-1]], "test": [te[0], te[-1]] if te else None, "chosen": best[0],
                    "train_expectancy": round(best[1], 6), "train_n": best[2],
                    "test": _stats([r[key] for r in test if isinstance(r.get(key), (int, float))])})
    return {"windows": out, "oos_rows": oos}


# ---------------------------------------------------------------- OI publication delay (diagnostic)
def oi_views(rows: Sequence[tuple], t: int) -> tuple:
    """rows: (exchange_ts_ns, receive_ns, oi). (OI known at decision time t = latest received by t, OI as eventually reported
    for t = latest with exchange time <= t, received at any time). The second is LOOK_AHEAD_DIAGNOSTIC, never a decision input."""
    known = max((r for r in rows if r[1] <= t), default=None, key=lambda r: (r[1], r[0]))
    later = max((r for r in rows if r[0] <= t), default=None, key=lambda r: (r[0], r[1]))
    return (Unavailable("NO_OI_RECEIVED_BY_DECISION_TIME") if known is None else known[2],
            Unavailable("NO_OI_REPORTED_FOR_T") if later is None else later[2])


# ---------------------------------------------------------------- HISTORICAL_CANDLES day (pure over loaded bars)
def index_payload(start_ns: int, res_min: int, o: float, h: float, lo: float, c: float, source: str) -> dict:
    """A lab-CSV index bar as a Phase 3 candle payload: paise, COMPLETE, no volume and no VWAP (the dataset has none)."""
    return {"start_ns": start_ns, "end_ns": start_ns + res_min * MIN, "open": round(o * 100), "high": round(h * 100),
            "low": round(lo * 100), "close": round(c * 100), "volume": None, "vwap": None, "completeness": "COMPLETE",
            "quality": {"status": "OK", "source": source, "receive_ts": None}}


def history_rows(payloads: Iterable[dict]) -> list[list]:
    """Payloads -> Kite-minute-shaped rows [ts, o, h, l, c, volume] (rupees) for Phase 5 seeds and previous-day levels."""
    return [[datetime.fromtimestamp(p["start_ns"] / S, IST).isoformat(), p["open"] / 100, p["high"] / 100, p["low"] / 100,
             p["close"] / 100, None] for p in payloads]


def atr_lookup(atr: Mapping, tf: int, t: int) -> float | Unavailable:
    """The Phase 5 Detector's ATR after the last bar of timeframe tf ending at or before t."""
    ks = [k for k in atr.get(tf, {}) if k <= t]
    v = atr[tf][max(ks)] if ks else None
    return Unavailable(f"INSUFFICIENT_DATA: no {tf}m ATR at or before {t}") if v is None else v


@dataclass(frozen=True)
class HistDay:
    day: date
    dets: tuple
    setups: tuple
    evals: Mapping                   # setup id -> [Evaluation]
    targets: Mapping                 # setup id -> target | Unavailable
    atr: Mapping                     # tf -> {bar end: atr | None}


def historical_day(und: str, day: date, bars: Mapping[str, list[dict]], rows: list, cfg, source: str,
                   half_life: Mapping | None = None, as_of: int | None = None) -> HistDay:
    """Phase 5 Detector (unchanged) + Phase 6 setups / track on one day of index bars ('5m', '15m' payloads). rows: earlier
    days' history_rows. Only bars ending by as_of are used (default: all), so every decision is a prefix decision."""
    tok, tfs = 0, cfg.get("backtest.historical.timeframes_min")
    use = {iv: sorted((p for p in ps if as_of is None or p["end_ns"] <= as_of), key=lambda p: p["start_ns"])
           for iv, ps in bars.items()}
    prev = prev_session(day, cfg)
    dets = [replace(x, source=tuple(s.replace("HISTORICAL_API", source) for s in x.source))
            for x in history_levels(und, tok, rows, day, cfg)]
    keys = [x for x in dets if x.type in KEY_LEVELS]
    atr = {}
    for tf in tfs:
        det, atr[tf] = Detector(und, tok, tf, seed(rows, tf, day, prev, cfg), keys, cfg, day), {}
        for p in use.get(f"{tf}m", []):
            b = bar_of(p)
            dets += det.on_bar(b)
            atr[tf][b.end] = det.atr()
    dets.sort(key=lambda x: (x.confirmed_ts, x.timeframe, x.type, x.id))

    atr_at = lambda tf, t: atr_lookup(atr, tf, t)  # noqa: E731

    tf_bars = {f"{tf}m": {b.end: b for b in map(bar_of, use.get(f"{tf}m", []))} for tf in tfs}
    setups = []
    for s in setups_from_structure(dets, use, atr_at, cfg):
        setups.append(replace(s, pre_signal_move_atr=pre_signal(tf_bars[f"{s.timeframe}m"], s.first_ts, s.first_price,
                                                                s.direction, s.timeframe, atr_at, cfg)))
    finest = use.get(f"{min(tfs)}m", [])
    ends = [p["end_ns"] for p in finest]
    close = _ns(day, cfg.get("sessions.fno.close"))
    novwap = Unavailable(f"{NOT_REPRESENTABLE}: the index dataset has no volume, so no VWAP")
    lms, evals, targets = {}, {}, {}
    vtf = cfg.get("opportunity.exhaustion.vwap_atr_timeframe_min")
    for s in setups:
        snaps = []
        for t in (e for e in ends if s.confirmed_ts <= e <= min(close, as_of or close)):
            if t not in lms:
                lms[t] = level_map(und, tok, dets, finest, t)
            lm = lms[t]
            snaps.append(Snapshot(t, lm.price, None if _u(lm.price) else t, None, atr_at(s.timeframe, t), novwap, lm,
                                  tuple(dets), None, atr_at(vtf, t)))
        evs = evals[s.id] = track(s, snaps, cfg, half_life=(half_life or {}).get(s.source_type))
        targets[s.id] = next((e.obstacle[2] for e in evs if e.state == "ACTIVE" and e.as_of == s.confirmed_ts and e.obstacle),
                             Unavailable("NO_TARGET: no obstacle in the trade direction at confirmation"))
    return HistDay(day, tuple(dets), tuple(setups), evals, targets, atr)


def first_executable(s: Setup, evs, close_ns: int):
    """Phase 6 anchors (FIRST_DETECTION, CONFIRMATION, FIRST_EXECUTABLE) known at the close."""
    return anchors(s, list(evs), close_ns, close_ns)
