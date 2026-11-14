"""Phase 5: price action, structure, liquidity and VWAP on each underlying's near-month future.

  python3 -m engine.structure YYYY-MM-DD [...] [--report PATH] [--dry-run] [--config config/engine/v6.yaml]

Pure core: `detect(underlying, token, candles, history_rows, cfg, day)` reads no clock, disk or network. Every threshold
is in config `structure.*` (v6, owner decisions in Phase 5). Instrument = the near-month future (earliest expiry >= day),
the Phase 4 price contract (owner decision).

Non-repainting rules
- Only COMPLETE candles with quality OK are used (no in-progress candle; nothing here is PROVISIONAL). A missing,
  PARTIAL, EMPTY or non-OK candle breaks every window that spans it: pivots, consolidation, pending breakout attempts,
  pending sweeps and zone reactions are dropped, never bridged.
- Each timeframe is one streaming detector fed bar by bar. A detection made at a bar carries confirmed_ts = that bar's
  close and is never changed afterwards; later facts are new detections (e.g. ZONE_TEST, ZONE_INVALIDATED). So the
  detections of a candle prefix ending at t are exactly the full-day detections with confirmed_ts <= t.
- Swing pivot: high > the `left_bars` highs before it and >= the `right_bars` highs after it (lows mirrored); it is
  confirmed at the close of the last right bar, and nothing uses it before that bar.
- Previous day/week levels come from the Phase 3 history store (Kite minutes, HISTORICAL_API); PDC = the last minute
  close of the previous session, not the exchange settlement price.

Detection types: PDH PDL PDC PWH PWL ORH ORL | SWING_HIGH SWING_LOW (attrs.swing_label HH/LH/EQ, HL/LL/EQ) TREND
BOS_UP BOS_DOWN CHOCH_UP CHOCH_DOWN (label HEURISTIC: first close through the last swing against the trend) |
CONSOLIDATION BREAKOUT_ACCEPTED BREAKDOWN_ACCEPTED BREAKOUT_FAILED BREAKDOWN_FAILED | DEMAND_ZONE SUPPLY_ZONE ZONE_TEST
ZONE_DEFENDED ZONE_INVALIDATED | EQUAL_HIGHS EQUAL_LOWS SWEEP_HIGH (bearish sweep + rejection) SWEEP_LOW (bullish
sweep + reclaim) RECLAIM LOSS (attrs.level_type PDH/PDL/ORH/ORL/VWAP) | VWAP (one per usable bar). Prices are paise.
"""

import argparse
import gzip
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping

from .candles import IST, MIN, S, Unavailable, _ns
from .config import REPO, ConfigError, EngineConfig, load_config
from .positioning import _hhmm, _int, contracts, history_reader, iso, prev_session
from .provider import parse_master
from .snapshots import jsonable, read_snapshots
from .universe import registry_rows

DEFAULT_CONFIG = REPO / "config" / "engine" / "v6.yaml"
REQUIRED = [f"structure.{k}" for k in (
    "timeframes_min", "swing.left_bars", "swing.right_bars", "opening_range_min", "atr.bars", "rvol_sessions",
    "consolidation.bars", "consolidation.max_width_atr", "acceptance.closes", "acceptance.hold_min",
    "acceptance.fail_bars", "zones.impulse_body_atr", "zones.base_max_bars", "zones.base_body_atr",
    "zones.reaction_bars", "liquidity.equal_tol_atr", "liquidity.sweep_reclaim_bars", "vwap.slope_bars",
    "vwap.extension_atr")]
KEY_LEVELS = ("PDH", "PDL", "ORH", "ORL")          # reclaim/loss levels (plus VWAP)
MAP_LEVELS = {"PDH", "PDL", "PDC", "PWH", "PWL", "ORH", "ORL", "SWING_HIGH", "SWING_LOW", "EQUAL_HIGHS", "EQUAL_LOWS"}
PROFILE_LEVELS = {"PROFILE_POC", "PROFILE_VAH", "PROFILE_VAL", "PROFILE_HVN", "PROFILE_LVN"}   # Phase 13 (engine.profile, v17)


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
class Detection:
    id: str
    type: str
    underlying: str
    token: int
    timeframe: str                 # '3m' '5m' '15m' | 'day' 'week' 'OR'
    level: int | None              # paise; zones / consolidation carry attrs.low / attrs.high instead
    created_ts: int                # ns: close of the candle the object describes (pivot, base, pierce...)
    confirmed_ts: int              # ns: earliest time it is knowable; never usable before
    source: tuple[str, ...]        # candles used: '<tf>@HH:MM' (start) or 'HISTORICAL_API:<date>'
    attrs: dict
    label: str                     # '' | 'HEURISTIC'
    config_version: str


