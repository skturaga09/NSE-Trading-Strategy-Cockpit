"""Phase 6: opportunity age, timeliness, retest plans, exhaustion flags and the timing recorder.

  python3 -m engine.opportunity YYYY-MM-DD [...] [--report PATH] [--dry-run] [--config config/engine/v7.yaml]

Pure core: `opportunity_age(setup, snapshot, cfg, plan)`, `track(setup, snapshots, cfg)`, `exhaustion(...)` and
`timing_rows(setup, evaluations, bars_1m, target, atrs, as_of, close_ns, cfg)` read no clock, disk or network; time is
the `as_of` input. Thresholds: config `opportunity.*` (v7, owner decisions in Phase 6, "as proposed").

Setups (owner decision): Phase 5 BREAKOUT_ACCEPTED / BREAKDOWN_ACCEPTED, SWEEP_LOW / SWEEP_HIGH, ZONE_DEFENDED and Phase 4
CONFIRMED positioning events. Structural stop (owner decision "far side"), fixed when the setup is built and never
recomputed: breakout = opposite consolidation edge; sweep = the wick extreme; zone = the zone's far edge; positioning =
Phase 4's PRICE_THROUGH_FIRST_OBSERVED level. Invalidation = a 1m close through the stop (Phase 4: also its own
INVALIDATED row).

Classification precedence (conservative): UNKNOWN (a required input UNAVAILABLE, incl. no LevelMap or no obstacle in
the trade direction) > EXHAUSTED (any exhaustion flag; output POSSIBLE_EXHAUSTION, never "reversal") > TIMELY (every
rule passes) / VALID_BUT_LATE (failed rules listed). UNKNOWN is never TIMELY. AGE_VS_HALF_LIFE (Phase 12, owner D-56): a setup type with a measured RECORDED
half-life (file `opportunity.half_life_file`, written by engine.backtest_report) fails TIMELY once its age since confirmation
exceeds `opportunity.half_life_multiple` x that half-life. With no measured value the rule is disabled (outputs unchanged).
"""

import argparse
import json
import sqlite3
import statistics
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from .candles import MIN, S, Unavailable, _ns
from .config import REPO, ConfigError, EngineConfig, load_config
from .oi_cadence import DEFAULT_OUT as CADENCE_PATH
from .positioning import DIRECTION, NEUTRAL, _hhmm, history_reader, parse_cadence, run_day
from .snapshots import jsonable
from .profile import SNAPSHOT_TYPES as PROFILE_SNAPSHOTS, add_profile
from .structure import Bar, LevelMap, bar_of, evaluate_day as structure_day, level_map, load_day, near_candles

DEFAULT_CONFIG = REPO / "config" / "engine" / "v8.yaml"
REQUIRED = [f"opportunity.{k}" for k in (
    "positioning_timeframe_min", "min_rr", "max_extension_atr", "max_stop_atr", "pre_signal_bars",
    "retest.zone_width_atr", "retest.expiry_min", "exhaustion.vwap_extension_atr", "exhaustion.vwap_atr_timeframe_min",
    "exhaustion.windows",
    "exhaustion.window_min", "exhaustion.failure_tests", "exhaustion.level_tol_atr", "timing.horizons_min")]
TIMELY, LATE, EXHAUSTED, UNKNOWN = "TIMELY", "VALID_BUT_LATE", "EXHAUSTED", "UNKNOWN"
NET = Unavailable("NET_UNAVAILABLE: no cost model yet")
OPTION = Unavailable("UNAVAILABLE: option candidates are filled in a later phase")
HALF_LIFE = Unavailable("UNAVAILABLE: no measured edge half-life yet; the rule using it is disabled")
FAIL_TYPES = {1: ("SWING_HIGH", "SWEEP_HIGH", "BREAKOUT_FAILED"), -1: ("SWING_LOW", "SWEEP_LOW", "BREAKDOWN_FAILED")}


def load(path=DEFAULT_CONFIG) -> EngineConfig:
    cfg = load_config(path)
    for key in REQUIRED:
        try:
            v = cfg.get(key)
        except (KeyError, TypeError):
            v = None
        if v is None or v == "":
            raise ConfigError(f"config {path}: required key '{key}' is missing or empty")
    return cfg


def _u(x) -> bool:
    return isinstance(x, Unavailable)


# ---------------------------------------------------------------- types
@dataclass(frozen=True)
class Setup:
    id: str                        # the source detection id / Phase 4 event_id
    family: str                    # BREAKOUT | SWEEP | ZONE | POSITIONING
    source_type: str
    underlying: str
    token: int
    timeframe: int                 # minutes: ATR / VWAP / pre-signal bars
    direction: int                 # +1 long (price up), -1 short
    first_ts: int
    first_price: int | Unavailable
    confirmed_ts: int
    confirmed_price: int | Unavailable
    structural_stop: int | Unavailable
    broken_level: int | None       # retest candidate (breakout edge, swept level, zone near edge); None for positioning
    pre_signal_move_atr: float | Unavailable
    invalidated_ts: int | None     # set by the source itself (Phase 4 INVALIDATED row)


