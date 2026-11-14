"""Phase 4: futures positioning hypotheses per underlying, from Phase 3 snapshots + the Phase 3 history store.

  python3 -m engine.positioning YYYY-MM-DD [...] [--report PATH] [--dry-run] [--config config/engine/v5.yaml]

Pure core: `evaluate_day(data, master, history, cadence, cfg, day)` reads no clock, disk or network. Time is the
1-minute F&O candle close of each evaluation. Every threshold is in config `positioning.*` (v5).

Inputs
- Today: 1m / 5m candles, combined OI and depth snapshots (`read_snapshots`). An input is OK iff its DataQuality
  status is OK and (for a price) the candle is COMPLETE; a feature is UNAVAILABLE if any input is not OK.
- History (owner decision): Kite minute candles in history.sqlite (source HISTORICAL_API), the
  contract's last `history_sessions` sessions before the day. Distributions are fixed for the day (no lookahead).
- OI cadence: docs/measured-oi-cadence.md (engine.oi_cadence). An OI window shorter than the series' measured
  `oi_cadence_stat` is disabled (combined OI: its COMBINED:<underlying> row, owner decision; near-month:
  the token's row). A series with no measurement disables every window.

Views (each a full classification): primary = index-residual price x combined futures OI; raw = raw price x
combined OI (transparency); near_month = residual price x near-month OI (secondary). For the beta reference
underlying itself (NIFTY) the raw price is primary. A quadrant is formed per OI window w from the price change
and the OI change over the same w. Significant = percentile vs the contract's own history beyond pct_up/pct_down
AND the change beyond the fixed floor.

Labels are positioning hypotheses read from price and OI only. See DISCLAIMER.
"""

import argparse
import gzip
import hashlib
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping

from .baselines import oi_change_distribution, percentile_rank, volume_baseline
from .candles import IST, MIN, S, DataQuality, Unavailable
from .config import REPO, ConfigError, EngineConfig, load_config
from .oi_cadence import DEFAULT_OUT as CADENCE_PATH, nearest_rank
from .provider import parse_master
from .snapshots import jsonable, read_snapshots
from .universe import registry_rows

DISCLAIMER = ("Positioning hypotheses are inferred from public price, volume and open-interest data only. They do "
              "not identify who traded and are not evidence of institutional buying or selling.")
DEFAULT_CONFIG = REPO / "config" / "engine" / "v5.yaml"

LONG_BUILDUP, SHORT_BUILDUP, SHORT_COVERING, LONG_UNWINDING = "LONG_BUILDUP", "SHORT_BUILDUP", "SHORT_COVERING", "LONG_UNWINDING"
NEUTRAL = "NEUTRAL_OR_MIXED"
QUADRANT = {(1, 1): LONG_BUILDUP, (-1, 1): SHORT_BUILDUP, (1, -1): SHORT_COVERING, (-1, -1): LONG_UNWINDING}
DIRECTION = {LONG_BUILDUP: "PRICE_UP", SHORT_COVERING: "PRICE_UP", SHORT_BUILDUP: "PRICE_DOWN", LONG_UNWINDING: "PRICE_DOWN"}
# Noise filters (phase text) + why a view is neutral without a filter.
FILTERS = ("OI_STALE", "OI_JUMP_INVALID", "ROLLOVER_WINDOW", "EXPIRY_DAY", "ILLIQUID_FUTURE", "INDEX_DRIVEN", "LOW_SAMPLE")
CODES = FILTERS + ("OI_WINDOW_DISABLED", "INSUFFICIENT_DATA", "NOT_SIGNIFICANT", "CONFLICTING_WINDOWS")

REQUIRED = [f"positioning.{k}" for k in (
    "price_windows_min", "oi_windows_min", "oi_cadence_stat", "history_sessions", "min_sample", "pct_up", "pct_down",
    "floor_price_pct", "floor_oi_pct", "beta.index_underlying", "beta.window_returns", "beta.min_returns",
    "atr.interval_min", "atr.bars", "feature_window_min", "basis.abnormal_z", "basis.min_samples", "oi_jump.multiple",
    "oi_jump.quantile", "rollover_days", "illiquid.window_min", "illiquid.min_trades", "illiquid.max_spread_bps",
    "confirm_count", "invalidation_atr")]


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


# ---------------------------------------------------------------- types
@dataclass(frozen=True)
class Feature:
    name: str
    value: float | Unavailable
    quality: DataQuality


@dataclass(frozen=True)
class WindowView:
    window_min: int
    price_change_pct: float | None
    price_percentile: float | None
    price_sig: int                 # +1 / -1 / 0
    oi_change_pct: float | None
    oi_percentile: float | None
    oi_sig: int
    quadrant: str | None           # set only when price and OI are both significant
    reason: str | None             # code when the window could not be evaluated


@dataclass(frozen=True)
class View:
    positioning_hypothesis: str
    reasons: tuple[str, ...]
    suppressed_hypothesis: str | None   # what the windows said before a noise filter suppressed it
    windows: tuple[WindowView, ...]


@dataclass(frozen=True)
class PositioningState:
    underlying: str
    ts_ns: int                     # evaluation time = 1m F&O candle close
    near_token: int
    near_symbol: str
    near_expiry: str
    oi_components: tuple[int, ...]
    primary: View
    raw: View
    near_month: View
    flags: tuple[str, ...]         # warnings that do not suppress (ROLLOVER_WINDOW on combined OI, ABNORMAL_BASIS, ...)
    features: tuple[Feature, ...]
    config_version: str

    def feature(self, name: str) -> float | None:
        f = next((f for f in self.features if f.name == name), None)
        return None if f is None or isinstance(f.value, Unavailable) else f.value


@dataclass
class DayData:
    c1: dict        # token -> end_ns -> 1m candle payload (dict, as published)
    c5: dict        # token -> end_ns -> 5m candle payload
    comb: dict      # underlying -> end_ns -> 1m combined OI payload
    depth: dict     # token -> [(receive_ns, payload)] sorted