@dataclass(frozen=True)
class Bar:
    start: int
    end: int
    o: int | None
    h: int | None
    l: int | None  # noqa: E741
    c: int | None
    vol: int | None
    vwap: int | None
    ok: bool


def bar_of(p: dict) -> Bar:
    o, h, lo, c = (_int(p[k]) for k in ("open", "high", "low", "close"))
    ok = p["completeness"] == "COMPLETE" and p["quality"]["status"] == "OK" and None not in (o, h, lo, c)
    return Bar(p["start_ns"], p["end_ns"], o, h, lo, c, _int(p["volume"]), _int(p["vwap"]), ok)


def _r(x):
    return None if x is None else round(x, 6)


def _det(typ, und, tok, tf, level, created, confirmed, source, attrs, version, label="") -> Detection:
    attrs = {k: (_r(v) if isinstance(v, float) else v) for k, v in sorted(attrs.items())}
    key = json.dumps([typ, und, tok, tf, level, created, confirmed, list(source), attrs, label], sort_keys=True)
    return Detection(hashlib.sha1(key.encode()).hexdigest()[:16], typ, und, tok, tf, level, created, confirmed,
                     tuple(source), attrs, label, version)


# ---------------------------------------------------------------- history (pure)
def _hist_bars(rows, tf: int) -> dict:
    """Kite minute rows -> {date: {slot: (o, h, l, c, vol)}} in paise, slots aligned to 09:15."""
    out = defaultdict(lambda: defaultdict(list))
    for r in rows:
        m = int(r[0][11:13]) * 60 + int(r[0][14:16]) - 555
        if m >= 0:
            out[r[0][:10]][m // tf].append(r)
    return {d: {s: (round(v[0][1] * 100), round(max(x[2] for x in v) * 100), round(min(x[3] for x in v) * 100),
                    round(v[-1][4] * 100), sum(x[5] or 0 for x in v)) for s, v in sorted(slots.items())}
            for d, slots in out.items()}


@dataclass(frozen=True)
class Seed:
    trs: tuple                     # last atr.bars true ranges (paise) from history
    close: int | None              # last history close when it is the previous session's final bar
    rvol: dict                     # slot -> (median volume, n sessions)


def seed(rows, tf: int, day: date, prev: date, cfg) -> Seed:
    bars = _hist_bars([r for r in rows if r[0][:10] < day.isoformat()], tf)
    n = (_ns(day, cfg.get("sessions.fno.close")) - _ns(day, cfg.get("sessions.fno.open"))) // MIN
    last_slot = -(-n // tf) - 1     # the last bucket is cut at the close (Phase 3), e.g. 15:39-15:40 for 3m
    trs, pc = [], None              # pc = (date, slot, close) of the previous bar
    for d in sorted(bars):
        for s, (o, h, lo, c, v) in bars[d].items():
            if pc and ((pc[0] == d and pc[1] == s - 1) or (pc[0] != d and pc[1] == last_slot and s == 0)):
                trs.append(max(h - lo, abs(h - pc[2]), abs(lo - pc[2])))
            pc = (d, s, c)
    close = pc[2] if pc and pc[0] == prev.isoformat() and pc[1] == last_slot else None
    rv = defaultdict(list)
    for d in sorted(bars)[-cfg.get("structure.rvol_sessions"):]:
        for s, b in bars[d].items():
            rv[s].append(b[4])
    return Seed(tuple(trs[-cfg.get("structure.atr.bars"):]), close,
                {s: (statistics.median(v), len(v)) for s, v in rv.items()})


def history_levels(und, tok, rows, day: date, cfg) -> list[Detection]:
    """PDH/PDL/PDC from the previous session, PWH/PWL from the previous Mon-Sun week (history store)."""
    prev, out, v = prev_session(day, cfg), [], cfg.version
    pd = [r for r in rows if r[0][:10] == prev.isoformat()]
    if pd:
        end = int(datetime.fromisoformat(pd[-1][0]).timestamp()) * S + MIN
        src = (f"HISTORICAL_API:{prev}",)
        for typ, lvl in (("PDH", max(r[2] for r in pd)), ("PDL", min(r[3] for r in pd)), ("PDC", pd[-1][4])):
            out.append(_det(typ, und, tok, "day", round(lvl * 100), end, end, src, {"session": str(prev)}, v))
    mon = day - timedelta(days=day.weekday() + 7)
    wk = [r for r in rows if mon.isoformat() <= r[0][:10] < (mon + timedelta(days=7)).isoformat()]
    if wk:
        end = int(datetime.fromisoformat(wk[-1][0]).timestamp()) * S + MIN
        days = sorted({r[0][:10] for r in wk})
        src = tuple(f"HISTORICAL_API:{d}" for d in days)
        for typ, lvl in (("PWH", max(r[2] for r in wk)), ("PWL", min(r[3] for r in wk))):
            out.append(_det(typ, und, tok, "week", round(lvl * 100), end, end, src,
                            {"week_of": str(mon), "sessions": len(days)}, v))
    return out


def opening_range(und, tok, c1: list[dict], day: date, cfg) -> list[Detection]:
    """ORH/ORL from the 1m candles of the first `opening_range_min` minutes; nothing unless every one is usable."""
    o, n = _ns(day, cfg.get("sessions.fno.open")), cfg.get("structure.opening_range_min")
    bars = {b.start: b for b in map(bar_of, c1)}
    win = [bars.get(o + k * MIN) for k in range(n)]
    if any(b is None or not b.ok for b in win):
        return []
    src, end = tuple(f"1m@{_hhmm(b.start)}" for b in win), o + n * MIN
    return [_det("ORH", und, tok, "OR", max(b.h for b in win), end, end, src, {"minutes": n}, cfg.version),
            _det("ORL", und, tok, "OR", min(b.l for b in win), end, end, src, {"minutes": n}, cfg.version)]


# ---------------------------------------------------------------- per-timeframe detector (pure, streaming)
@dataclass
class _Liq:                         # a liquidity level: confirmed swing or equal-highs/lows cluster
    det: Detection
    side: int                       # +1 highs, -1 lows
    members: tuple
    pend: dict | None = None


@dataclass
class _Zone:
    det: Detection
    side: int                       # +1 demand, -1 supply
    lo: int
    hi: int
    state: str                      # 'cool' (must leave first) | 'idle' | 'react'
    tests: int = 0
    react: dict = field(default_factory=dict)


class Detector:
    def __init__(self, und: str, tok: int, tf: int, sd: Seed, keys: list[Detection], cfg, day: date):
        g = lambda k: cfg.get(f"structure.{k}")  # noqa: E731
        self.und, self.tok, self.tf, self.tfs, self.v = und, tok, tf, f"{tf}m", cfg.version
        self.L, self.R = g("swing.left_bars"), g("swing.right_bars")
        self.CB, self.CW = g("consolidation.bars"), g("consolidation.max_width_atr")
        self.AN, self.AH, self.AK = g("acceptance.closes"), g("acceptance.hold_min") * MIN, g("acceptance.fail_bars")
        self.IB, self.BM, self.BB, self.RB = (g("zones.impulse_body_atr"), g("zones.base_max_bars"),
                                              g("zones.base_body_atr"), g("zones.reaction_bars"))
        self.EQ, self.SK = g("liquidity.equal_tol_atr"), g("liquidity.sweep_reclaim_bars")
        self.VS, self.VX = g("vwap.slope_bars"), g("vwap.extension_atr")
        self.open = _ns(day, cfg.get("sessions.fno.open"))
        self.sd, self.keys = sd, keys
        self.trs = deque(sd.trs, maxlen=g("atr.bars"))
        self.prev: Bar | None = None
        self.run: list[Bar] = []
        self.highs, self.lows = [], []            # confirmed swing Detections
        self.trend, self.choch = "UNDEFINED", False
        self.broken: set[str] = set()
        self.liq: list[_Liq] = []
        self.zones: list[_Zone] = []
        self.box: Detection | None = None
        self.att: dict | None = None

    # helpers
    def ref(self, b: Bar) -> str:
        return f"{self.tfs}@{_hhmm(b.start)}"

    def atr(self) -> float | None:
        return statistics.fmean(self.trs) if len(self.trs) == self.trs.maxlen and any(self.trs) else None

    def rvol(self, bars: list[Bar]) -> tuple[float | None, int | None]:
        base = [self.sd.rvol.get((b.start - self.open) // (self.tf * MIN)) for b in bars]
        if any(x is None or not x[0] for x in base) or any(b.vol is None for b in bars):
            return None, None
        return sum(b.vol for b in bars) / sum(x[0] for x in base), min(x[1] for x in base)

    def mk(self, b: Bar, typ, level, created, source, label="", **attrs) -> Detection:
        return _det(typ, self.und, self.tok, self.tfs, level, created, b.end, source, attrs, self.v, label)

    def _break(self) -> None:
        self.run, self.att = [], None
        self.liq = [x for x in self.liq if x.pend is None]   # what happened in the hole is unknown: level dropped
        for z in self.zones:
            if z.state == "react":
                z.state, z.react = "cool", {}

    # main step
    def on_bar(self, b: Bar) -> list[Detection]:
        out: list[Detection] = []
        contig = self.prev is not None and self.prev.ok and b.ok and b.start == self.prev.end
        first = self.prev is None and b.ok and b.start == self.open
        self.prev = b
        if not contig:
            self._break()
        if not b.ok:
            return out
        pc = self.run[-1].c if self.run else (self.sd.close if first else None)
        if pc is not None:
            self.trs.append(max(b.h - b.l, abs(b.h - pc), abs(b.l - pc)))
        self.run = (self.run + [b])[-max(self.L + self.R + 1, self.CB, self.BM + 1, self.VS + 1, 2):]
        atr = self.atr()
        self._breakout(b, atr, out)
        self._sweeps(b, atr, out)
        self._zones(b, atr, out)
        self._bos(b, out)
        self._reclaims(b, out)
        self._vwap(b, atr, out)
        self._pivots(b, atr, out)
        self._consolidation(b, atr, out)
        self._impulse(b, atr, out)
        return out

    def _breakout(self, b, atr, out):
        a = self.att
        if a:
            a["bars"] += 1
            if (b.c - a["level"]) * a["dir"] > 0:
                a["closes"] += 1
                a["refs"].append(self.ref(b))
                self._accept(b, out)
            else:
                if a["bars"] - 1 <= self.AK:
                    out.append(self.mk(b, "BREAKOUT_FAILED" if a["dir"] > 0 else "BREAKDOWN_FAILED", a["level"], a["t0"],
                                       a["refs"] + [self.ref(b)], box=a["box"], back_inside_bars=a["bars"] - 1))
                self.att = None
        if self.att is None and self.box is not None:
            hi, lo = self.box.attrs["high"], self.box.attrs["low"]
            d = 1 if b.c > hi else -1 if b.c < lo else 0
            if d:
                self.att = {"dir": d, "level": hi if d > 0 else lo, "t0": b.end, "closes": 1, "bars": 1,
                            "box": self.box.id, "refs": [self.ref(b)]}
                self._accept(b, out)

    def _accept(self, b, out):
        a = self.att
        via = "closes" if a["closes"] >= self.AN else "hold" if b.end - a["t0"] >= self.AH else None
        if via:
            out.append(self.mk(b, "BREAKOUT_ACCEPTED" if a["dir"] > 0 else "BREAKDOWN_ACCEPTED", a["level"], a["t0"],
                               a["refs"], box=a["box"], via=via, closes_beyond=a["closes"]))
            self.att = self.box = None

    def _sweeps(self, b, atr, out):
        for x in list(self.liq):
            p, s = x.det.level, x.side
            if x.pend is None and not (b.h > p if s > 0 else b.l < p):
                continue
            q = x.pend = x.pend or {"n": 0, "ext": p, "t0": b.end, "refs": []}
            q["n"] += 1
            q["ext"] = max(q["ext"], b.h) if s > 0 else min(q["ext"], b.l)
            q["refs"].append(self.ref(b))
            if (b.c <= p) if s > 0 else (b.c >= p):
                rv, n = self.rvol([b])
                out.append(self.mk(b, "SWEEP_HIGH" if s > 0 else "SWEEP_LOW", p, q["t0"], q["refs"],
                                   swept=x.det.id, swept_type=x.det.type, extreme=q["ext"],
                                   depth_atr=None if atr is None else abs(q["ext"] - p) / atr, reclaim_bars=q["n"],
                                   rejection_rvol=rv, rvol_sessions=n))
                self.liq.remove(x)
            elif q["n"] >= self.SK:
                self.liq.remove(x)              # held beyond: taken, not swept

    def _zones(self, b, atr, out):
        for z in list(self.zones):
            through = b.c < z.lo if z.side > 0 else b.c > z.hi
            touch = b.l <= z.hi if z.side > 0 else b.h >= z.lo
            if z.state == "cool" and not touch:
                z.state = "idle"
                continue
            if z.state == "idle" and touch:
                z.tests += 1
                pen = (z.hi - b.l) if z.side > 0 else (b.h - z.lo)
                out.append(self.mk(b, "ZONE_TEST", None, b.end, [self.ref(b)], zone=z.det.id, test=z.tests,
                                   low=z.lo, high=z.hi, penetration_atr=None if atr is None else pen / atr))
                z.state, z.react = "react", {"n": 0, "ext": None, "bars": [b], "t0": b.end}
                if not through:
                    continue
            if through:
                out.append(self.mk(b, "ZONE_INVALIDATED", None, z.det.created_ts, [self.ref(b)], zone=z.det.id,
                                   test=z.tests, low=z.lo, high=z.hi, close=b.c))
                self.zones.remove(z)
            elif z.state == "react":
                r = z.react
                r["n"] += 1
                r["bars"].append(b)
                r["ext"] = max(r["ext"] or b.h, b.h) if z.side > 0 else min(r["ext"] or b.l, b.l)
                if r["n"] == self.RB:
                    rv, n = self.rvol(r["bars"])
                    move = (r["ext"] - z.hi) if z.side > 0 else (z.lo - r["ext"])
                    out.append(self.mk(b, "ZONE_DEFENDED", None, r["t0"], [self.ref(x) for x in r["bars"]],
                                       zone=z.det.id, test=z.tests, low=z.lo, high=z.hi,
                                       reaction_atr=None if atr is None else move / atr, reaction_rvol=rv,
                                       rvol_sessions=n))
                    z.state, z.react = "cool", {}

    def _bos(self, b, out):
        hs, ls = (self.highs[-1] if self.highs else None), (self.lows[-1] if self.lows else None)
        d = 1 if self.trend == "UP" else -1 if self.trend == "DOWN" else 0
        if not d:
            return
        with_ = hs if d > 0 else ls
        against = ls if d > 0 else hs
        if with_ and with_.id not in self.broken and (b.c - with_.level) * d > 0:
            self.broken.add(with_.id)
            out.append(self.mk(b, "BOS_UP" if d > 0 else "BOS_DOWN", with_.level, b.end, [self.ref(b)],
                               swing=with_.id, trend=self.trend))
        if against and not self.choch and against.id not in self.broken and (against.level - b.c) * d > 0:
            self.broken.add(against.id)
            self.choch = True
            out.append(self.mk(b, "CHOCH_DOWN" if d > 0 else "CHOCH_UP", against.level, b.end, [self.ref(b)],
                               "HEURISTIC", swing=against.id, trend=self.trend,
                               rule="first close through the last swing against the trend"))

    def _reclaims(self, b, out):
        if len(self.run) < 2:
            return
        p = self.run[-2]
        lv = [(k.type, k.level) for k in self.keys if k.confirmed_ts <= p.end]
        if p.vwap is not None and b.vwap is not None:
            lv.append(("VWAP", None))
        for typ, lvl in lv:
            a, z = (p.vwap, b.vwap) if typ == "VWAP" else (lvl, lvl)
            if p.c <= a and b.c > z:
                out.append(self.mk(b, "RECLAIM", z, b.end, [self.ref(p), self.ref(b)], level_type=typ))
            elif p.c >= a and b.c < z:
                out.append(self.mk(b, "LOSS", z, b.end, [self.ref(p), self.ref(b)], level_type=typ))

    def _vwap(self, b, atr, out):
        if b.vwap is None:
            return
        old = self.run[-1 - self.VS].vwap if len(self.run) > self.VS else None
        dist = None if atr is None else (b.c - b.vwap) / atr
        out.append(self.mk(b, "VWAP", b.vwap, b.end, [self.ref(b)], close=b.c, atr=atr, distance_atr=dist,
                           slope_atr=None if atr is None or old is None else (b.vwap - old) / atr,
                           extended=None if dist is None else abs(dist) >= self.VX))

    def _pivots(self, b, atr, out):
        if len(self.run) < self.L + self.R + 1:
            return
        win = self.run[-(self.L + self.R + 1):]
        c, left, right = win[self.L], win[:self.L], win[self.L + 1:]
        src = [self.ref(x) for x in win]
        if c.h > max(x.h for x in left) and c.h >= max(x.h for x in right):
            self._swing(b, 1, c.h, c, src, atr, out)
        if c.l < min(x.l for x in left) and c.l <= min(x.l for x in right):
            self._swing(b, -1, c.l, c, src, atr, out)

    def _swing(self, b, s, p, c, src, atr, out):
        book = self.highs if s > 0 else self.lows
        last = book[-1].level if book else None
        up, dn, eq = ("HH", "LH", "EQ") if s > 0 else ("HL", "LL", "EQ")
        label = None if last is None else up if p > last else dn if p < last else eq
        d = self.mk(b, "SWING_HIGH" if s > 0 else "SWING_LOW", p, c.end, src, swing_label=label, pivot=self.ref(c))
        book.append(d)
        out.append(d)
        hl, ll = (self.highs[-1].attrs["swing_label"] if self.highs else None), (self.lows[-1].attrs["swing_label"] if self.lows else None)
        trend = "UP" if (hl, ll) == ("HH", "HL") else "DOWN" if (hl, ll) == ("LH", "LL") else \
            "RANGE" if hl and ll else "UNDEFINED"
        if trend != self.trend:
            out.append(self.mk(b, "TREND", None, b.end, src, state=trend, previous=self.trend, high=hl, low=ll))
            self.trend, self.choch = trend, False
        tol = None if atr is None else self.EQ * atr
        same = [x for x in self.liq if x.side == s and x.pend is None and tol is not None and abs(x.det.level - p) <= tol]
        if same:
            members = tuple(sorted({m for x in same for m in x.members} | {d.id}))
            lvl = (max if s > 0 else min)([p] + [x.det.level for x in same])
            cl = self.mk(b, "EQUAL_HIGHS" if s > 0 else "EQUAL_LOWS", lvl, b.end, src, members=list(members),
                         count=len(members), tolerance=tol)
            out.append(cl)
            self.liq = [x for x in self.liq if x not in same] + [_Liq(cl, s, members)]
        else:
            self.liq.append(_Liq(d, s, (d.id,)))

    def _consolidation(self, b, atr, out):
        if self.box is not None or atr is None or len(self.run) < self.CB:
            return
        w = self.run[-self.CB:]
        hi, lo = max(x.h for x in w), min(x.l for x in w)
        if hi - lo <= self.CW * atr:
            self.box = self.mk(b, "CONSOLIDATION", None, b.end, [self.ref(x) for x in w], high=hi, low=lo,
                               width_atr=(hi - lo) / atr, bars=self.CB)
            out.append(self.box)

    def _impulse(self, b, atr, out):
        if atr is None or abs(b.c - b.o) < self.IB * atr:
            return
        base = []
        for x in reversed(self.run[:-1]):
            if len(base) == self.BM or abs(x.c - x.o) > self.BB * atr:
                break
            base.append(x)
        if not base:
            return
        s = 1 if b.c > b.o else -1
        lo, hi = min(x.l for x in base), max(x.h for x in base)
        d = self.mk(b, "DEMAND_ZONE" if s > 0 else "SUPPLY_ZONE", None, base[0].end,
                    [self.ref(x) for x in reversed(base)] + [self.ref(b)], low=lo, high=hi,
                    impulse_body_atr=abs(b.c - b.o) / atr, base_bars=len(base))
        out.append(d)
        away = b.l > hi if s > 0 else b.h < lo
        self.zones.append(_Zone(d, s, lo, hi, "idle" if away else "cool"))


# ---------------------------------------------------------------- day evaluation (pure)
def detect(und: str, tok: int, candles: Mapping[str, list[dict]], rows: list, cfg, day: date) -> list[Detection]:
    """All detections of one underlying's near-month future for `day`. candles: '1m' / '<tf>m' -> published candle
    payloads (any order; only those passed are used). rows: Kite minute rows before `day` (history store)."""
    prev = prev_session(day, cfg)
    out = history_levels(und, tok, rows, day, cfg) + opening_range(und, tok, candles.get("1m", []), day, cfg)
    keys = [d for d in out if d.type in KEY_LEVELS]
    for tf in cfg.get("structure.timeframes_min"):
        det = Detector(und, tok, tf, seed(rows, tf, day, prev, cfg), keys, cfg, day)
        for p in sorted(candles.get(f"{tf}m", []), key=lambda p: p["start_ns"]):
            out += det.on_bar(bar_of(p))
    return sorted(out, key=lambda d: (d.confirmed_ts, d.timeframe, d.type, d.id))


def near_candles(rows, master: Mapping[int, tuple], day: date, cfg) -> dict:
    """snapshot rows -> {underlying: (token, {'1m'|'<tf>m': [payload]})} for each underlying's near-month future."""
    near = {}
    for und in sorted({a[0] for a in master.values() if a[2] == "FUT"}):
        c = contracts(master, und, (), day)
        if c:
            near[c.near] = und
    want = {"1m"} | {f"{t}m" for t in cfg.get("structure.timeframes_min")}
    out = {}
    for kind, key, _ts, payload in rows:
        if kind != "candle":
            continue
        tok, iv = key.split(":")
        if iv in want and int(tok) in near:
            out.setdefault(near[int(tok)], (int(tok), defaultdict(list)))[1][iv].append(json.loads(payload))
    return out


def evaluate_day(near: dict, history: Callable[[int], list], cfg, day: date) -> dict:
    """near = near_candles(...) -> {underlying: [Detection]}."""
    return {und: detect(und, tok, cs, history(tok), cfg, day) for und, (tok, cs) in sorted(near.items())}


# ---------------------------------------------------------------- level map (pure)
@dataclass(frozen=True)
class Obstacle:
    type: str
    timeframe: str
    level: int
    distance: int                  # paise, level - price
    distance_atr: dict             # tf -> distance / that timeframe's ATR at as_of (None if unknown)
    detection_id: str


@dataclass(frozen=True)
class LevelMap:
    underlying: str
    token: int
    as_of: int
    price: int | Unavailable       # last usable 1m close at or before as_of
    atr: dict                      # tf -> ATR (paise) from the latest VWAP detection at or before as_of
    above: Obstacle | None         # nearest level >= price
    below: Obstacle | None         # nearest level < price
    considered: int


def levels_at(dets: list[Detection], as_of: int) -> list[tuple[str, str, int, str]]:
    """Every obstacle known at as_of: (type, tf, level, id). Zones and consolidation boxes give both edges;
    invalidated zones drop out; VWAP = the latest per timeframe; Phase 13 profile levels = the latest profile snapshot only
    (none when that snapshot is PROFILE_UNAVAILABLE)."""
    seen = [d for d in dets if d.confirmed_ts <= as_of]
    dead = {d.attrs["zone"] for d in seen if d.type == "ZONE_INVALIDATED"}
    out, vw, prof = [], {}, []
    for d in seen:
        if d.type in MAP_LEVELS:
            out.append((d.type, d.timeframe, d.level, d.id))
        elif d.type in ("DEMAND_ZONE", "SUPPLY_ZONE", "CONSOLIDATION") and d.id not in dead:
            out += [(f"{d.type}_LOW", d.timeframe, d.attrs["low"], d.id), (f"{d.type}_HIGH", d.timeframe, d.attrs["high"], d.id)]
        elif d.type == "VWAP":
            vw[d.timeframe] = d
        elif d.type in PROFILE_LEVELS or d.type == "PROFILE_UNAVAILABLE":
            prof.append(d)
    snap = max((d.confirmed_ts for d in prof), default=None)
    out += [(d.type, d.timeframe, d.level, d.id) for d in prof if d.confirmed_ts == snap and d.type in PROFILE_LEVELS]
    return out + [("VWAP", tf, d.level, d.id) for tf, d in sorted(vw.items())]


def level_map(und: str, tok: int, dets: list[Detection], c1: list[dict], as_of: int) -> LevelMap:
    last = max((b for b in map(bar_of, c1) if b.ok and b.end <= as_of), default=None, key=lambda b: b.end)
    vw = {}
    for d in dets:
        if d.type == "VWAP" and d.confirmed_ts <= as_of:
            vw[d.timeframe] = d.attrs["atr"]
    lv = levels_at(dets, as_of)
    if last is None:
        return LevelMap(und, tok, as_of, Unavailable("INSUFFICIENT_DATA: no usable 1m candle at or before as_of"),
                        vw, None, None, len(lv))
    px = last.c

    def ob(t):
        return Obstacle(t[0], t[1], t[2], t[2] - px,
                        {tf: None if not a else round((t[2] - px) / a, 4) for tf, a in sorted(vw.items())}, t[3])
    up = min((t for t in lv if t[2] >= px), default=None, key=lambda t: (t[2], t[0], t[1]))
    dn = max((t for t in lv if t[2] < px), default=None, key=lambda t: (t[2], t[0], t[1]))
    return LevelMap(und, tok, as_of, px, vw, up and ob(up), dn and ob(dn), len(lv))


# ---------------------------------------------------------------- edge: day runs, store, report, CLI
def load_day(cfg, day_dir: Path):
    day = date.fromisoformat(day_dir.name)
    master = registry_rows(parse_master(gzip.decompress((day_dir / "instruments.csv.gz").read_bytes())),
                           cfg.get("universe.index_spots"))
    return day, master, read_snapshots(day_dir)


def write_detections(day_dir: Path, dets: list[Detection]) -> int:
    """Append-only: INSERT OR IGNORE on (id, config_version); never UPDATE or DELETE."""
    db = sqlite3.connect(Path(day_dir) / "structure.sqlite")
    try:
        db.execute("CREATE TABLE IF NOT EXISTS structure_detections (id TEXT, config_version TEXT, type TEXT, "
                   "underlying TEXT, timeframe TEXT, created_ts INTEGER, confirmed_ts INTEGER, payload TEXT, "
                   "PRIMARY KEY (id, config_version))")
        n = db.total_changes
        db.executemany("INSERT OR IGNORE INTO structure_detections VALUES (?,?,?,?,?,?,?,?)",
                       [(d.id, d.config_version, d.type, d.underlying, d.timeframe, d.created_ts, d.confirmed_ts,
                         json.dumps(jsonable(d), sort_keys=True)) for d in dets])
        db.commit()
        return db.total_changes - n
    finally:
        db.close()


def summarize(res: dict) -> dict:
    c = Counter((d.type, d.timeframe) for ds in res.values() for d in ds)
    return {"underlyings": len(res), "detections": sum(c.values()),
            "by_type": {f"{t}/{tf}": n for (t, tf), n in sorted(c.items())}}


def _fmt_map(m: LevelMap) -> str:
    def o(x):
        return "none" if x is None else f"{x.type} {x.timeframe} {x.level / 100:.2f} ({x.distance / 100:+.2f}, ATR {x.distance_atr})"
    px = m.price.reason if isinstance(m.price, Unavailable) else f"{m.price / 100:.2f}"
    return f"| {m.underlying} | {_hhmm(m.as_of)} | {px} | {o(m.above)} | {o(m.below)} | {m.considered} |"


def report(cfg, results: dict, out: Path, symbols=("NIFTY", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS"),
           times=("12:00", "14:00", "15:40"), n_sweeps=15) -> str:
    lines = ["# Phase 5 structure report", "",
             f"Generated by `python3 -m engine.structure` (config {cfg.version}, sha256 {cfg.sha256[:8]}). Instrument = "
             "near-month future. Prices in rupees. Level maps: nearest obstacle above (>= price) and below (< price).", ""]
    for d, (day, res, c1) in sorted(results.items()):
        sm = summarize(res)
        lines += [f"## {d}", "", f"{sm['detections']} detections, {sm['underlyings']} underlyings", "",
                  "| type/timeframe | count |", "|---|---|"] + [f"| {k} | {n} |" for k, n in sm["by_type"].items()]
        lines += ["", "### Level maps", "", "| underlying | as of | price | above | below | levels known |", "|---|---|---|---|---|---|"]
        for u in symbols:
            if u in res:
                tok = next((x.token for x in res[u]), None)
                lines += [_fmt_map(level_map(u, tok, res[u], c1.get(u, []), _ns(day, t))) for t in times]
        sw = [x for ds in res.values() for x in ds if x.type in ("SWEEP_HIGH", "SWEEP_LOW")]
        lines += ["", f"### Sweeps ({min(n_sweeps, len(sw))} of {len(sw)}, by depth)", "",
                  "| underlying | tf | type | swept | level | extreme | depth ATR | reclaim bars | rejection RVOL | at |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for x in sorted(sw, key=lambda x: -(x.attrs["depth_atr"] or 0))[:n_sweeps]:
            a = x.attrs
            lines.append(f"| {x.underlying} | {x.timeframe} | {x.type} | {a['swept_type']} | {x.level / 100:.2f} | "
                         f"{a['extreme'] / 100:.2f} | {a['depth_atr']} | {a['reclaim_bars']} | {a['rejection_rvol']} | "
                         f"{_hhmm(x.confirmed_ts)} |")
        lines.append("")
    text = "\n".join(lines) + "\n"
    Path(out).write_text(text)
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.structure")
    ap.add_argument("dates", nargs="+")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry-run", action="store_true", help="do not write <date>/structure.sqlite")
    a = ap.parse_args(argv)
    cfg = load(a.config)
    hist, results = history_reader(cfg), {}
    for d in a.dates:
        day, master, rows = load_day(cfg, cfg.root / d)
        near = near_candles(rows, master, day, cfg)
        res = evaluate_day(near, hist(day), cfg, day)
        c1 = {u: cs["1m"] for u, (_, cs) in near.items()}
        results[d] = (day, res, c1)
        written = 0 if a.dry_run else write_detections(cfg.root / d, [x for ds in res.values() for x in ds])
        print(json.dumps({"date": d, **summarize(res), "rows_written": written}))
    if a.report:
        report(cfg, results, Path(a.report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