@dataclass(frozen=True)
class Snapshot:
    as_of: int
    price: int | Unavailable       # last usable 1m close at or before as_of
    price_ts: int | None           # that candle's close (exchange-time basis)
    price_receive_ns: int | None
    atr: float | Unavailable       # setup-timeframe ATR (Phase 5) at as_of
    vwap: int | Unavailable        # setup-timeframe session VWAP (Phase 5) at as_of
    level_map: LevelMap | None
    structure: tuple = ()          # Phase 5 detections of the underlying (filtered by confirmed_ts <= as_of inside)
    positioning: Mapping = None    # Phase 4 PositioningState by ts_ns, or None when not available
    vwap_atr: float | Unavailable | None = None   # ATR of exhaustion.vwap_atr_timeframe_min (Q-OPP-1); None = not given


@dataclass(frozen=True)
class RetestPlan:
    created_ts: int
    level_type: str | None         # BROKEN_LEVEL | VWAP | None (no valid level)
    level: int | None
    zone_low: int | None
    zone_high: int | None
    invalidation: int              # = the structural stop
    expires_ts: int
    rr_if_filled: float | Unavailable


@dataclass(frozen=True)
class Evaluation:
    setup_id: str
    as_of: int                     # processing time (stream / replay time, not wall clock)
    state: str                     # ACTIVE | INVALIDATED | RETEST_EXPIRED
    classification: str | None     # TIMELY | VALID_BUT_LATE | EXHAUSTED | UNKNOWN (None when not ACTIVE)
    reason: str
    failed_rules: tuple
    price: int | Unavailable
    price_ts: int | None
    price_receive_ns: int | None
    price_age_s: float | None
    atr: float | Unavailable
    age_first_s: float
    age_confirmed_s: float
    extension_atr: float | Unavailable
    extension_confirmed_atr: float | Unavailable
    obstacle: tuple | None         # (type, timeframe, level, detection id)
    obstacle_distance_atr: float | Unavailable
    structural_stop: int | Unavailable
    stop_distance_atr: float | Unavailable
    current_rr: float | Unavailable
    current_rr_net: Unavailable
    option_premium_change: float | Unavailable   # Phase 11: % change of the selected option's mid since confirmation (filled in Phase 8)
    option_iv_change: float | Unavailable        # Phase 11: IV points change since confirmation (filled in Phase 8)
    pre_signal_move_atr: float | Unavailable
    age_vs_half_life: float | Unavailable        # age since confirmation / measured half-life (Phase 12, D-56)
    exhaustion: str | None         # POSSIBLE_EXHAUSTION | None
    exhaustion_flags: tuple
    exhaustion_notes: tuple
    retest_plan: RetestPlan | None
    missing: tuple
    source: str
    config_version: str


# ---------------------------------------------------------------- setups (pure)
def setups_from_structure(dets, candles: Mapping[str, list[dict]], atr_at, cfg) -> list[Setup]:
    """Phase 5 detections -> setups. candles: '1m' / '<tf>m' payloads. atr_at(tf_min, ts) -> ATR | Unavailable."""
    by_id = {d.id: d for d in dets}
    bars = {iv: {b.end: b for b in map(bar_of, cs)} for iv, cs in candles.items()}
    out = []
    for d in dets:
        if d.type in ("BREAKOUT_ACCEPTED", "BREAKDOWN_ACCEPTED"):
            s, box = (1 if d.type == "BREAKOUT_ACCEPTED" else -1), by_id[d.attrs["box"]]
            fam, stop, broken = "BREAKOUT", box.attrs["low"] if s > 0 else box.attrs["high"], d.level
        elif d.type in ("SWEEP_LOW", "SWEEP_HIGH"):
            s = 1 if d.type == "SWEEP_LOW" else -1
            fam, stop, broken = "SWEEP", d.attrs["extreme"], d.level
        elif d.type == "ZONE_DEFENDED":
            z = by_id[d.attrs["zone"]]
            s = 1 if z.type == "DEMAND_ZONE" else -1
            fam, stop, broken = "ZONE", z.attrs["low"] if s > 0 else z.attrs["high"], z.attrs["high"] if s > 0 else z.attrs["low"]
        else:
            continue
        tf = int(d.timeframe[:-1])
        close = lambda t: _close(bars.get(d.timeframe, {}), t, d.timeframe)  # noqa: E731
        out.append(Setup(d.id, fam, d.type, d.underlying, d.token, tf, s, d.created_ts, close(d.created_ts),
                         d.confirmed_ts, close(d.confirmed_ts), stop, broken,
                         pre_signal(bars.get("1m", {}), d.created_ts, close(d.created_ts), s, tf, atr_at, cfg), None))
    return out


