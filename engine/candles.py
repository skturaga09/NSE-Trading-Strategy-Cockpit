"""Phase 3 aggregation: ticks -> 1/3/5/15-minute and daily candles, OI at each candle close,
combined futures OI per underlying, Tier B depth snapshots, and a DataQuality object on every snapshot.

Pure: fed only by engine events (engine.store.Event) and `advance(now_ns)`; reads no clock, disk or
network, so the live recorder consumer and a replay of the same session give the same snapshots.
Times are int ns since the epoch; prices stay the exchange integers (paise, F-WS-9).

Rules
- Feed order is arrival order (receive_ns, conn, seq). Only tick/depth events move the stream clock: the
  recorder can process a connection event ahead of frames that are still queued.
- Bucket time = the packet's exchange timestamp when it has one (full mode), else its receive time
  (quote packets carry none, F-WS-4/7). Each candle records which (`time_basis`).
- A tick is accepted iff receive_ns < end of its 1-minute bucket + candles.out_of_order_window_s. Otherwise
  it is published as a LateTick and used nowhere. That depends on the tick alone, not on delivery timing.
  A minute is final once the clock reaches its end + candles.finalize_delay_s (>= the window; long enough that
  a recorder 'stall' gap is always known first). 3/5/15-minute and daily candles roll up final
  minutes (buckets aligned to the session open, the last one cut at the close). Inside a minute, ticks
  are ordered by (bucket time, receive_ns, conn, seq). Exact duplicates are counted and dropped.
- Volume = rise of the cumulative day volume between consecutive accepted ticks. It is never interpolated.
  The minute's volume is UNAVAILABLE when a gap overlaps the minute or a delta crosses one, when there is no earlier value
  today (PARTIAL in both cases), or when the volume goes backwards (VOLUME_BACKWARDS). The baseline then
  restarts from the new value. "Trades" (the trade-count proxy) = ticks where the cumulative volume rose.
  OHLC uses those ticks only; an index has no volume, so every tick counts. Daily volume = the last
  cumulative day volume seen in session (the exchange's own figure).
- VWAP = the exchange's session VWAP (`atp`, F-QUOTE-6) of the candle's last tick. Not recomputed.
- Completeness: PARTIAL if a recorder gap (disconnect, queue drop, restart, disk stop of ticks) overlaps
  the candle or a minute's volume is unknown for a gap/first-tick reason. Else EMPTY if no trade, else COMPLETE.
- OI: change points come from accepted ticks. The first OI seen today, or the first after a gap, is a
  baseline with an unknown change time. oi_at_close = the latest point before the close. oi_last_change and
  oi_age are given only when that point is a known change, never as "updated at the close".
  With `quality.oi_age_basis: packet` (config v19+, owner D-67) oi_age instead counts from the latest accepted packet that
  carried OI (the broker re-confirming the value); oi_last_change stays the change time. Older configs: `change`.
- Combined futures OI = sum over the underlying's futures in the tier plan, at each F&O candle close.
  Age = max component age; a missing component or an unknown age is reported, never assumed.
"""

import bisect
import heapq
import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time as dtime
from decimal import Decimal
from typing import Iterable
from zoneinfo import ZoneInfo

from .store import Event, arrival_key

IST = ZoneInfo("Asia/Kolkata")
S = 1_000_000_000
MIN = 60 * S
DERIVATIVES = {"FUT", "CE", "PE"}  # F&O session; carry OI in full mode
QUOTE_FIELDS = ("ltp", "ltq", "atp", "volume", "tbq", "tsq", "open", "high", "low", "close")  # F-WS-4
FULL_FIELDS = QUOTE_FIELDS + ("last_trade_ts", "oi", "exchange_ts")                       # F-WS-5
CANDLE_GAPS = {"disconnect", "queue_drop", "restart", "disk_ticks", "stall"}                        # disk_depth: depth only


@dataclass(frozen=True)
class Unavailable:
    reason: str


@dataclass(frozen=True)
class DataQuality:
    source: str                    # 'kite.ws.full' | 'kite.ws.quote' | 'derived:combined_oi' | 'HISTORICAL_API'
    exchange_ts: int | None        # epoch s of the latest input (as sent)
    receive_ts: int | None         # ns
    processing_ts: int             # ns on the stream clock (deterministic, not wall time)
    feed_age: float | None         # s since the instrument's last accepted tick
    missing_fields: tuple[str, ...]
    oi_age: float | None           # s since the last known OI change
    warnings: tuple[str, ...]
    status: str                    # OK | DEGRADED | STALE | UNAVAILABLE