def day_from_snapshots(rows) -> DayData:
    d = DayData(defaultdict(dict), defaultdict(dict), defaultdict(dict), defaultdict(list))
    for kind, key, ts, payload in rows:
        if kind == "candle" and key.endswith((":1m", ":5m")):
            p = json.loads(payload)
            (d.c1 if key.endswith(":1m") else d.c5)[p["token"]][p["end_ns"]] = p
        elif kind == "combined_oi" and key.endswith(":1m"):
            p = json.loads(payload)
            d.comb[p["underlying"]][p["end_ns"]] = p
        elif kind == "depth":
            d.depth[int(key)].append((ts, json.loads(payload)))
    for v in d.depth.values():
        v.sort(key=lambda r: r[0])
    return d


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _hhmm(ns: int) -> str:
    return datetime.fromtimestamp(ns / S, IST).strftime("%H:%M")


def iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / S, IST).isoformat()


class _Inputs:
    """One feature's inputs. The feature is UNAVAILABLE if any input is not OK (first problem's code wins)."""

    def __init__(self, t: int, stale_oi_s: float):
        self.t, self.stale, self.bad, self.src, self.oi_ages = t, stale_oi_s, [], set(), []

    def fail(self, code: str, text: str):
        self.bad.append((code, text))
        return None

    def candle(self, c, label: str, field: str = "close"):
        if c is None:
            return self.fail("INSUFFICIENT_DATA", f"{label}: no snapshot")
        self.src.add("snapshot")
        st, comp, v = c["quality"]["status"], c["completeness"], _int(c.get(field))
        ok_comp = ("COMPLETE",) if field in ("close", "high", "low", "vwap") else ("COMPLETE", "EMPTY")
        if field == "oi_at_close":
            age = c.get("oi_age_seconds")
            if st != "OK" and (age is None or age >= self.stale):
                return self.fail("OI_STALE", f"{label}: {st}, OI age {age}")
            if age is not None:
                self.oi_ages.append(age)
        if st != "OK" or comp not in ok_comp or v is None:
            return self.fail("INSUFFICIENT_DATA", f"{label}: {st}/{comp}")
        return v

    def combined(self, x, label: str):
        if x is None:
            return self.fail("INSUFFICIENT_DATA", f"{label}: no snapshot")
        self.src.add("snapshot")
        st, v = x["quality"]["status"], _int(x["oi"])
        if st == "DEGRADED":
            return self.fail("OI_STALE", f"{label}: DEGRADED, OI age {x['quality']['oi_age']}")
        if st != "OK" or v is None:
            return self.fail("INSUFFICIENT_DATA", f"{label}: {st}")
        self.oi_ages.append(x["quality"]["oi_age"])
        return v

    def hist(self, v, label: str):
        self.src.add("HISTORICAL_API")
        if v is None or isinstance(v, Unavailable):
            return self.fail("INSUFFICIENT_DATA", f"{label}: {v.reason if v else 'missing'}")
        return v

    def feature(self, name: str, compute: Callable[[], float | Unavailable]) -> Feature:
        v = Unavailable(f"{self.bad[0][0]}: " + "; ".join(t for _, t in self.bad)) if self.bad else compute()
        if isinstance(v, float):
            v = round(v, 6)
        ok = not isinstance(v, Unavailable)
        q = DataQuality("derived:positioning(" + "+".join(sorted(self.src)) + ")", None, None, self.t, None,
                        tuple(t for _, t in self.bad), max(self.oi_ages) if self.oi_ages else None, (),
                        "OK" if ok else "UNAVAILABLE")
        return Feature(name, v, q)


def code_of(v) -> str | None:
    if not isinstance(v, Unavailable):
        return None
    c = v.reason.split(":")[0]
    return c if c in CODES else "INSUFFICIENT_DATA"


# ---------------------------------------------------------------- history profile (pure)
@dataclass(frozen=True)
class Profile:
    sessions: tuple[str, ...]
    raw: dict                 # window -> sorted % price changes of the near-month future
    residual: dict            # window -> sorted % residual changes (empty for the beta reference itself)
    oi_comb: dict             # window (incl. 1) -> sorted % combined OI changes
    oi_near: dict
    beta_seed: tuple          # last beta.window_returns (rs, ri) 1-minute return pairs before the day
    volume: dict              # minute 'HH:MM' -> [median, n] (engine.baselines.volume_baseline)
    bars: tuple               # last atr.bars + 1 history bars (high, low, close) in paise
    prev_close: dict          # 'combined' / 'near' -> OI at the previous session's last minute, or Unavailable


def _by_minute(rows, keep) -> dict:
    out = defaultdict(dict)
    for r in rows:
        if r[0][:10] in keep:
            out[r[0][:10]][int(r[0][11:13]) * 60 + int(r[0][14:16])] = r
    return out


class _Beta:
    def __init__(self, n: int, k: int):
        self.n, self.k, self.q, self.s = n, k, deque(), [0.0] * 4   # sums of rs, ri, rs*ri, ri*ri

    def add(self, rs: float, ri: float) -> None:
        self.q.append((rs, ri))
        self._acc(rs, ri, 1)
        if len(self.q) > self.n:
            self._acc(*self.q.popleft(), -1)

    def _acc(self, rs, ri, sign):
        s = self.s
        s[0] += sign * rs
        s[1] += sign * ri
        s[2] += sign * rs * ri
        s[3] += sign * ri * ri

    def value(self) -> float | Unavailable:
        n = len(self.q)
        if n < self.k:
            return Unavailable(f"LOW_SAMPLE: {n} 1-minute return pairs < {self.k}")
        var = self.s[3] - self.s[1] ** 2 / n
        if var <= 1e-18:
            return Unavailable("INSUFFICIENT_DATA: index returns have no variance")
        return (self.s[2] - self.s[0] * self.s[1] / n) / var