def setups_from_positioning(events: list[dict], c1: Mapping[str, list[dict]], atr_at, cfg) -> list[Setup]:
    """Phase 4 CONFIRMED rows -> setups; their INVALIDATED rows set invalidated_ts. c1: underlying -> 1m payloads."""
    tf, out = cfg.get("opportunity.positioning_timeframe_min"), []
    inval = {e["event_id"]: e["ts_ns"] for e in events if e["state"] == "INVALIDATED"}
    for e in events:
        if e["state"] != "CONFIRMED":
            continue
        s = 1 if e["direction"] == "PRICE_UP" else -1
        first = _ns_iso(e["first_observed_ts"])
        fp = e["price_first_observed_paise"]
        fp = Unavailable("INSUFFICIENT_DATA: no first_observed price") if fp is None else round(fp)
        cp = e["price_confirmed_paise"]
        lvl = e["invalidation"][1]["level_paise"]
        bars = {b.end: b for b in map(bar_of, c1.get(e["underlying"], []))}
        und = e["underlying"]
        out.append(Setup(e["event_id"], "POSITIONING", e["positioning_hypothesis"], und, e["contracts"]["price"][0], tf, s,
                         first, fp, e["ts_ns"], Unavailable("INSUFFICIENT_DATA: no confirmed price") if cp is None else round(cp),
                         Unavailable("INSUFFICIENT_DATA: Phase 4 invalidation level unavailable") if lvl is None else round(lvl),
                         None, pre_signal(bars, first, fp, s, tf, lambda m, t: atr_at(und, m, t), cfg), inval.get(e["event_id"])))
    return out


def _ns_iso(s: str) -> int:
    from datetime import datetime
    return int(datetime.fromisoformat(s).timestamp()) * S


def _close(bars: Mapping[int, Bar], t: int, label: str) -> int | Unavailable:
    b = bars.get(t)
    return b.c if b is not None and b.ok else Unavailable(f"INSUFFICIENT_DATA: no usable {label} candle closing {_hhmm(t)}")


def pre_signal(c1: Mapping[int, Bar], first_ts: int, first_price, s: int, tf: int, atr_at, cfg) -> float | Unavailable:
    """(price at first detection - 1m close `pre_signal_bars` setup bars earlier) / ATR at first detection, signed."""
    ref = _close(c1, first_ts - cfg.get("opportunity.pre_signal_bars") * tf * MIN, "1m")
    atr = atr_at(tf, first_ts)
    for v in (first_price, ref, atr):
        if _u(v):
            return v
    return (first_price - ref) * s / atr


# ---------------------------------------------------------------- evaluation (pure)
def exhaustion(s: Setup, snap: Snapshot, obstacle, cfg) -> tuple[tuple, tuple]:
    """(flags, notes): each flag explains itself; a note says why a check could not run."""
    g = lambda k: cfg.get(f"opportunity.exhaustion.{k}")  # noqa: E731
    flags, notes, t, d = [], [], snap.as_of, s.direction
    px, atr, vw, va = snap.price, snap.atr, snap.vwap, snap.vwap_atr
    va = Unavailable(f"INSUFFICIENT_DATA: no {g('vwap_atr_timeframe_min')}m ATR given") if va is None else va
    if any(_u(v) for v in (px, va, vw)):
        notes.append("VWAP_EXTENSION not checked: " + next(v.reason for v in (px, va, vw) if _u(v)))
    elif (px - vw) * d / va >= g("vwap_extension_atr"):
        flags.append(f"VWAP_EXTENSION: price {(px - vw) * d / va:+.2f} x {g('vwap_atr_timeframe_min')}m ATR beyond VWAP"
                     f" >= {g('vwap_extension_atr')}")
    w, k = g("window_min"), g("windows")
    ts = [t - (k - 1 - i) * w * MIN for i in range(k)]          # oldest first
    st = [None if snap.positioning is None else snap.positioning.get(x) for x in ts]
    if None in st:
        why = "no Phase 4 positioning states" if snap.positioning is None else \
            f"no Phase 4 state at {', '.join(_hhmm(x) for x, y in zip(ts, st) if y is None)}"
        notes += [f"OI_PROGRESS_DECLINING not checked: {why}", f"RVOL_DECLINING_WHILE_EXTENDING not checked: {why}"]
    else:
        p, o = [x.feature(f"fut_price_chg_{w}m_pct") for x in st], [x.feature(f"combined_oi_chg_{w}m_pct") for x in st]
        if None in p or None in o:
            notes.append(f"OI_PROGRESS_DECLINING not checked: {w}m price or combined OI change unavailable")
        elif all(x > 0 for x in o):
            prog = [a * d / b for a, b in zip(p, o)]
            if all(a > b for a, b in zip(prog, prog[1:])):
                flags.append(f"OI_PROGRESS_DECLINING: price % per OI % over {k} x {w}m windows {[round(x, 3) for x in prog]}")
        rv, cl = [x.feature(f"rvol_{w}m") for x in st], [x.feature("fut_close") for x in st]
        if None in rv or None in cl:
            notes.append(f"RVOL_DECLINING_WHILE_EXTENDING not checked: rvol_{w}m or price unavailable")
        elif all(a > b for a, b in zip(rv, rv[1:])) and all((b - a) * d > 0 for a, b in zip(cl, cl[1:])):
            flags.append(f"RVOL_DECLINING_WHILE_EXTENDING: rvol {[round(x, 2) for x in rv]} while price extends")
    if obstacle is None or _u(atr):
        notes.append("REPEATED_FAILURE not checked: " + ("no obstacle in the trade direction" if obstacle is None else atr.reason))
    else:
        tol, lvl = g("level_tol_atr") * atr, obstacle[2]
        hits = [x for x in snap.structure if x.type in FAIL_TYPES[d] and x.timeframe == f"{s.timeframe}m"
                and x.confirmed_ts <= t and abs(x.level - lvl) <= tol]
        if len(hits) >= g("failure_tests"):
            flags.append(f"REPEATED_FAILURE: {len(hits)} tests at {lvl / 100:.2f} ({sorted(Counter(x.type for x in hits).items())})")
    try:
        win = cfg.get("profile.rejection.flag_window_min") * MIN    # Phase 13 (v17); earlier configs keep the old note
    except KeyError:
        win = None
    if win is None:
        notes.append("HIGH_VOLUME_ZONE_REJECTION skipped: no volume profile available yet")
    else:
        hits = [x for x in snap.structure if x.type == "HVZ_REJECTION" and x.attrs["direction"] == -d
                and t - win < x.confirmed_ts <= t]
        last = max((x for x in snap.structure if x.type in PROFILE_SNAPSHOTS and x.confirmed_ts <= t),
                   key=lambda x: x.confirmed_ts, default=None)
        if hits:
            at = ", ".join(f"{x.attrs['zone'][8:]} {x.level / 100:.2f}" for x in hits)       # PROFILE_POC -> POC
            flags.append(f"HIGH_VOLUME_ZONE_REJECTION: {len(hits)} rejection(s) against the trade at {at} in the last "
                         f"{win // MIN} min ({', '.join(sorted({x.label for x in hits}))} volume profile)")
        elif last is None or last.type == "PROFILE_UNAVAILABLE":
            notes.append("HIGH_VOLUME_ZONE_REJECTION not checked: " + ("no volume profile snapshot at as_of" if last is None
                                                                       else last.attrs["reason"]))
    now = None if snap.positioning is None else snap.positioning.get(t)
    if now is None:
        notes.append("OPPOSING_POSITIONING not checked: no Phase 4 state at as_of")
    else:
        h = now.primary.positioning_hypothesis
        if h != NEUTRAL and (1 if DIRECTION[h] == "PRICE_UP" else -1) != d:
            flags.append(f"OPPOSING_POSITIONING: primary positioning hypothesis {h}")
    return tuple(flags), tuple(notes)