@dataclass(frozen=True)
class Candle:
    token: int
    interval: str                  # '1m' | '3m' | '5m' | '15m' | 'day'
    start_ns: int
    end_ns: int
    time_basis: str                # 'exchange' | 'receive'
    open: int | Unavailable
    high: int | Unavailable
    low: int | Unavailable
    close: int | Unavailable
    volume: int | Unavailable
    trades: int | Unavailable      # trade-count proxy
    ticks: int
    duplicate_ticks: int
    vwap: int | Unavailable        # exchange session VWAP at the last tick
    first_tick_ns: int | None
    last_tick_ns: int | None
    completeness: str              # COMPLETE | PARTIAL | EMPTY
    oi_at_close: int | Unavailable
    oi_last_change_ns: int | None
    oi_age_seconds: float | None
    quality: DataQuality


@dataclass(frozen=True)
class CombinedOI:
    underlying: str
    interval: str
    end_ns: int
    oi: int | Unavailable
    components: tuple[tuple[int, int | None, float | None], ...]   # (token, oi_at_close, oi_age_s)
    quality: DataQuality


@dataclass(frozen=True)
class DepthSnapshot:
    token: int
    receive_ns: int
    exchange_ts: int | None
    best_bid: int | Unavailable
    best_ask: int | Unavailable
    spread: int | Unavailable
    mid: Decimal | Unavailable
    bids: tuple[tuple[int, int, int], ...]   # (qty, price, orders) x 5, pending orders only (F-QUOTE-7)
    asks: tuple[tuple[int, int, int], ...]
    quality: DataQuality


@dataclass(frozen=True)
class QualityChange:
    token: int
    at_ns: int
    quality: DataQuality


@dataclass(frozen=True)
class LateTick:
    token: int
    receive_ns: int
    conn: int
    seq: int
    bucket_ns: int
    late_by_s: float               # receive time past the minute's end


@dataclass
class _Bin:
    start: int
    partial: bool
    o: int | None = None
    h: int | None = None
    l: int | None = None
    c: int | None = None
    vol: int = 0
    vol_bad: str | None = None
    trades: int = 0
    ticks: int = 0
    dups: int = 0
    first: int | None = None
    last: int | None = None
    atp: int | None = None
    last_cum: int | None = None
    last_tick: tuple | None = None  # (exchange_ts, receive_ns, fields)
    warnings: tuple = ()


class _Tok:
    def __init__(self):
        self.mode, self.tiers, self.kind, self.underlying, self.planned = None, "", "UNKNOWN", "", False
        self.bins = defaultdict(list)
        self.carry = None             # (cumulative volume, receive_ns) of the latest accepted tick in time order
        self.oi_last = None           # (oi, receive_ns)
        self.oi_t, self.oi_points = [], []   # bucket times, (t, oi, known_change, receive_ns)
        self.oi_seen_t, self.oi_seen_rns = [], []   # every accepted packet that carried OI (oi_age_basis: packet)
        self.day: list[_Bin] = []
        self.session_cum = None
        self.rns = {"price": None, "volume": None, "depth": None}
        self.last = None              # (exchange_ts, receive_ns, fields) of the latest accepted tick in arrival order
        self.final_last = None        # same, for the latest tick of the minutes already final (time order)
        self.status = "UNAVAILABLE"


def _ns(day: date, hhmm: str) -> int:
    return int(datetime.combine(day, dtime.fromisoformat(hhmm), IST).timestamp()) * S