def profile(near_rows, index_rows, fut_rows: Mapping[int, list], day: date, prev_day: date, cfg,
            is_index: bool) -> Profile:
    P = lambda k: cfg.get(f"positioning.{k}")  # noqa: E731
    n = P("history_sessions")
    sessions = sorted({r[0][:10] for r in near_rows if r[0][:10] < day.isoformat()})[-n:]
    keep = set(sessions)
    every = set(r[0][:10] for r in near_rows if r[0][:10] < day.isoformat())
    windows = sorted(set(P("oi_windows_min")))
    sc, ic = _by_minute(near_rows, every), _by_minute(index_rows, every)
    raw, res = defaultdict(list), defaultdict(list)
    beta = _Beta(P("beta.window_returns"), P("beta.min_returns"))
    for d in sorted(sc):
        s, i = sc[d], ic.get(d, {})
        for m in sorted(s):
            if not is_index and m - 1 in s and m in i and m - 1 in i:
                beta.add(s[m][4] / s[m - 1][4] - 1, i[m][4] / i[m - 1][4] - 1)
            if d not in keep:
                continue
            b = beta.value()
            for w in windows:
                if m - w not in s:
                    continue
                rs = s[m][4] / s[m - w][4] - 1
                raw[w].append(round(rs * 100, 6))
                if not is_index and not isinstance(b, Unavailable) and m in i and m - w in i:
                    res[w].append(round((rs - b * (i[m][4] / i[m - w][4] - 1)) * 100, 6))
    # Combined OI history: only minutes where every current component has OI (older contracts are not in the store).
    comb = defaultdict(dict)
    toks = sorted(fut_rows)
    per = {t: {r[0]: r[6] for r in fut_rows[t] if r[0][:10] in keep | {prev_day.isoformat()} and r[6] and r[6] > 0}
           for t in toks}
    for ts in sorted(set.intersection(*(set(v) for v in per.values()))) if per else []:
        comb[ts] = sum(per[t][ts] for t in toks)
    comb_rows = [[ts, None, None, None, None, None, oi] for ts, oi in comb.items()]
    ow = sorted(set([1] + windows))
    near_keep = [r for r in near_rows if r[0][:10] in keep]
    bars = []
    for d in sessions:
        byb = defaultdict(list)
        for m, r in sorted(sc.get(d, {}).items()):
            byb[(m - 555) // P("atr.interval_min")].append(r)
        bars += [(round(max(r[2] for r in v) * 100), round(min(r[3] for r in v) * 100), round(v[-1][4] * 100))
                 for _, v in sorted(byb.items())]
    pd = prev_day.isoformat()
    last_c = max((ts for ts in comb if ts[:10] == pd), default=None)
    last_n = max((r for r in near_rows if r[0][:10] == pd and r[6]), default=None, key=lambda r: r[0])
    miss = Unavailable(f"INSUFFICIENT_DATA: previous session {pd} not in the history store")
    return Profile(tuple(sessions), {w: sorted(v) for w, v in raw.items()}, {w: sorted(v) for w, v in res.items()},
                   oi_change_distribution([r for r in comb_rows if r[0][:10] in keep], day, n, ow)["windows"],
                   oi_change_distribution(near_keep, day, n, ow)["windows"],
                   tuple(beta.q), volume_baseline(near_keep, day, n)["minutes"],
                   tuple(bars[-(P("atr.bars") + 1):]),
                   {"combined": comb[last_c] if last_c else miss, "near": last_n[6] if last_n else miss})


def parse_cadence(text: str, stat: str) -> dict:
    """docs/measured-oi-cadence.md -> {token or 'COMBINED:<underlying>': max over dates of the `stat` column};
    rows without a value are skipped."""
    out, col = {}, None
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if "token" in cells:
            col, tc = cells.index(stat.replace("_", " ")), cells.index("token")
        elif col is not None and len(cells) > col and (cells[tc].isdigit() or cells[tc] == "combined"):
            try:
                v = float(cells[col])
            except ValueError:
                continue
            k = int(cells[tc]) if cells[tc].isdigit() else cells[tc - 1]
            out[k] = max(v, out.get(k, v))
    return out


def prev_session(day: date, cfg) -> date:
    hol = {str(h["date"]) for h in cfg.get("restrictions.holidays")}
    d = day - timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in hol:
        d -= timedelta(days=1)
    return d


# ---------------------------------------------------------------- evaluation (pure)
@dataclass(frozen=True)
class Contracts:
    underlying: str
    near: int
    near_symbol: str
    near_expiry: date
    futures: tuple[int, ...]
    spot: int | None


def contracts(master: Mapping[int, tuple], underlying: str, components, day: date) -> Contracts | None:
    futs = sorted((a[3], t, a[1]) for t, a in master.items()
                  if a[0] == underlying and a[2] == "FUT" and a[3] and a[3] >= day.isoformat())
    if not futs:
        return None
    spot = next((t for t, a in sorted(master.items()) if a[0] == underlying and a[8] == "NSE"), None)
    return Contracts(underlying, futs[0][1], futs[0][2], date.fromisoformat(futs[0][0]),
                     tuple(sorted(components)) or tuple(sorted(t for _, t, _ in futs)), spot)


def _sig(v: float, pct: float, floor: float, cfg) -> int:
    if v >= floor and pct >= cfg.get("positioning.pct_up"):
        return 1
    if v <= -floor and pct <= cfg.get("positioning.pct_down"):
        return -1
    return 0


def _pctile(dist, v, cfg):
    n = len(dist or ())
    if isinstance(v, Unavailable):
        return v
    if n < cfg.get("positioning.min_sample"):
        return Unavailable(f"LOW_SAMPLE: {n} historical observations < {cfg.get('positioning.min_sample')}")
    return percentile_rank(dist, v)


def _window(w, price, ppct, oi, opct, cfg) -> WindowView:
    vals = [price, ppct, oi, opct]
    reason = next((code_of(v) for v in (oi, opct, price, ppct) if code_of(v)), None)
    if reason:
        p = lambda x: None if isinstance(x, Unavailable) else x  # noqa: E731
        return WindowView(w, *map(p, (price, ppct)), 0, *map(p, (oi, opct)), 0, None, reason)
    ps = _sig(price, ppct, cfg.get("positioning.floor_price_pct"), cfg)
    os_ = _sig(oi, opct, cfg.get("positioning.floor_oi_pct"), cfg)
    return WindowView(w, *vals[:2], ps, *vals[2:], os_, QUADRANT.get((ps, os_)), None)


def classify(windows: tuple[WindowView, ...]) -> tuple[str, tuple[str, ...]]:
    quads = sorted({v.quadrant for v in windows if v.quadrant})
    if len(quads) > 1:
        return NEUTRAL, ("CONFLICTING_WINDOWS",)
    if quads:
        return quads[0], ()
    codes = {v.reason for v in windows if v.reason}
    if not codes or any(v.reason is None for v in windows):
        codes.add("NOT_SIGNIFICANT")
    return NEUTRAL, tuple(sorted(codes))


def _view(windows, suppress: tuple[str, ...] = ()) -> View:
    hyp, reasons = classify(windows)
    if hyp != NEUTRAL and suppress:
        return View(NEUTRAL, tuple(sorted(suppress)), hyp, windows)
    return View(hyp, tuple(sorted(set(reasons) | set(suppress))) if hyp == NEUTRAL else reasons, None, windows)


def evaluate_day(data: DayData, master: Mapping[int, tuple], history: Callable[[int], list],
                 cadence: Mapping[int, float], cfg, day: date) -> list[PositioningState]:
    """Every underlying with combined OI snapshots, at every 1m close. `history(token)` -> Kite minute rows
    [ts, open, high, low, close, volume, oi] before `day` (edge: history.sqlite)."""
    idx_name = cfg.get("positioning.beta.index_underlying")
    idx = contracts(master, idx_name, (), day)
    idx_rows = history(idx.near) if idx else []
    prev = prev_session(day, cfg)
    out = []
    for und in sorted(data.comb):
        comps = next(iter(data.comb[und].values()))["components"]
        c = contracts(master, und, [x[0] for x in comps], day)
        if c is None:
            continue
        is_index = und == idx_name
        prof = profile(history(c.near), idx_rows, {t: history(t) for t in c.futures}, day, prev, cfg, is_index)
        out += _evaluate_underlying(data, c, idx, prof, cadence, cfg, day, is_index)
    return out


def _evaluate_underlying(data, c: Contracts, idx: Contracts | None, prof: Profile, cadence, cfg, day, is_index):
    P = lambda k: cfg.get(f"positioning.{k}")  # noqa: E731
    stale = cfg.get("quality.stale_oi_s")
    c1, near1, spot1 = data.c1, data.c1.get(c.near, {}), data.c1.get(c.spot, {}) if c.spot else {}
    inear = data.c1.get(idx.near, {}) if idx and not is_index else {}
    comb = data.comb[c.underlying]
    fw = P("feature_window_min")
    pw, ow = sorted(set(P("price_windows_min"))), sorted(set(P("oi_windows_min")))
    beta = _Beta(P("beta.window_returns"), P("beta.min_returns"))
    for rs, ri in prof.beta_seed:
        beta.add(rs, ri)
    basis_hist: dict[int, int] = {}
    dte = (c.near_expiry - day).days
    states = []
    for t in sorted(comb):
        F: dict[str, Feature] = {}
        I = lambda: _Inputs(t, stale)  # noqa: E731, E741

        def close_chg(series, label, w):
            x = I()
            a, b = x.candle(series.get(t), f"{label}@{_hhmm(t)}"), x.candle(series.get(t - w * MIN), f"{label}@{_hhmm(t - w * MIN)}")
            return x, (lambda: (a / b - 1) * 100)

        # 1. price change (futures, spot, index future)
        for w in pw:
            for name, ser, lab in (("fut", near1, c.near_symbol), ("spot", spot1, "spot")) + \
                    ((("index", inear, idx.near_symbol),) if inear else ()):
                x, f = close_chg(ser, lab, w)
                F[f"{name}_price_chg_{w}m_pct"] = x.feature(f"{name}_price_chg_{w}m_pct", f)
        # 8. beta (1-minute futures returns) and residual change
        if not is_index:
            a, b, ia, ib = (_int(s.get(k, {}).get("close")) if _ok(s.get(k)) else None
                            for s, k in ((near1, t), (near1, t - MIN), (inear, t), (inear, t - MIN)))
            if None not in (a, b, ia, ib):
                beta.add(a / b - 1, ia / ib - 1)
            x = I()
            x.src.update(("snapshot", "HISTORICAL_API"))
            bv = beta.value()
            F["beta"] = x.feature("beta", lambda: bv)
            for w in pw:
                fp, ip = F[f"fut_price_chg_{w}m_pct"].value, F.get(f"index_price_chg_{w}m_pct")
                x = I()
                for v, lab in ((fp, "fut change"), (ip.value if ip else Unavailable("no index future"), "index change"),
                               (bv, "beta")):
                    if isinstance(v, Unavailable):
                        x.fail(code_of(v), f"{lab}: {v.reason}")
                x.src.update(("snapshot", "HISTORICAL_API"))
                F[f"residual_chg_{w}m_pct"] = x.feature(f"residual_chg_{w}m_pct", lambda: fp - bv * ip.value)
        # 2 + 7. OI change (combined, near) per window, vs previous close, and percentile vs own history
        for w in ow:
            for name, get, toks, dist in (("combined", lambda e: comb.get(e), (f"COMBINED:{c.underlying}",), prof.oi_comb),
                                          ("near", lambda e: near1.get(e), (c.near,), prof.oi_near)):
                x = I()
                cad = [cadence.get(tk) for tk in toks]
                if any(v is None for v in cad):
                    x.fail("OI_WINDOW_DISABLED", f"no measured OI cadence for {[tk for tk, v in zip(toks, cad) if v is None]}")
                elif w * 60 < max(cad):
                    x.fail("OI_WINDOW_DISABLED", f"{w} min < measured {P('oi_cadence_stat')} {max(cad)} s")
                else:
                    a, b = _oi(x, name, get(t), t), _oi(x, name, get(t - w * MIN), t - w * MIN)
                f = x.feature(f"{name}_oi_chg_{w}m_pct", lambda: (a / b - 1) * 100 if b else Unavailable("INSUFFICIENT_DATA: OI 0"))
                F[f.name] = f
                F[f"{name}_oi_pctile_{w}m"] = _pfeat(f"{name}_oi_pctile_{w}m", dist.get(str(w)), f.value, t, cfg)
        for name, get in (("combined", comb.get(t)), ("near", near1.get(t))):
            x = I()
            a, b = _oi(x, name, get, t), x.hist(prof.prev_close[name], "previous session close")
            F[f"{name}_oi_chg_prev_close_pct"] = x.feature(f"{name}_oi_chg_prev_close_pct", lambda: (a / b - 1) * 100)
        # price percentiles (raw and residual) for the OI windows
        for w in ow:
            F[f"raw_pctile_{w}m"] = _pfeat(f"raw_pctile_{w}m", prof.raw.get(w), F[f"fut_price_chg_{w}m_pct"].value, t, cfg)
            if not is_index:
                F[f"residual_pctile_{w}m"] = _pfeat(f"residual_pctile_{w}m", prof.residual.get(w),
                                                    F[f"residual_chg_{w}m_pct"].value, t, cfg)
        # 3. relative volume vs same-minute baseline; 4. volume / OI change
        ends = [t - k * MIN for k in range(fw)]
        x = I()
        vols = [x.candle(near1.get(e), f"{c.near_symbol}@{_hhmm(e)}", "volume") for e in ends]
        base = [prof.volume.get(_hhmm(e - MIN)) for e in ends]
        x.hist(None if any(b is None or not b[0] for b in base) else 1, "volume baseline")
        F[f"rvol_{fw}m"] = x.feature(f"rvol_{fw}m", lambda: sum(vols) / sum(b[0] for b in base))
        x = I()
        cv = [x.candle(c1.get(tk, {}).get(e), f"{tk}@{_hhmm(e)}", "volume") for tk in c.futures for e in ends]
        a, b = x.combined(comb.get(t), "combined OI"), x.combined(comb.get(t - fw * MIN), "combined OI")
        F[f"volume_oi_ratio_{fw}m"] = x.feature(f"volume_oi_ratio_{fw}m", lambda: sum(cv) / abs(a - b) if a != b
                                                else Unavailable("INSUFFICIENT_DATA: combined OI unchanged"))
        # 5. ATR, VWAP deviation, ATR-normalized move, momentum
        F["atr"] = _atr(near1, data.c5.get(c.near, {}), prof, t, cfg, stale)
        atr = F["atr"].value
        x = I()
        cl, vw = x.candle(near1.get(t), "close"), x.candle(near1.get(t), "vwap", "vwap")
        if isinstance(atr, Unavailable):
            x.fail(code_of(atr), f"atr: {atr.reason}")
        F["vwap_dev_atr"] = x.feature("vwap_dev_atr", lambda: (cl - vw) / atr)
        x = I()
        a, b = x.candle(near1.get(t), "close"), x.candle(near1.get(t - fw * MIN), "close")
        if isinstance(atr, Unavailable):
            x.fail(code_of(atr), f"atr: {atr.reason}")
        F[f"atr_move_{fw}m"] = x.feature(f"atr_move_{fw}m", lambda: (a - b) / atr)
        F[f"momentum_{fw}m_roc_pct"] = Feature(f"momentum_{fw}m_roc_pct", F[f"fut_price_chg_{fw}m_pct"].value,
                                                  F[f"fut_price_chg_{fw}m_pct"].quality)
        # 6. basis = futures - spot (paise), its change, abnormal flag
        x = I()
        a, b = x.candle(near1.get(t), "fut close"), x.candle(spot1.get(t), "spot close")
        F["basis"] = x.feature("basis", lambda: float(a - b))
        if not isinstance(F["basis"].value, Unavailable):
            basis_hist[t] = int(a - b)
        x = I()
        prev_b = basis_hist.get(t - fw * MIN)
        if prev_b is None or t not in basis_hist:
            x.fail("INSUFFICIENT_DATA", "basis unavailable at one end")
        F[f"basis_chg_{fw}m"] = x.feature(f"basis_chg_{fw}m", lambda: float(basis_hist[t] - prev_b))
        x = I()
        past = [v for k, v in basis_hist.items() if k < t]
        if t not in basis_hist or len(past) < P("basis.min_samples"):
            x.fail("INSUFFICIENT_DATA", f"{len(past)} earlier basis values today < {P('basis.min_samples')}")
        sd = statistics.pstdev(past) if len(past) > 1 else 0.0
        F["basis_z"] = x.feature("basis_z", lambda: (basis_hist[t] - statistics.fmean(past)) / sd if sd
                                 else Unavailable("INSUFFICIENT_DATA: basis has no variance today"))
        # levels used by events (price and OI points with their quality)
        x = I()
        cl = x.candle(near1.get(t), f"{c.near_symbol}@{_hhmm(t)}")
        F["fut_close"] = x.feature("fut_close", lambda: float(cl))
        x = I()
        oi_now = x.combined(comb.get(t), f"combined OI@{_hhmm(t)}")
        F["combined_oi"] = x.feature("combined_oi", lambda: float(oi_now))
        # windows -> views
        jump = {name: _jumps(get, dist, t, ow, cfg) for name, get, dist in
                (("combined", lambda e: comb.get(e), prof.oi_comb), ("near", lambda e: near1.get(e), prof.oi_near))}

        def wins(price_key, oi_name):
            out = []
            for w in ow:
                oi = F[f"{oi_name}_oi_chg_{w}m_pct"].value
                if jump[oi_name].get(w):
                    oi = Unavailable(f"OI_JUMP_INVALID: {jump[oi_name][w]}")
                price = F[f"fut_price_chg_{w}m_pct" if price_key == "raw" else f"residual_chg_{w}m_pct"].value
                out.append(_window(w, price, F[f"{price_key}_pctile_{w}m"].value, oi,
                                   F[f"{oi_name}_oi_pctile_{w}m"].value, cfg))
            return tuple(out)

        flags, common = [], []
        if dte == 0:
            common.append("EXPIRY_DAY")
        elif 0 < dte <= P("rollover_days"):
            flags.append(f"ROLLOVER_WINDOW: {dte} days to {c.near_expiry} (combined OI used)")
        liq = _illiquid(near1, data.depth.get(c.near, []), t, cfg)
        if liq:
            common.append(liq[0])
            flags.append(f"{liq[0]}: liquidity {liq[1]}")
        if not isinstance(F["basis_z"].value, Unavailable) and abs(F["basis_z"].value) > P("basis.abnormal_z"):
            flags.append(f"ABNORMAL_BASIS: z {F['basis_z'].value:.2f}")
        flags += [f"OI_JUMP_UNCHECKED: {v}" for v in sorted({j.get('unchecked') for j in jump.values()} - {None})]
        raw = _view(wins("raw", "combined"), tuple(common))
        if is_index:
            primary = raw
            near = _view(wins("raw", "near"), tuple(common) + (("ROLLOVER_WINDOW",) if 0 < dte <= P("rollover_days") else ()))
        else:
            pw_ = wins("residual", "combined")
            idx_driven = raw.suppressed_hypothesis is None and raw.positioning_hypothesis != NEUTRAL and \
                classify(pw_)[0] == NEUTRAL and all(p.reason is None and p.price_sig == 0
                                                    for p, r in zip(pw_, raw.windows) if r.quadrant)
            primary = _view(pw_, tuple(common) + (("INDEX_DRIVEN",) if idx_driven else ()))
            near = _view(wins("residual", "near"),
                         tuple(common) + (("ROLLOVER_WINDOW",) if 0 < dte <= P("rollover_days") else ()))
        states.append(PositioningState(c.underlying, t, c.near, c.near_symbol, c.near_expiry.isoformat(), c.futures,
                                       primary, raw, near, tuple(flags), tuple(F.values()), cfg.version))
    return states


def _ok(cndl) -> bool:
    return cndl is not None and cndl["quality"]["status"] == "OK" and cndl["completeness"] == "COMPLETE" \
        and _int(cndl["close"]) is not None


def _oi(x: _Inputs, name, snap, at):
    return x.combined(snap, f"combined OI@{_hhmm(at)}") if name == "combined" else \
        x.candle(snap, f"near OI@{_hhmm(at)}", "oi_at_close")


def _pfeat(name, dist, v, t, cfg) -> Feature:
    x = _Inputs(t, 0)
    x.src.add("HISTORICAL_API")
    if isinstance(v, Unavailable):
        x.fail(code_of(v), v.reason)
    return x.feature(name, lambda: _pctile(dist, v, cfg))


def _atr(near1, near5, prof: Profile, t, cfg, stale) -> Feature:
    n, k = cfg.get("positioning.atr.bars"), cfg.get("positioning.atr.interval_min")
    x = _Inputs(t, stale)
    x.src.add("HISTORICAL_API")
    today = [(e, p) for e, p in sorted(near5.items()) if e <= t]
    bars = list(prof.bars)
    for e, p in today[-(n + 1):]:
        h, lo, cl = (x.candle(p, f"5m@{_hhmm(e)}", f) for f in ("high", "low", "close"))
        bars.append((h, lo, cl))
    bars = bars[-(n + 1):]
    if len(bars) < n + 1:
        x.fail("INSUFFICIENT_DATA", f"{len(bars)} {k}-minute bars < {n + 1}")

    def calc():
        tr = [max(h - lo, abs(h - pc), abs(lo - pc)) for (h, lo, _), (_, _, pc) in zip(bars[1:], bars[:-1])]
        return statistics.fmean(tr) if any(tr) else Unavailable("INSUFFICIENT_DATA: zero true range")
    return x.feature("atr", calc)


def _jumps(get, dist, t, windows, cfg) -> dict:
    """{w: description} for windows containing an implausible 1-minute OI change; 'unchecked' if history is short."""
    d1 = sorted(abs(v) for v in (dist.get("1") or ()))
    if len(d1) < cfg.get("positioning.min_sample"):
        return {"unchecked": f"{len(d1)} historical 1-minute OI changes"}
    lim = cfg.get("positioning.oi_jump.multiple") * nearest_rank(d1, cfg.get("positioning.oi_jump.quantile"))
    out = {}
    for w in windows:
        for k in range(w):
            e = t - k * MIN
            a, b = (_raw_oi(get(x)) for x in (e, e - MIN))
            if a and b and abs((a / b - 1) * 100) > lim:
                out[w] = f"{_hhmm(e - MIN)}->{_hhmm(e)} {round((a / b - 1) * 100, 3)} % > {round(lim, 3)} %"
                break
    return out


def _raw_oi(snap):
    if snap is None or snap["quality"]["status"] not in ("OK",):
        return None
    return _int(snap.get("oi", snap.get("oi_at_close")))


def _illiquid(near1, depth, t, cfg) -> tuple[str, str] | None:
    P = lambda k: cfg.get(f"positioning.illiquid.{k}")  # noqa: E731
    cs = [near1.get(t - k * MIN) for k in range(P("window_min"))]
    # liquidity reads the trade count of every candle without a gap; a STALE empty minute is a real "no trade"
    if any(c is None or c["completeness"] == "PARTIAL" or _int(c["trades"]) is None for c in cs):
        return "INSUFFICIENT_DATA", f"trade count unknown in the last {P('window_min')} min (gap or missing candle)"
    n = sum(c["trades"] for c in cs)
    if n < P("min_trades"):
        return "ILLIQUID_FUTURE", f"{n} trades in {P('window_min')} min < {P('min_trades')}"
    last = next((d for r, d in reversed(depth) if r <= t), None)
    if last and _int(last["spread"]) is not None and isinstance(last["mid"], str):
        bps = last["spread"] / float(last["mid"]) * 1e4
        if bps > P("max_spread_bps"):
            return "ILLIQUID_FUTURE", f"spread {bps:.1f} bps > {P('max_spread_bps')}"
    return None


# ---------------------------------------------------------------- events (pure)
def _point(s: PositioningState | None, name: str) -> dict | None:
    f = None if s is None else next((f for f in s.features if f.name == name), None)
    if f is None:
        return None
    return {"ts": iso(s.ts_ns), "value": None if isinstance(f.value, Unavailable) else f.value,
            "oi_age_s": f.quality.oi_age, "status": f.quality.status}


def evidence(s: PositioningState, first: PositioningState, at: Mapping[int, PositioningState], cfg) -> dict:
    """Everything an event row carries besides its identity: the evidence at confirmation (state `s`)."""
    hyp, fw = s.primary.positioning_hypothesis, cfg.get("positioning.feature_window_min")
    w = max((x for x in s.primary.windows if x.quadrant == hyp), key=lambda x: x.window_min)
    up = DIRECTION[hyp] == "PRICE_UP"
    atr, vdev, rv = s.feature("atr"), s.feature("vwap_dev_atr"), s.feature(f"rvol_{fw}m")
    contra = [f"{name}: {v.positioning_hypothesis} {list(v.reasons)}"
              for name, v in (("raw (not index-adjusted) view", s.raw), ("near-month OI view", s.near_month))
              if v.positioning_hypothesis != hyp]
    for x in s.primary.windows:
        if x.quadrant and x.quadrant != hyp:
            contra.append(f"{x.window_min} min window: {x.quadrant}")
        elif x.reason:
            contra.append(f"{x.window_min} min window not evaluated: {x.reason}")
        elif not x.quadrant:
            contra.append(f"{x.window_min} min window not significant (price {x.price_sig:+d}, OI {x.oi_sig:+d})")
    if rv is not None and rv < 1:
        contra.append(f"relative volume {rv:.2f} < 1 (below the same-minute baseline)")
    if vdev is not None and (vdev < 0 if up else vdev > 0):
        contra.append(f"near-month price {'below' if up else 'above'} session VWAP ({vdev:+.2f} ATR)")
    contra += list(s.flags)
    contra += [f"unavailable: {f.name} ({f.value.reason})" for f in s.features if isinstance(f.value, Unavailable)
               and f.name in ("atr", "beta", f"rvol_{fw}m", "basis", "vwap_dev_atr", "combined_oi_chg_prev_close_pct")]
    first_px, k = first.feature("fut_close"), cfg.get("positioning.invalidation_atr")
    lvl = None if atr is None or first_px is None else round(first_px - k * atr if up else first_px + k * atr, 2)
    return {
        "price_first_observed_paise": first_px, "price_confirmed_paise": s.feature("fut_close"),
        "window_min": w.window_min,
        "oi_baseline": _point(at.get(s.ts_ns - w.window_min * MIN), "combined_oi"),
        "oi_current": _point(s, "combined_oi"),
        "oi_change_pct": w.oi_change_pct, "oi_percentile": w.oi_percentile,
        "residual_move_pct": s.feature(f"residual_chg_{w.window_min}m_pct"),
        "raw_move_pct": s.feature(f"fut_price_chg_{w.window_min}m_pct"),
        "price_percentile": w.price_percentile, "beta": s.feature("beta"),
        f"rvol_{fw}m": rv,
        "vwap": {"relation": None if vdev is None else "ABOVE" if vdev > 0 else "BELOW" if vdev < 0 else "AT",
                 "deviation_atr": vdev},
        "atr_paise": atr,
        "views": {"primary": [s.primary.positioning_hypothesis, list(s.primary.reasons)],
                  "raw": [s.raw.positioning_hypothesis, list(s.raw.reasons)],
                  "near_month": [s.near_month.positioning_hypothesis, list(s.near_month.reasons)]},
        "data_quality": {f.name: f.quality.status for f in s.features},
        "contradicting_evidence": contra,
        "invalidation": [
            {"rule": "OPPOSITE_HYPOTHESIS", "detail": "a non-neutral primary hypothesis with the opposite price direction"},
            {"rule": "PRICE_THROUGH_FIRST_OBSERVED", "level_paise": lvl,
             "detail": f"near-month 1m close {'<=' if up else '>='} first_observed price {'-' if up else '+'} {k} ATR"
                       + ("" if lvl is not None else " (UNAVAILABLE: no ATR or first price)")}],
    }


def track_events(states: list[PositioningState], cfg) -> list[dict]:
    """Append-only event rows. CONFIRMED after `confirm_count` consecutive evaluations with the same non-neutral
    primary hypothesis; INVALIDATED (a new row) on the opposite price direction or on price back through the
    first_observed price by `invalidation_atr` ATR. A new CONFIRMED needs a fresh run."""
    k, rows = cfg.get("positioning.confirm_count"), []
    by_u = defaultdict(dict)
    for s in states:
        by_u[s.underlying][s.ts_ns] = s
    for und in sorted(by_u):
        at, run, active = by_u[und], None, None
        for t in sorted(at):
            s = at[t]
            h, px = s.primary.positioning_hypothesis, s.feature("fut_close")
            if active is not None:
                d, why = DIRECTION[active["positioning_hypothesis"]], None
                lvl = active["invalidation"][1]["level_paise"]
                if h != NEUTRAL and DIRECTION[h] != d:
                    why = f"OPPOSITE_HYPOTHESIS: {h}"
                elif lvl is not None and px is not None and (px <= lvl if d == "PRICE_UP" else px >= lvl):
                    why = f"PRICE_THROUGH_FIRST_OBSERVED: close {px} vs level {lvl}"
                if why:
                    rows.append({"event_id": active["event_id"], "state": "INVALIDATED", "ts": iso(t), "ts_ns": t,
                                 "underlying": und, "positioning_hypothesis": active["positioning_hypothesis"],
                                 "reason": why, "price_paise": px, "current_positioning_hypothesis": h,
                                 "config_version": s.config_version})
                    active = None
            run = None if h == NEUTRAL else (h, run[1], run[2] + 1) if run and run[0] == h else (h, s, 1)
            if run and run[2] == k and (active is None or active["positioning_hypothesis"] != h):
                first = run[1]
                eid = hashlib.sha256(f"{und}|{h}|{first.ts_ns}|{s.config_version}".encode()).hexdigest()[:16]
                active = {"event_id": eid, "state": "CONFIRMED", "ts": iso(t), "ts_ns": t, "underlying": und,
                          "contracts": {"price": [s.near_token, s.near_symbol, s.near_expiry],
                                        "oi_components": list(s.oi_components)},
                          "positioning_hypothesis": h, "direction": DIRECTION[h],
                          "first_observed_ts": iso(first.ts_ns), "confirmed_ts": iso(t),
                          **evidence(s, first, at, cfg), "config_version": s.config_version}
                rows.append(active)
    return rows


# ---------------------------------------------------------------- edge: day runs, store, report
def history_reader(cfg) -> Callable[[date], Callable[[int], list]]:
    db = sqlite3.connect(f"file:{cfg.root / 'history.sqlite'}?mode=ro", uri=True)

    def for_day(day: date):
        def rows(token: int) -> list:
            return [list(r) for r in db.execute(
                "SELECT ts, open, high, low, close, volume, oi FROM hist_candles WHERE token=? AND interval='minute' "
                "AND source='HISTORICAL_API' AND ts < ? ORDER BY ts", (token, day.isoformat()))]
        return rows
    return for_day


def run_day(cfg, day_dir: Path, history: Callable[[int], list], cadence: Mapping[int, float]):
    day = date.fromisoformat(day_dir.name)
    master = registry_rows(parse_master(gzip.decompress((day_dir / "instruments.csv.gz").read_bytes())),
                           cfg.get("universe.index_spots"))
    states = evaluate_day(day_from_snapshots(read_snapshots(day_dir)), master, history, cadence, cfg, day)
    return states, track_events(states, cfg)


def write_events(day_dir: Path, rows: list[dict]) -> int:
    """Append-only: INSERT OR IGNORE on (event_id, state, config_version); never UPDATE or DELETE."""
    db = sqlite3.connect(Path(day_dir) / "positioning.sqlite")
    try:
        db.execute("CREATE TABLE IF NOT EXISTS positioning_events (event_id TEXT, state TEXT, ts_ns INTEGER, "
                   "underlying TEXT, positioning_hypothesis TEXT, config_version TEXT, payload TEXT, "
                   "PRIMARY KEY (event_id, state, config_version))")
        n = db.total_changes
        db.executemany("INSERT OR IGNORE INTO positioning_events VALUES (?,?,?,?,?,?,?)",
                       [(r["event_id"], r["state"], r["ts_ns"], r["underlying"], r["positioning_hypothesis"],
                         r["config_version"], json.dumps(jsonable(r), sort_keys=True)) for r in rows])
        db.commit()
        return db.total_changes - n
    finally:
        db.close()


def summarize(states: list[PositioningState], events: list[dict]) -> dict:
    out = {}
    for view in ("primary", "raw", "near_month"):
        vs = [getattr(s, view) for s in states]
        out[view] = {"hypotheses": dict(sorted(Counter(v.positioning_hypothesis for v in vs).items())),
                     "suppressed_by": dict(sorted(Counter(r for v in vs if v.suppressed_hypothesis
                                                          for r in v.reasons).items())),
                     "neutral_reasons": dict(sorted(Counter(r for v in vs if v.positioning_hypothesis == NEUTRAL
                                                            for r in v.reasons).items()))}
    out["evaluations"], out["underlyings"] = len(states), len({s.underlying for s in states})
    out["events"] = dict(sorted(Counter(e["state"] for e in events).items()))
    return out


def report(cfg, results: dict, out: Path, n_examples: int = 10) -> str:
    lines = ["# Phase 4 positioning report", "", f"> {DISCLAIMER}", "",
             f"Generated by `python3 -m engine.positioning` (config {cfg.version}, sha256 {cfg.sha256[:8]}). "
             "Primary = index-residual price x combined futures OI. Counts are evaluations (underlying x 1-minute close).", ""]
    examples = []
    for d, (states, events) in sorted(results.items()):
        sm = summarize(states, events)
        lines += [f"## {d}", "", f"{sm['evaluations']} evaluations, {sm['underlyings']} underlyings, events {sm['events']}", ""]
        for view in ("primary", "raw", "near_month"):
            v = sm[view]
            lines += [f"**{view}** hypotheses: `{json.dumps(v['hypotheses'])}`  ",
                      f"suppressed (would have been non-neutral) by reason: `{json.dumps(v['suppressed_by'])}`  ",
                      f"all neutral reasons: `{json.dumps(v['neutral_reasons'])}`", ""]
        examples += [e for e in events if e["state"] == "CONFIRMED"]
    lines += [f"## Example events ({min(n_examples, len(examples))} of {len(examples)})", ""]
    for e in examples[:n_examples]:
        lines += ["```json", json.dumps(jsonable(e), indent=1, sort_keys=True), "```", ""]
    text = "\n".join(lines) + "\n"
    Path(out).write_text(text)
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.positioning")
    ap.add_argument("dates", nargs="+")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--cadence", default=str(CADENCE_PATH))
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry-run", action="store_true", help="do not write <date>/positioning.sqlite")
    a = ap.parse_args(argv)
    cfg = load(a.config)
    cp = Path(a.cadence)
    cadence = parse_cadence(cp.read_text(), cfg.get("positioning.oi_cadence_stat")) if cp.exists() else {}
    hist, results = history_reader(cfg), {}
    for d in a.dates:
        states, events = results[d] = run_day(cfg, cfg.root / d, hist(date.fromisoformat(d)), cadence)
        written = 0 if a.dry_run else write_events(cfg.root / d, events)
        print(json.dumps({"date": d, **summarize(states, events), "event_rows_written": written}))
    if a.report:
        report(cfg, results, Path(a.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