def opportunity_age(s: Setup, snap: Snapshot, cfg, plan: RetestPlan | None = None, *,
                    half_life: float | None = None) -> Evaluation:
    """half_life: measured edge half-life of this setup type in seconds (Phase 12), None = rule disabled."""
    g = lambda k: cfg.get(f"opportunity.{k}")  # noqa: E731
    d, px, atr, lm = s.direction, snap.price, snap.atr, snap.level_map

    def per_atr(a, b):
        for v in (a, b, atr):
            if _u(v):
                return v
        return (a - b) * d / atr
    ob = None
    if lm is None:
        dist = Unavailable("NO_LEVEL_MAP")
    else:
        o = lm.above if d > 0 else lm.below
        ob = None if o is None else (o.type, o.timeframe, o.level, o.detection_id)
        dist = Unavailable("NO_OBSTACLE_IN_TRADE_DIRECTION") if o is None else per_atr(o.level, px)
    stop_d = per_atr(px, s.structural_stop)
    rr = next((v for v in (dist, stop_d) if _u(v)), None) or \
        (Unavailable("INSUFFICIENT_DATA: price at or through the stop") if stop_d <= 0 else dist / stop_d)
    ext, ext_c = per_atr(px, s.first_price), per_atr(px, s.confirmed_price)
    flags, notes = exhaustion(s, snap, ob, cfg)
    missing = tuple(f"{n}: {v.reason}" for n, v in (("price", px), ("atr", atr), ("first_price", s.first_price),
                                                    ("structural_stop", s.structural_stop), ("obstacle", dist), ("rr", rr))
                    if _u(v))
    failed = ()
    hl = HALF_LIFE if half_life is None else (snap.as_of - s.confirmed_ts) / S / half_life
    if missing:
        cls, why = UNKNOWN, "INPUT_UNAVAILABLE"
    elif flags:
        cls, why = EXHAUSTED, "POSSIBLE_EXHAUSTION"
    else:
        failed = tuple(r for r, bad in (("RR_BELOW_MIN", rr < g("min_rr")), ("EXTENDED", ext > g("max_extension_atr")),
                                        ("STOP_TOO_WIDE", stop_d > g("max_stop_atr")),
                                        ("AGE_VS_HALF_LIFE", not _u(hl) and hl > g("half_life_multiple"))) if bad)
        in_zone = plan is not None and plan.zone_low is not None and plan.zone_low <= px <= plan.zone_high
        cls, why = (LATE, "RULES_FAILED") if failed else (TIMELY, "RETEST" if in_zone else "RULES_PASS")
    return Evaluation(s.id, snap.as_of, "ACTIVE", cls, why, failed, px, snap.price_ts, snap.price_receive_ns,
                      None if snap.price_ts is None else (snap.as_of - snap.price_ts) / S, atr,
                      (snap.as_of - s.first_ts) / S, (snap.as_of - s.confirmed_ts) / S, ext, ext_c, ob, dist,
                      s.structural_stop, stop_d, rr, NET, OPTION, OPTION, s.pre_signal_move_atr, hl,
                      "POSSIBLE_EXHAUSTION" if flags else None, flags, notes, plan, missing,
                      f"derived:opportunity({s.family}:{s.source_type})", cfg.version)