class Aggregator:
    def __init__(self, cfg, day: date, trading_day: bool = True):
        window = cfg.get("candles.out_of_order_window_s")
        if window <= cfg.get("writer.flush_interval_s"):
            raise ValueError("candles.out_of_order_window_s must exceed writer.flush_interval_s "
                             "(queue-drop gaps reach consumers once per flush)")
        self.W = int(window * S)  # thresholds below: a field whose age reaches its threshold is stale
        delay = cfg.get("candles.finalize_delay_s")
        if delay < window or delay <= (cfg.get("ws.stall_after_s") + cfg.get("tiers.executor_interval_s")
                                        + cfg.get("writer.status_interval_s")):
            raise ValueError("candles.finalize_delay_s must be >= the out-of-order window and exceed "
                             "ws.stall_after_s + tiers.executor_interval_s + writer.status_interval_s")
        self.F = int(delay * S)
        self.intervals = [int(k) for k in cfg.get("candles.intervals_min")]
        self.thr = {k: int(cfg.get(f"quality.stale_{k}_s") * S) for k in ("price", "volume", "depth", "oi")}
        # configs before v19 have no key: they keep the change-based age they were recorded with
        self.oi_by_packet = cfg.values.get("quality", {}).get("oi_age_basis", "change") == "packet"
        self.sessions = {n: (_ns(day, cfg.get(f"sessions.{n}.open")), _ns(day, cfg.get(f"sessions.{n}.close")))
                         for n in ("fno", "cash")} if trading_day else {}
        self.toks: dict[int, _Tok] = {}
        self.clock = None
        self.next_min = None
        self.gaps: list[tuple[int, int]] = []
        self.open: dict[tuple, int] = {}
        self.shutting: set[int] = set()
        self.heap: list[tuple[int, int]] = []

    # ---------------------------------------------------------------- input
    def on_event(self, e: Event) -> list:
        out = []
        if e.kind in ("tick", "depth"):
            out += self.advance(e.receive_ns)
            (self._tick if e.kind == "tick" else self._depth)(e, out)
        elif e.kind == "conn":
            self._conn(dict(e.data), e)
        elif e.kind == "gap":
            self._gap(dict(e.data))
        return out

    def advance(self, now: int) -> list:
        """Emit everything due at or before `now`: final minutes (and their roll-ups) and status changes."""
        out = []
        if self.clock is not None and now <= self.clock:
            return out
        if self.next_min is None:
            self.next_min = (now - self.F) // MIN * MIN
        while True:
            fin = self.next_min + MIN + self.F
            if self.heap and self.heap[0][0] <= now and self.heap[0][0] < fin:
                at, tok = heapq.heappop(self.heap)
                self._recheck(tok, at, out)
            elif fin <= now:
                self._finalize(self.next_min, fin, out)
                self.next_min += MIN
            else:
                break
        self.clock = now
        return out

    def _tok(self, t: int) -> _Tok:
        return self.toks.setdefault(t, _Tok())

    def _due(self, at: int, tok: int) -> None:
        heapq.heappush(self.heap, (at, tok))

    def _tick(self, e: Event, out: list) -> None:
        f = dict(e.data)
        t = e.exchange_ts * S if e.exchange_ts else e.receive_ns
        m = t // MIN * MIN
        if e.receive_ns >= m + MIN + self.W or m < self.next_min:
            out.append(LateTick(e.token, e.receive_ns, e.conn, e.seq, m, round((e.receive_ns - m - MIN) / S, 3)))
            return
        T = self._tok(e.token)
        T.bins[m].append((t, e.receive_ns, e.conn, e.seq, f, e.exchange_ts))
        T.last = (e.exchange_ts, e.receive_ns, f)
        for k, thr in (("price", "ltp"), ("volume", "volume")):
            if f[thr] is not None:
                T.rns[k] = e.receive_ns
                self._due(e.receive_ns + self.thr[k], e.token)
        self._recheck(e.token, e.receive_ns, out)

    def _depth(self, e: Event, out: list) -> None:
        T = self._tok(e.token)
        T.rns["depth"] = e.receive_ns
        self._due(e.receive_ns + self.thr["depth"], e.token)
        if "B" in T.tiers:
            d = dict(e.data)
            side = lambda s: tuple((d[f"{s}{i}_qty"], d[f"{s}{i}_price"], d[f"{s}{i}_orders"]) for i in range(5))  # noqa: E731
            bids, asks = side("b"), side("s")
            bid = bids[0][1] if bids[0][0] else Unavailable("no bid in depth")
            ask = asks[0][1] if asks[0][0] else Unavailable("no offer in depth")
            both = not isinstance(bid, Unavailable) and not isinstance(ask, Unavailable)
            out.append(DepthSnapshot(e.token, e.receive_ns, e.exchange_ts, bid, ask,
                                     ask - bid if both else Unavailable("one side of the book is empty"),
                                     Decimal(bid + ask) / 2 if both else Unavailable("one side of the book is empty"),
                                     bids, asks, self._quality(T, e.receive_ns, oi_age=self._oi_age_now(T, e.receive_ns))))
        self._recheck(e.token, e.receive_ns, out)

    def _conn(self, d: dict, e: Event) -> None:
        kind = d["event"]
        if kind == "tier_plan":
            plan = json.loads(d["detail"])["plan"]
            for T in self.toks.values():
                T.planned = False
            for tok, (mode, tiers, k, und) in plan.items():
                T = self._tok(int(tok))
                T.mode, T.tiers, T.kind, T.underlying, T.planned = mode, tiers, k, und, True
        elif kind == "shutdown":
            self.shutting.add(e.conn)
        elif kind in ("close", "error", "noreconnect") and e.conn not in self.shutting:
            self.open.setdefault(("conn", e.conn), e.receive_ns)
        elif kind == "connect":
            self.open.pop(("conn", e.conn), None)
        elif kind == "disk_stop_ticks":
            self.open.setdefault(("disk",), e.receive_ns)

    def _gap(self, d: dict) -> None:
        if d["kind"] not in CANDLE_GAPS:
            return
        self.gaps.append((d["start_ns"], d["end_ns"]))
        self.open.pop(("disk",) if d["kind"] == "disk_ticks" else ("conn", d["conn"]), None)

    def _overlaps(self, a: int, b: int) -> bool:
        # shortcut: a gap on any connection counts for every instrument; upgrade to per-connection gaps once >1 connection is used
        return any(s < b and e > a for s, e in self.gaps) or any(s < b for s in self.open.values())

    # ---------------------------------------------------------------- minutes
    def _session(self, T: _Tok):
        return self.sessions.get("fno" if T.kind in DERIVATIVES else "cash")

    def _finalize(self, s: int, fin: int, out: list) -> None:
        e = s + MIN
        gapped = self._overlaps(s, e)
        for tok in sorted(self.toks):
            T = self.toks[tok]
            b = self._bin(tok, T, s, gapped, fin)
            sess = self._session(T)
            if b is None or sess is None or not sess[0] <= s < sess[1]:
                continue
            T.day.append(b)
            if b.last_cum is not None:
                T.session_cum = b.last_cum
            for k in self.intervals:
                if (e - sess[0]) % (k * MIN) == 0 or e == sess[1]:
                    start = sess[0] + (s - sess[0]) // (k * MIN) * k * MIN
                    out.append(self._candle(tok, T, f"{k}m", start, e, fin, T.day[-((e - start) // MIN):]))
            if e == sess[1]:
                out.append(self._candle(tok, T, "day", sess[0], e, fin, T.day))
        fno = self.sessions.get("fno")
        if fno and fno[0] < e <= fno[1]:
            labels = [f"{k}m" for k in self.intervals if (e - fno[0]) % (k * MIN) == 0 or e == fno[1]]
            groups = defaultdict(list)
            for tok, T in sorted(self.toks.items()):
                if T.planned and T.kind == "FUT":
                    groups[T.underlying].append(tok)
            for und in sorted(groups):
                c = self._combined(und, groups[und], e, fin)
                out += [replace(c, interval=lab) for lab in labels + (["day"] if e == fno[1] else [])]

    def _bin(self, tok: int, T: _Tok, s: int, gapped: bool, fin: int) -> _Bin | None:
        rows = sorted(T.bins.pop(s, ()), key=lambda r: r[:4])
        if not rows and not T.planned:
            return None
        b, seen, warn = _Bin(s, gapped, vol_bad="recorder gap inside the candle" if gapped else None), set(), set()
        for t, rns, conn, seq, f, ex in rows:
            sig = (t, tuple(f.items()))
            if sig in seen:
                b.dups += 1
                continue
            seen.add(sig)
            b.ticks += 1
            cum = f["volume"]
            trade = cum is None and f["ltp"] is not None
            if cum is not None:
                prev = T.carry
                if prev is None:
                    b.vol_bad, b.partial = b.vol_bad or "no earlier cumulative volume today", True
                elif self._overlaps(prev[1], rns):
                    b.vol_bad, b.partial = b.vol_bad or "volume delta spans a recorder gap", True
                elif cum < prev[0]:
                    b.vol_bad = b.vol_bad or f"cumulative volume fell {prev[0]} -> {cum}"
                    warn.add("VOLUME_BACKWARDS")
                elif cum > prev[0]:
                    b.vol += cum - prev[0]
                    trade = True
                T.carry, b.last_cum = (cum, rns), cum
            if f["oi"] is not None:
                oi = f["oi"]
                T.oi_seen_t.append(t)
                T.oi_seen_rns.append(rns)
                if self.oi_by_packet:
                    self._due(max(rns + self.thr["oi"], fin), tok)
                if T.oi_last is None or self._overlaps(T.oi_last[1], rns):
                    T.oi_t.append(t)
                    T.oi_points.append((t, oi, False, rns))
                elif oi != T.oi_last[0]:
                    T.oi_t.append(t)
                    T.oi_points.append((t, oi, True, rns))
                    self._due(max(rns + self.thr["oi"], fin), tok)
                T.oi_last = (oi, rns)
            if trade:
                p = f["ltp"]
                b.o = p if b.o is None else b.o
                b.h, b.l, b.c = p if b.h is None else max(b.h, p), p if b.l is None else min(b.l, p), p
                b.trades += 1
            if f["atp"] is not None:
                b.atp = f["atp"]
            b.first = t if b.first is None else b.first
            b.last, b.last_tick = t, (ex, rns, f)
            T.final_last = b.last_tick
        b.warnings = tuple(sorted(warn))
        return b

    # ---------------------------------------------------------------- outputs
    def _candle(self, tok: int, T: _Tok, interval: str, start: int, end: int, at: int, bins: list[_Bin]) -> Candle:
        tr = [b for b in bins if b.o is not None]
        partial = any(b.partial for b in bins)
        if T.kind == "INDEX":
            vol = trades = Unavailable("index has no volume (F-WS-7)")
        else:
            bad = next((b.vol_bad for b in bins if b.vol_bad), None)
            if interval == "day":
                vol = T.session_cum if T.session_cum is not None else Unavailable("no cumulative volume seen in session")
            else:
                vol = Unavailable(bad) if bad else sum(b.vol for b in bins)
            trades = Unavailable(bad) if bad else sum(b.trades for b in bins)
        none = Unavailable("no trade in candle")
        last = next((b.last_tick for b in reversed(bins) if b.last_tick), None)
        atp = next((b.atp for b in reversed(bins) if b.atp is not None), None)
        oi, oi_ts, oi_age, oi_warn = self._oi_at(T, end)
        warn = sorted({w for b in bins for w in b.warnings} | set(oi_warn) | ({"PARTIAL"} if partial else set()))
        # Quality as of the candle's close: ages from the latest accepted tick up to `end`, not from `at`.
        ref = T.final_last
        age = None if ref is None else max(0, end - ref[1])
        ages = {"price": age if ref and ref[2]["ltp"] is not None else None,
                "volume": age if ref and ref[2]["volume"] is not None else None}   # no depth rule for candles
        basis = "exchange" if (last[0] if last else T.mode == "full") else "receive"
        return Candle(tok, interval, start, end, basis,
                      tr[0].o if tr else none, max(b.h for b in tr) if tr else none,
                      min(b.l for b in tr) if tr else none, tr[-1].c if tr else none,
                      vol, trades, sum(b.ticks for b in bins), sum(b.dups for b in bins),
                      atp if atp is not None else Unavailable("no session VWAP in the packets"),
                      next((b.first for b in bins if b.first is not None), None),
                      next((b.last for b in reversed(bins) if b.last is not None), None),
                      "PARTIAL" if partial else ("EMPTY" if not tr else "COMPLETE"),
                      oi, oi_ts, oi_age, self._quality(T, at, ref, oi_age, warn, ages))

    def _expects_oi(self, T: _Tok) -> bool:
        return T.kind in DERIVATIVES and (T.last[2]["mode"] if T.last else T.mode) == "full"

    def _oi_at(self, T: _Tok, end: int):
        if T.kind not in DERIVATIVES:
            return Unavailable(f"{T.kind} has no OI"), None, None, []
        if not self._expects_oi(T):
            return Unavailable("quote mode has no OI (F-WS-6)"), None, None, []
        i = bisect.bisect_left(T.oi_t, end)
        if not i:
            return Unavailable("no OI observed before the close"), None, None, ["OI_UNAVAILABLE"]
        t, oi, known, _ = T.oi_points[i - 1]
        if self.oi_by_packet:   # age of the latest packet that re-confirmed the value; change time kept when known
            seen = T.oi_seen_t[bisect.bisect_left(T.oi_seen_t, end) - 1]
            return oi, t if known else None, round((end - seen) / S, 3), [] if known else ["OI_CHANGE_TIME_UNKNOWN"]
        if known:
            return oi, t, round((end - t) / S, 3), []
        return oi, None, None, ["OI_CHANGE_TIME_UNKNOWN"]

    def _oi_age_now(self, T: _Tok, at: int) -> float | None:
        if self.oi_by_packet:
            return round((at - T.oi_seen_rns[-1]) / S, 3) if T.oi_seen_rns else None
        if not T.oi_points or not T.oi_points[-1][2]:
            return None
        return round((at - T.oi_points[-1][3]) / S, 3)

    def _combined(self, und: str, toks: list[int], end: int, at: int) -> CombinedOI:
        comps = [(t, *self._oi_at(self.toks[t], end)) for t in toks]
        missing = [t for t, oi, *_ in comps if isinstance(oi, Unavailable)]
        ages = [age for _, _, _, age, _ in comps]
        warn = sorted({w for *_, ws in comps for w in ws})
        age = None if missing or any(a is None for a in ages) else max(ages)
        status = ("UNAVAILABLE" if missing else
                  "DEGRADED" if age is None or age * S >= self.thr["oi"] else "OK")
        q = DataQuality("derived:combined_oi", None, None, at, None, tuple(f"oi:{t}" for t in missing), age,
                        tuple(warn), status)
        total = Unavailable(f"no OI for tokens {missing}") if missing else sum(oi for _, oi, *_ in comps)
        return CombinedOI(und, "", end, total,
                          tuple((t, None if isinstance(oi, Unavailable) else oi, a) for t, oi, _, a, _ in comps), q)

    def _quality(self, T: _Tok, at: int, last=None, oi_age=None, warnings=(), ages=None) -> DataQuality:
        """ages (ns per field) default to `at` minus the field's latest receive time; candles pass their own."""
        if ages is None:
            ages = {k: None if v is None else at - v for k, v in T.rns.items()}
        ex, rns, f = last or T.last or (None, None, None)
        mode = f["mode"] if f else T.mode
        missing = ()
        if f:
            if T.kind == "INDEX":
                want = ("ltp", "exchange_ts") if mode == "full" else ("ltp",)
            else:
                want = FULL_FIELDS if mode == "full" else QUOTE_FIELDS
            missing = tuple(k for k in want if (not ex if k == "exchange_ts" else f.get(k) is None))
        feed = ages["price"] if ages["price"] is not None else ages["volume"]
        return DataQuality(f"kite.ws.{mode}" if mode else "kite.ws", ex, rns, at,
                           None if feed is None else round(feed / S, 3), missing, oi_age,
                           tuple(warnings), self._status(T, ages, missing, oi_age))

    def _status(self, T: _Tok, ages: dict, missing, oi_age) -> str:
        age = ages.get
        if age("price") is None:
            return "UNAVAILABLE"
        if age("price") >= self.thr["price"]:
            return "STALE"
        deg = bool(missing)
        if T.kind != "INDEX" and (age("volume") is None or age("volume") >= self.thr["volume"]):
            deg = True
        if self._expects_oi(T) and (oi_age is None or oi_age * S >= self.thr["oi"]):
            deg = True
        if ("B" in T.tiers and "depth" in ages and T.last and T.last[2]["mode"] == "full"
                and (age("depth") is None or age("depth") >= self.thr["depth"])):
            deg = True
        return "DEGRADED" if deg else "OK"

    def _recheck(self, tok: int, at: int, out: list) -> None:
        T = self.toks[tok]
        q = self._quality(T, at, oi_age=self._oi_age_now(T, at))
        if q.status != T.status:
            T.status = q.status
            out.append(QualityChange(tok, at, q))


def aggregate(events: Iterable[Event], cfg, day: date, trading_day: bool = True) -> list:
    """Replay helper: the same Aggregator over recorded events (use day_events(..., control=True))."""
    agg, out = Aggregator(cfg, day, trading_day), []
    for e in sorted(events, key=arrival_key):
        out += agg.on_event(e)
    return out