def retest_plan(s: Setup, ev: Evaluation, snap: Snapshot, cfg) -> RetestPlan:
    """Re-entry zone at the nearer valid level among the broken level and VWAP (valid = between the stop and price)."""
    g = lambda k: cfg.get(f"opportunity.retest.{k}")  # noqa: E731
    d, px, stop, atr = s.direction, ev.price, s.structural_stop, ev.atr
    cands = [(t, lv) for t, lv in (("BROKEN_LEVEL", s.broken_level), ("VWAP", None if _u(snap.vwap) else snap.vwap))
             if lv is not None and (px - lv) * d > 0 and (lv - stop) * d > 0]
    exp = snap.as_of + g("expiry_min") * MIN
    if not cands:
        return RetestPlan(snap.as_of, None, None, None, None, stop, exp,
                          Unavailable("NO_VALID_LEVEL: neither the broken level nor VWAP lies between the stop and price"))
    typ, lv = min(cands, key=lambda c: (abs(px - c[1]), c[0]))
    w = round(g("zone_width_atr") * atr)
    lo, hi = (lv, lv + w) if d > 0 else (lv - w, lv)
    fill = hi if d > 0 else lo                     # the zone's worse edge
    rr = Unavailable("NO_OBSTACLE_IN_TRADE_DIRECTION") if ev.obstacle is None else \
        (ev.obstacle[2] - fill) * d / ((fill - stop) * d)
    return RetestPlan(snap.as_of, typ, lv, lo, hi, stop, exp, rr)


def _end(s: Setup, snap: Snapshot, state: str, why: str, cfg) -> Evaluation:
    u = Unavailable(f"{state}: not evaluated")
    return Evaluation(s.id, snap.as_of, state, None, why, (), snap.price, snap.price_ts, snap.price_receive_ns, None, u,
                      (snap.as_of - s.first_ts) / S, (snap.as_of - s.confirmed_ts) / S, u, u, None, u, s.structural_stop,
                      u, u, NET, OPTION, OPTION, s.pre_signal_move_atr, HALF_LIFE, None, (), (), None, (),
                      f"derived:opportunity({s.family}:{s.source_type})", cfg.version)


def track(s: Setup, snapshots: Iterable[Snapshot], cfg, *, half_life: float | None = None) -> list[Evaluation]:
    """Evaluations at each snapshot from confirmation on, until invalidation or retest expiry (a final row says which).
    VALID_BUT_LATE without an active plan creates one; TIMELY clears it."""
    out, plan = [], None
    for snap in snapshots:
        if snap.as_of < s.confirmed_ts:
            continue
        px, stop = snap.price, s.structural_stop
        if s.invalidated_ts is not None and snap.as_of >= s.invalidated_ts:
            out.append(_end(s, snap, "INVALIDATED", "SOURCE_INVALIDATED", cfg))
            break
        if not _u(px) and not _u(stop) and (px - stop) * s.direction <= 0:
            out.append(_end(s, snap, "INVALIDATED", f"CLOSE_THROUGH_STOP: {px} vs {stop}", cfg))
            break
        if plan is not None and snap.as_of >= plan.expires_ts:
            out.append(_end(s, snap, "RETEST_EXPIRED", f"retest plan from {_hhmm(plan.created_ts)} expired", cfg))
            break
        ev = opportunity_age(s, snap, cfg, plan, half_life=half_life)
        if ev.classification == TIMELY:
            plan = None
        elif ev.classification == LATE and plan is None:
            plan = retest_plan(s, ev, snap, cfg)
            ev = replace(ev, retest_plan=plan)
        out.append(ev)
    return out


# ---------------------------------------------------------------- timing recorder (pure)
def anchors(s: Setup, evs: list[Evaluation], as_of: int, close_ns: int) -> dict:
    """name -> (ts, price) | Unavailable | None (not known yet)."""
    first = next((e for e in evs if e.classification == TIMELY and e.as_of <= as_of), None)
    fx = (first.as_of, first.price) if first else \
        Unavailable("NEVER_TIMELY: no TIMELY evaluation by the close") if as_of >= close_ns else None
    return {"FIRST_DETECTION": (s.first_ts, s.first_price), "CONFIRMATION": (s.confirmed_ts, s.confirmed_price),
            "FIRST_EXECUTABLE": fx}


def timing_rows(s: Setup, evs: list[Evaluation], bars: Mapping[int, Bar], target, atr_at, as_of: int,
                close_ns: int, cfg) -> list[dict]:
    """Rows known at `as_of` (replay time): MFE/MAE per anchor x horizon once anchor + horizon <= as_of, from the 1m bars
    after the anchor only; time to target / invalidation once hit (or at the close). bars: 1m Bar by start_ns.
    target: level (paise) fixed at confirmation, or Unavailable. Values are paise and ATR at the anchor."""
    rows, d = [], s.direction
    for name, a in anchors(s, evs, as_of, close_ns).items():
        if a is None:
            continue
        if _u(a) or _u(a[1]):
            why = a if _u(a) else a[1]
            if as_of >= close_ns:
                rows += [_row(s, name, f"MFE_MAE_{h}m", why) for h in cfg.get("opportunity.timing.horizons_min")]
                rows += [_row(s, name, k, why) for k in ("TIME_TO_TARGET", "TIME_TO_INVALIDATION")]
            continue
        t0, p0 = a
        atr = atr_at(s.timeframe, t0)
        for h in cfg.get("opportunity.timing.horizons_min"):
            end = t0 + h * MIN
            if end > close_ns:
                if as_of >= close_ns:
                    rows.append(_row(s, name, f"MFE_MAE_{h}m", Unavailable("horizon ends after the session close")))
                continue
            if end > as_of:
                continue
            win = [bars.get(t0 + k * MIN) for k in range(h)]
            bad = next((t0 + k * MIN for k, b in enumerate(win) if b is None or not b.ok), None)
            if bad is not None:
                rows.append(_row(s, name, f"MFE_MAE_{h}m", Unavailable(f"INSUFFICIENT_DATA: unusable 1m bar at {_hhmm(bad)}")))
                continue
            hi, lo = max(b.h for b in win), min(b.l for b in win)
            mfe, mae = (hi - p0, p0 - lo) if d > 0 else (p0 - lo, hi - p0)
            rows.append(_row(s, name, f"MFE_MAE_{h}m", {
                "mfe_paise": mfe, "mae_paise": mae, "atr": atr if not _u(atr) else None,
                "mfe_atr": None if _u(atr) else round(mfe / atr, 6), "mae_atr": None if _u(atr) else round(mae / atr, 6)}))
        for kind, hit in (("TIME_TO_TARGET", lambda b: not _u(target) and (b.h >= target if d > 0 else b.l <= target)),
                          ("TIME_TO_INVALIDATION", lambda b: not _u(s.structural_stop)
                           and (b.c <= s.structural_stop if d > 0 else b.c >= s.structural_stop))):
            if kind == "TIME_TO_TARGET" and _u(target):
                if as_of >= close_ns:
                    rows.append(_row(s, name, kind, target))
                continue
            t, val = t0, None
            while t + MIN <= min(as_of, close_ns):
                b = bars.get(t)
                if b is None or not b.ok:
                    val = Unavailable(f"INSUFFICIENT_DATA: unusable 1m bar at {_hhmm(t)} before any hit")
                    break
                if hit(b):
                    val = {"seconds": (b.end - t0) // S, "at": _hhmm(b.end), "resolution": "1m close"}
                    break
                t += MIN
            if val is None and as_of >= close_ns:
                val = {"seconds": None, "at": None, "resolution": "NOT_REACHED_BY_CLOSE"}
            if val is not None:
                rows.append(_row(s, name, kind, val))
    return rows


def _row(s: Setup, anchor: str, metric: str, value) -> dict:
    return {"setup_id": s.id, "anchor": anchor, "metric": metric,
            "value": {"UNAVAILABLE": value.reason} if _u(value) else value}


# ---------------------------------------------------------------- per-underlying context (pure over loaded data)
class Context:
    """Snapshots of one underlying at any as_of from its Phase 5 detections, 1m candles and Phase 4 states."""

    def __init__(self, und: str, tok: int, dets: list, c1: list[dict], pstates: Mapping | None):
        self.und, self.tok, self.dets, self.c1, self.pstates = und, tok, dets, c1, pstates
        self.rx = {p["end_ns"]: p["quality"].get("receive_ts") for p in c1}
        self.bars = {b.start: b for b in map(bar_of, c1)}
        self.ends = sorted(b.end for b in self.bars.values() if b.ok)       # usable 1m closes (as level_map's price)
        self.vw = defaultdict(list)
        for x in dets:
            if x.type == "VWAP":
                self.vw[int(x.timeframe[:-1])].append(x)
        self.vt = {tf: [x.confirmed_ts for x in v] for tf, v in self.vw.items()}
        self.lm: dict[int, LevelMap] = {}

    def _vwap(self, tf: int, t: int):
        i = bisect_right(self.vt.get(tf, []), t)
        return self.vw[tf][i - 1] if i else None

    def atr_at(self, tf: int, t: int) -> float | Unavailable:
        v = self._vwap(tf, t)
        return Unavailable(f"INSUFFICIENT_DATA: no {tf}m ATR at {_hhmm(t)}") if v is None or v.attrs["atr"] is None \
            else v.attrs["atr"]

    def snapshot(self, tf: int, t: int, vwap_atr_tf: int) -> Snapshot:
        if t not in self.lm:
            self.lm[t] = level_map(self.und, self.tok, self.dets, self.c1, t)
        lm, v = self.lm[t], self._vwap(tf, t)
        i = bisect_right(self.ends, t)
        bt = self.ends[i - 1] if i else None
        return Snapshot(t, lm.price, bt, None if bt is None else self.rx.get(bt), self.atr_at(tf, t),
                        Unavailable(f"INSUFFICIENT_DATA: no {tf}m VWAP at {_hhmm(t)}") if v is None else v.level,
                        lm, tuple(self.dets), self.pstates, self.atr_at(vwap_atr_tf, t))


def half_lives(cfg) -> dict[str, float]:
    """source_type -> half-life seconds usable by the AGE_VS_HALF_LIFE rule: only RECORDED, MEASURED, stage TENTATIVE or
    FINAL entries of the file named by `opportunity.half_life_file` (configs before v16 have no such key: {})."""
    try:
        f = cfg.get("opportunity.half_life_file")
    except KeyError:
        return {}
    p = REPO / f
    if not p.exists():
        return {}
    doc = json.loads(p.read_text())
    return {k: v["half_life_s"] for k, v in doc.get("entries", {}).get("RECORDED", {}).items()
            if v.get("status") == "MEASURED" and v.get("stage") in ("TENTATIVE", "FINAL") and v.get("half_life_s")}


def run_setups(setups: list[Setup], ctx: Mapping[str, Context], day: date, cfg, as_of: int | None = None):
    """Evaluations (every 1m close from confirmation to the close) and timing rows known at as_of (default: close)."""
    close = _ns(day, cfg.get("sessions.fno.close"))
    as_of = close if as_of is None else as_of
    evals, timing, hl = {}, [], half_lives(cfg)
    for s in setups:
        c = ctx[s.underlying]
        times = range(s.confirmed_ts, min(close, as_of) + 1, MIN)
        vtf = cfg.get("opportunity.exhaustion.vwap_atr_timeframe_min")
        evs = evals[s.id] = track(s, (c.snapshot(s.timeframe, t, vtf) for t in times), cfg, half_life=hl.get(s.source_type))
        target = next((e.obstacle[2] for e in evs if e.state == "ACTIVE" and e.as_of == s.confirmed_ts and e.obstacle),
                      Unavailable("NO_TARGET: no obstacle in the trade direction at confirmation"))
        timing += timing_rows(s, evs, c.bars, target, c.atr_at, as_of, close, cfg)
    return evals, timing


# ---------------------------------------------------------------- edge: day run, store, report, CLI
def run_date(cfg, d: str, hist, cadence):
    day, master, rows = load_day(cfg, cfg.root / d)
    near = near_candles(rows, master, day, cfg)
    dets = add_profile(structure_day(near, hist(day), cfg, day), near, master, rows, cfg.root / d, cfg, day)
    states, events = run_day(cfg, cfg.root / d, hist(day), cadence)
    pst = defaultdict(dict)
    for st in states:
        pst[st.underlying][st.ts_ns] = st
    ctx = {u: Context(u, tok, dets.get(u, []), cs["1m"], pst.get(u)) for u, (tok, cs) in near.items()}
    setups = [x for u, (tok, cs) in sorted(near.items()) for x in setups_from_structure(dets.get(u, []), cs, ctx[u].atr_at, cfg)]
    setups += setups_from_positioning(events, {u: cs["1m"] for u, (_, cs) in near.items()},
                                      lambda u, m, t: ctx[u].atr_at(m, t), cfg)
    evals, timing = run_setups(setups, ctx, day, cfg)
    return day, setups, evals, timing


def write(day_dir: Path, setups, evals, timing, version: str) -> int:
    """Append-only: INSERT OR IGNORE on natural keys + config version; never UPDATE or DELETE."""
    db = sqlite3.connect(Path(day_dir) / "opportunity.sqlite")
    try:
        db.executescript(
            "CREATE TABLE IF NOT EXISTS setups (id TEXT, config_version TEXT, family TEXT, underlying TEXT, payload TEXT, "
            "PRIMARY KEY (id, config_version));"
            "CREATE TABLE IF NOT EXISTS evaluations (setup_id TEXT, as_of INTEGER, config_version TEXT, state TEXT, "
            "classification TEXT, payload TEXT, PRIMARY KEY (setup_id, as_of, config_version));"
            "CREATE TABLE IF NOT EXISTS timing (setup_id TEXT, anchor TEXT, metric TEXT, config_version TEXT, payload TEXT, "
            "PRIMARY KEY (setup_id, anchor, metric, config_version));"
            "CREATE TABLE IF NOT EXISTS runs (config_version TEXT PRIMARY KEY, setups INTEGER, evaluations INTEGER, "
            "timing_rows INTEGER);")
        n = db.total_changes
        dump = lambda x: json.dumps(jsonable(x), sort_keys=True, separators=(",", ":"))  # noqa: E731
        db.executemany("INSERT OR IGNORE INTO setups VALUES (?,?,?,?,?)",
                       [(s.id, version, s.family, s.underlying, dump(s)) for s in setups])
        db.executemany("INSERT OR IGNORE INTO evaluations VALUES (?,?,?,?,?,?)",
                       [(e.setup_id, e.as_of, version, e.state, e.classification, dump(e)) for v in evals.values() for e in v])
        db.executemany("INSERT OR IGNORE INTO timing VALUES (?,?,?,?,?)",
                       [(r["setup_id"], r["anchor"], r["metric"], version, dump(r["value"])) for r in timing])
        # same transaction: a day counts as done for this config version only when everything above is stored
        db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?)",
                   (version, len(setups), sum(map(len, evals.values())), len(timing)))
        db.commit()
        return db.total_changes - n
    finally:
        db.close()


def summarize(setups, evals) -> dict:
    """Per family: classification at confirmation (first evaluation), ever TIMELY, how setups ended;
    pre_signal_move_atr distribution per classification at confirmation."""
    out = {}
    for fam in sorted({s.family for s in setups}) + ["ALL"]:
        ss = [s for s in setups if fam in ("ALL", s.family)]
        first = {s.id: next((e for e in evals[s.id] if e.state == "ACTIVE"), None) for s in ss}
        cls = Counter(e.classification if e else "NOT_EVALUATED" for e in first.values())
        pre = defaultdict(list)
        for s in ss:
            e = first[s.id]
            if e and not _u(s.pre_signal_move_atr):
                pre[e.classification].append(s.pre_signal_move_atr)
        q = lambda v: {"n": len(v), "p25": round(statistics.quantiles(v, n=4)[0], 3), "median": round(statistics.median(v), 3),  # noqa: E731
                       "p75": round(statistics.quantiles(v, n=4)[2], 3), "mean": round(statistics.fmean(v), 3)} \
            if len(v) >= 2 else {"n": len(v), "values": [round(x, 3) for x in v]}
        out[fam] = {"setups": len(ss), "at_confirmation": dict(sorted(cls.items())),
                    "ever_timely": sum(any(e.classification == TIMELY for e in evals[s.id]) for s in ss),
                    "timely_by_retest": sum(any(e.reason == "RETEST" for e in evals[s.id]) for s in ss),
                    "ended": dict(sorted(Counter(evals[s.id][-1].state if evals[s.id] else "NONE" for s in ss).items())),
                    "late_failed_rules": dict(sorted(Counter(r for s in ss for e in evals[s.id][:1] for r in e.failed_rules).items())),
                    "exhaustion_flags": dict(sorted(Counter(f.split(":")[0] for s in ss for e in evals[s.id]
                                                            for f in e.exhaustion_flags).items())),
                    "pre_signal_move_atr": {k: q(v) for k, v in sorted(pre.items())},
                    "pre_signal_unavailable": sum(_u(s.pre_signal_move_atr) for s in ss)}
    return out


def report(cfg, results: dict, out: Path) -> str:
    lines = ["# Phase 6 opportunity report", "",
             f"Generated by `python3 -m engine.opportunity` (config {cfg.version}, sha256 {cfg.sha256[:8]}). Classification "
             "at confirmation = each setup's first evaluation. pre_signal_move_atr is in ATR, signed in the trade direction.", ""]
    for d, sm in sorted(results.items()):
        lines += [f"## {d}", "", "```json", json.dumps(sm, indent=1), "```", ""]
    text = "\n".join(lines) + "\n"
    Path(out).write_text(text)
    return text


def load_cadence(cfg, path: Path) -> dict:
    path = Path(path)
    return parse_cadence(path.read_text(), cfg.get("positioning.oi_cadence_stat")) if path.exists() else {}


def process(cfg, d: str, hist, cadence, dry_run: bool = False) -> tuple[dict, dict]:
    """One recorded date: setups, evaluations and timing rows as of the close; stored unless dry_run."""
    day, setups, evals, timing = run_date(cfg, d, hist, cadence)
    written = 0 if dry_run else write(cfg.root / d, setups, evals, timing, cfg.version)
    return ({"date": d, "setups": len(setups), "evaluations": sum(map(len, evals.values())), "timing_rows": len(timing),
             "rows_written": written}, summarize(setups, evals))


def done(day_dir: Path, version: str) -> bool:
    p = Path(day_dir) / "opportunity.sqlite"
    if not p.exists():
        return False
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        return db.execute("SELECT 1 FROM sqlite_master WHERE name='runs'").fetchone() is not None and \
            db.execute("SELECT 1 FROM runs WHERE config_version=?", (version,)).fetchone() is not None
    finally:
        db.close()


def eod(root: Path, cadence_path: Path, cfg=None) -> dict:
    """EOD step (owner decision Q-OPP-6): each recorded day with snapshots and no completed run for this config version
    (so a missed or failed evening is caught up). Runs after the close, so every timing horizon up to 15:40 is due.
    `root` = the EOD job's storage root. A failing day is recorded and the next day still runs."""
    o = cfg or load()
    o = EngineConfig(o.version, o.sha256, {**o.values, "storage": {**o.values["storage"], "root": str(root)}})
    todo = [d for d in sorted(Path(root).iterdir()) if d.is_dir() and _is_day(d.name)
            and ((d / "snapshots.sqlite").exists() or (d / "parquet" / "snapshots").exists()) and not done(d, o.version)]
    if not todo:
        return {}
    cadence, hist, out = load_cadence(o, cadence_path), history_reader(o), {}
    for d in todo:
        try:
            out[d.name] = process(o, d.name, hist, cadence)[0]
        except Exception as e:
            out[d.name] = {"error": repr(e)}
    return out


def _is_day(name: str) -> bool:
    try:
        return date.fromisoformat(name).isoformat() == name
    except ValueError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.opportunity")
    ap.add_argument("dates", nargs="+")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--cadence", default=str(CADENCE_PATH))
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry-run", action="store_true", help="do not write <date>/opportunity.sqlite")
    a = ap.parse_args(argv)
    cfg = load(a.config)
    cadence, hist, results = load_cadence(cfg, a.cadence), history_reader(cfg), {}
    for d in a.dates:
        line, results[d] = process(cfg, d, hist, cadence, a.dry_run)
        print(json.dumps(line))
    if a.report:
        report(cfg, results, Path(a.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
