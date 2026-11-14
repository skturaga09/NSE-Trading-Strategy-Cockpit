"""Phase 13: session volume profile and Tier B depth behaviour on each underlying's near-month future.

Pure core: `levels`, `profile_at`, `profile_detections`, `depth_behaviour`, `depth_detections`, `profile_part`, `depth_part`
read no clock, disk or network; time is the `as_of` input. Thresholds: config v17 `profile.*` / `depth.*` (owner D-58..D-60,
ledger Q-13-*). Everything enters the engine as Phase 5 `Detection`s (owner D-59), so no earlier signature changes:
PROFILE_POC / _VAH / _VAL / _HVN / _LVN (or PROFILE_UNAVAILABLE with its reason) every `profile.snapshot_interval_min` from
the open, HVZ_REJECTION per 1m bar, DEPTH_BEHAVIOUR per 1m close (Tier B only).

Profile (owner D-60)
- TICK_BASED: the cumulative day volume's rise between two recorded packets is attributed at the later packet's last price
  (the Phase 3 delta rule; trades between packets at other prices are not visible). A minute is used only when its Phase 3
  1m candle is COMPLETE+OK (or EMPTY+OK, zero volume) and equals the minute's tick-delta sum, and only once every one of its
  ticks was received (at or before as_of). Like Phase 5, a 1m candle counts from its close.
- APPROXIMATE (no recorded ticks): each usable 1m candle's volume spread evenly over the bins of its high-low range. It is
  labelled APPROXIMATE in data, detections, score details and the UI, and is never a trade-at-price distribution.
- Coverage = usable minutes / elapsed `sessions.fno` minutes; below `profile.min_coverage` => UNAVAILABLE (no levels).
- Bin = first usable 1m open x `bin_bps`, rounded up to a whole multiple of the master tick_size (F-INST-2), fixed for the day.
  POC = highest-volume bin (tie: nearest the range middle, then lower); value area grows one bin at a time toward the larger
  neighbour (tie: both) until `value_area_pct` of the volume; VAL / VAH = its outer edges; POC / HVN / LVN = bin centres.

Depth behaviour (Tier B only, Q-13-4): computed from Phase 3 DepthSnapshots, which exist only for Tier B tokens; none =>
UNAVAILABLE NOT_TIER_B. Five-level depth shows pending orders only (F-QUOTE-7, F-QUOTE-8): not a full book and not executed
volume. Spoofing, iceberg orders and aggressor side are not inferred.
"""

import bisect
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from .candles import MIN, S, Unavailable, _ns
from .positioning import _hhmm, _int
from .snapshots import jsonable
from .structure import Detection, _det, bar_of

TICK_BASED, APPROXIMATE = "TICK_BASED", "APPROXIMATE"
TICK_NOTE = ("TICK_BASED: the cumulative-volume rise between two recorded packets is attributed at the later packet's last "
             "price; trades between packets at other prices are not visible")
APPROX_NOTE = ("APPROXIMATE (candle-based): each 1m candle's volume is spread evenly over its high-low range; "
               "not a trade-at-price distribution")
DEPTH_BASIS = "observed in 5-level depth (pending orders only: not a full book, not executed volume)"
NOT_INFERRED = "spoofing, iceberg orders and aggressor side are not inferred from 5-level depth"
DEPTH_LABEL = "OBSERVED_IN_5_LEVEL_DEPTH"
LEVEL_TYPES = ("PROFILE_POC", "PROFILE_VAH", "PROFILE_VAL", "PROFILE_HVN", "PROFILE_LVN")
SNAPSHOT_TYPES = LEVEL_TYPES + ("PROFILE_UNAVAILABLE",)


@dataclass(frozen=True)
class Levels:
    poc: int
    vah: int
    val: int
    hvn: tuple
    lvn: tuple


@dataclass(frozen=True)
class Profile:
    underlying: str
    token: int
    as_of: int
    method: str                    # TICK_BASED | APPROXIMATE
    note: str
    bin: int                       # paise
    bins: tuple                    # ((bin low, volume), ...) ascending, non-zero bins only
    poc: int
    vah: int
    val: int
    hvn: tuple
    lvn: tuple
    coverage: float
    total: float
    config_version: str


# ---------------------------------------------------------------- levels (pure)
def bin_size(first_price: int, tick: int, cfg) -> int:
    return max(1, -(-first_price * cfg.get("profile.bin_bps") // (10_000 * tick))) * tick


def levels(vols, b: int, cfg) -> Levels:
    """vols: {bin low (paise): volume}, b: bin size -> POC / value area / HVN / LVN in paise."""
    lo, hi = min(vols), max(vols)
    idx = list(range(lo, hi + b, b))
    v = [vols.get(x, 0) for x in idx]
    n, top = len(v), max(v)
    p = min((i for i in range(n) if v[i] == top), key=lambda i: (abs(2 * idx[i] + b - (lo + hi + b)), i))
    a = z = p
    acc, want = v[p], cfg.get("profile.value_area_pct") * sum(v)
    while acc < want and (a > 0 or z < n - 1):
        dn, up = (v[a - 1] if a > 0 else None), (v[z + 1] if z < n - 1 else None)
        if dn is None or (up is not None and up > dn):
            z, acc = z + 1, acc + up
        elif up is None or dn > up:
            a, acc = a - 1, acc + dn
        else:
            a, z, acc = a - 1, z + 1, acc + up + dn
    k = cfg.get("profile.hvn.smooth_bins") // 2
    s = [sum(v[max(0, i - k):i + k + 1]) / len(v[max(0, i - k):i + k + 1]) for i in range(n)]
    smax = max(s)

    def ext(i, w, cmp):            # strictly beyond the left neighbours, at least equal to the right ones (as a swing pivot)
        return all(cmp(s[i], s[j], True) for j in range(i - w, i)) and all(cmp(s[i], s[j], False) for j in range(i + 1, i + w + 1))
    wh, wl = cfg.get("profile.hvn.window_bins"), cfg.get("profile.lvn.window_bins")
    hv = [i for i in range(wh, n - wh) if i != p and s[i] >= cfg.get("profile.hvn.min_poc_ratio") * smax
          and ext(i, wh, lambda x, y, strict: x > y if strict else x >= y)]
    peaks = hv + [p]
    lv = [i for i in range(wl, n - wl) if s[i] <= cfg.get("profile.lvn.max_poc_ratio") * smax
          and ext(i, wl, lambda x, y, strict: x < y if strict else x <= y)
          and any(q < i for q in peaks) and any(q > i for q in peaks)]
    c = lambda i: idx[i] + b // 2  # noqa: E731
    return Levels(c(p), idx[z] + b, idx[a], tuple(map(c, hv)), tuple(map(c, lv)))


# ---------------------------------------------------------------- profile (pure)
def _ok(p: dict) -> bool:
    if p["quality"]["status"] != "OK":
        return False
    return (p["completeness"] == "COMPLETE" and bar_of(p).ok and _int(p["volume"]) is not None) or \
        (p["completeness"] == "EMPTY" and p["volume"] in (0, None))


def _tick_minutes(ticks, c1: list[dict], cfg) -> dict:
    """minute start -> (Counter {price: qty}, last receive_ns) for usable minutes (Phase 3 delta rule, checked against the
    minute's 1m candle volume)."""
    w = int(cfg.get("candles.out_of_order_window_s") * S)
    acc = []
    for ex, rns, conn, seq, ltp, cum in ticks:
        t = ex * S if ex else rns
        if rns < t // MIN * MIN + MIN + w:        # else a Phase 3 LateTick, used nowhere
            acc.append((t, rns, conn, seq, ltp, cum))
    acc.sort(key=lambda r: r[:4])
    prints, last, prev = defaultdict(Counter), {}, None
    for t, rns, _c, _s, ltp, cum in acc:
        m = t // MIN * MIN
        last[m] = max(last.get(m, rns), rns)
        if cum is None:
            continue
        if prev is not None and cum > prev:
            prints[m][ltp] += cum - prev
        prev = cum
    out = {}
    for p in c1:
        s = p["start_ns"]
        pr = prints.get(s, Counter())
        if _ok(p) and None not in pr and sum(pr.values()) == (p["volume"] or 0):
            out[s] = (pr, last.get(s, p["end_ns"]))
    return out


def _candle_minutes(c1: list[dict], b: int) -> dict:
    out = {}
    for p in c1:
        if not _ok(p):
            continue
        if p["completeness"] == "EMPTY":
            out[p["start_ns"]] = (Counter(), p["end_ns"])
            continue
        lo, hi = p["low"] // b * b, p["high"] // b * b
        k = (hi - lo) // b + 1
        out[p["start_ns"]] = (Counter({x: p["volume"] / k for x in range(lo, hi + b, b)}), p["end_ns"])
    return out


def _first_price(c1: list[dict], open_: int, as_of: int):
    bars = sorted((b for b in map(bar_of, c1) if b.ok and b.start >= open_ and b.end <= as_of), key=lambda b: b.start)
    return bars[0].o if bars else None


def _build(und, tok, c1, ticks, tick, as_of, day, cfg, minutes=None):
    open_, close = _ns(day, cfg.get("sessions.fno.open")), _ns(day, cfg.get("sessions.fno.close"))
    method = TICK_BASED if ticks else APPROXIMATE
    if not tick or tick <= 0:
        return Unavailable("INSUFFICIENT_DATA: master tick_size unavailable"), method
    first = _first_price(c1, open_, as_of)
    if first is None:
        return Unavailable(f"INSUFFICIENT_DATA: no usable 1m candle between the open and {_hhmm(as_of)}"), method
    b = bin_size(first, tick, cfg)
    if minutes is None:
        minutes = _tick_minutes(ticks, c1, cfg) if ticks else _candle_minutes(c1, b)
    elapsed = (min(as_of, close) - open_) // MIN
    used = [m for m, (_, rns) in minutes.items() if open_ <= m and m + MIN <= as_of and rns <= as_of]
    cov = len(used) / elapsed if elapsed > 0 else 0.0
    mc = cfg.get("profile.min_coverage")
    if cov < mc:
        return Unavailable(f"INSUFFICIENT_COVERAGE: coverage {cov:.2f} < profile.min_coverage {mc} ({len(used)}/{elapsed} "
                           f"usable minutes, {method})"), method
    vols = Counter()
    for m in used:
        for px, q in minutes[m][0].items():
            vols[px // b * b if ticks else px] += q
    vols = {k: q for k, q in vols.items() if q}
    if not vols:
        return Unavailable(f"NO_VOLUME: no traded volume between the open and {_hhmm(as_of)}"), method
    lv = levels(vols, b, cfg)
    return Profile(und, tok, as_of, method, TICK_NOTE if ticks else APPROX_NOTE, b, tuple(sorted(vols.items())), lv.poc,
                   lv.vah, lv.val, lv.hvn, lv.lvn, round(cov, 4), sum(vols.values()), cfg.version), method


def profile_at(und: str, tok: int, c1: list[dict], ticks, tick: int, as_of: int, day: date, cfg) -> Profile | Unavailable:
    """Session profile from the `sessions.fno` open to as_of. ticks: recorded rows (exchange_ts s, receive_ns, conn, seq, ltp,
    cumulative volume) of the token, or None / [] when none were recorded (=> APPROXIMATE). tick: master tick size (paise)."""
    return _build(und, tok, c1, ticks, tick, as_of, day, cfg)[0]


def _atr_series(dets, tf: int):
    pts = sorted((d.confirmed_ts, d.attrs.get("atr")) for d in dets if d.type == "VWAP" and d.timeframe == f"{tf}m")
    return [t for t, _ in pts], [a for _, a in pts]


def profile_detections(und: str, tok: int, c1: list[dict], ticks, tick: int, dets, day: date, cfg) -> list[Detection]:
    """Profile snapshots as detections, plus HVZ_REJECTION per 1m bar (zones = POC and HVNs of the latest snapshot at the
    bar's start; ATR = Phase 5 `profile.rejection.atr_timeframe_min` ATR at the bar's start, from `dets`)."""
    open_, close = _ns(day, cfg.get("sessions.fno.open")), _ns(day, cfg.get("sessions.fno.close"))
    step = cfg.get("profile.snapshot_interval_min") * MIN
    times = list(range(open_ + step, close + 1, step))
    times += [close] if times[-1:] != [close] else []
    minutes = _tick_minutes(ticks, c1, cfg) if ticks else None
    src = f"{'ticks' if ticks else '1m'}@{_hhmm(open_)}"
    out, snaps = [], []
    for t in times:
        first = _first_price(c1, open_, t)
        mins = minutes if ticks or first is None or not tick or tick <= 0 else _candle_minutes(c1, bin_size(first, tick, cfg))
        p, method = _build(und, tok, c1, ticks, tick, t, day, cfg, mins)
        snaps.append((t, p))
        if isinstance(p, Unavailable):
            out.append(_det("PROFILE_UNAVAILABLE", und, tok, "session", None, open_, t, (f"{src}-{_hhmm(t)}",),
                            {"reason": p.reason, "method": method}, cfg.version, method))
            continue
        attrs = {"method": p.method, "note": p.note, "coverage": p.coverage, "bin": p.bin, "total_volume": p.total,
                 "value_area_pct": cfg.get("profile.value_area_pct")}
        for typ, lvl in [("PROFILE_POC", p.poc), ("PROFILE_VAH", p.vah), ("PROFILE_VAL", p.val)] + \
                [("PROFILE_HVN", x) for x in p.hvn] + [("PROFILE_LVN", x) for x in p.lvn]:
            out.append(_det(typ, und, tok, "session", lvl, open_, t, (f"{src}-{_hhmm(t)}",), attrs, cfg.version, p.method))
    r = cfg.get("profile.rejection")
    at, av = _atr_series(dets, r["atr_timeframe_min"])
    st = [t for t, _ in snaps]
    for bar in sorted((b for b in map(bar_of, c1) if b.ok and open_ <= b.start and b.end <= close), key=lambda b: b.start):
        i, j = bisect.bisect_right(st, bar.start), bisect.bisect_right(at, bar.start)
        prof, atr = (snaps[i - 1][1] if i else None), (av[j - 1] if j else None)
        if not isinstance(prof, Profile) or not atr:
            continue
        tol, back = r["tol_atr"] * atr, r["back_atr"] * atr
        for zone, lvl in [("PROFILE_POC", prof.poc)] + [("PROFILE_HVN", x) for x in prof.hvn]:
            if bar.o < lvl and bar.h >= lvl - tol and bar.c <= lvl - back:
                d = -1                 # came from below, rejected back down: against longs
            elif bar.o > lvl and bar.l <= lvl + tol and bar.c >= lvl + back:
                d = 1                  # came from above, rejected back up: against shorts
            else:
                continue
            out.append(_det("HVZ_REJECTION", und, tok, "1m", lvl, bar.end, bar.end, (f"1m@{_hhmm(bar.start)}",),
                            {"direction": d, "zone": zone, "profile_snapshot": prof.as_of, "method": prof.method,
                             "atr": atr}, cfg.version, prof.method))
    return sorted(out, key=lambda d: (d.confirmed_ts, d.timeframe, d.type, d.id))


# ---------------------------------------------------------------- depth behaviour (pure, Tier B only)
def _cum_at(ticks, keys, t):
    """Latest cumulative volume received at or before t (None if unknown)."""
    i = bisect.bisect_right(keys, t)
    return next((r[5] for r in reversed(ticks[:i]) if r[5] is not None), None)


def _side(ss, side, ticks, keys, cfg):
    drop, rec = cfg.get("depth.replenish.drop"), cfg.get("depth.replenish.recover")
    wd = cfg.get("depth.withdrawal_drop")
    price = peak = prev = None
    dropped, reps, wds = False, 0, 0
    for x in ss:
        q, p, _ = x[side][0]
        if not q:
            price, prev = None, x
            continue
        if p != price:
            price, peak, dropped = p, q, False
        else:
            pq = prev[side][0][0]
            if q <= (1 - wd) * pq:
                i, j = bisect.bisect_right(keys, prev["receive_ns"]), bisect.bisect_right(keys, x["receive_ns"])
                a, z = _cum_at(ticks, keys, prev["receive_ns"]), _cum_at(ticks, keys, x["receive_ns"])
                if not any(r[4] == p for r in ticks[i:j]) and a is not None and z is not None and z - a < pq - q:
                    wds += 1           # size left the level with no trade at that price: observed withdrawal
            if not dropped and q <= (1 - drop) * peak:
                dropped = True
            elif dropped and q >= rec * peak:
                reps, dropped, peak = reps + 1, False, max(peak, q)
            elif not dropped:
                peak = max(peak, q)
        prev = x
    return reps, wds


def depth_behaviour(snaps, ticks, t: int, tick: int, cfg) -> dict | Unavailable:
    """Behaviour in the `depth.window_s` window ending at t. snaps: Phase 3 DepthSnapshot payloads of one Tier B token
    (bids / asks = [qty, price, orders] x 5); ticks: its recorded tick rows (as profile_at)."""
    w = int(cfg.get("depth.window_s") * S)
    ss = sorted((x for x in snaps if t - w < x["receive_ns"] <= t), key=lambda x: x["receive_ns"])
    if not ss:
        return Unavailable(f"NOT_TIER_B: no Tier B depth snapshot of this token in the {cfg.get('depth.window_s')} s "
                           f"before {_hhmm(t)} (depth behaviour is computed for Tier B only)")
    tk = sorted(ticks, key=lambda r: (r[1], r[2], r[3]))
    keys = [r[1] for r in tk]
    last = ss[-1]
    bq, aq = sum(q for q, _, _ in last["bids"]), sum(q for q, _, _ in last["asks"])
    bid = last["bids"][0][1] if last["bids"][0][0] else None
    ask = last["asks"][0][1] if last["asks"][0][0] else None
    (br, bw), (ar, aw) = _side(ss, "bids", tk, keys, cfg), _side(ss, "asks", tk, keys, cfg)
    ltp = [r[4] for r in tk[bisect.bisect_right(keys, t - w):bisect.bisect_right(keys, t)] if r[4] is not None]
    rng = max(ltp) - min(ltp) if ltp else None
    m, ab = cfg.get("depth.absorption.min_refills"), None
    if rng is not None and rng <= cfg.get("depth.absorption.max_range_ticks") * tick and max(ar, br) >= m and ar != br:
        ab = "POSSIBLE_ABSORPTION_AT_OFFER" if ar > br else "POSSIBLE_ABSORPTION_AT_BID"
    return {"basis": DEPTH_BASIS, "not_inferred": NOT_INFERRED, "window_s": cfg.get("depth.window_s"), "snapshots": len(ss),
            "spread": ask - bid if bid is not None and ask is not None else Unavailable("one side of the visible book is empty"),
            "imbalance": (bq - aq) / (bq + aq) if bq + aq else Unavailable("no visible pending quantity"),
            "bid_replenishments": br, "ask_replenishments": ar, "bid_withdrawals": bw, "ask_withdrawals": aw,
            "ltp_range": rng if rng is not None else Unavailable("no traded price in the window"),
            "possible_absorption": ab}


def depth_detections(und: str, tok: int, snaps, ticks, tick: int, day: date, cfg) -> list[Detection]:
    """DEPTH_BEHAVIOUR at each 1m close with Tier B snapshots in the window before it (none => no detection)."""
    open_, close = _ns(day, cfg.get("sessions.fno.open")), _ns(day, cfg.get("sessions.fno.close"))
    ss = sorted(snaps, key=lambda x: x["receive_ns"])
    keys, w = [x["receive_ns"] for x in ss], int(cfg.get("depth.window_s") * S)
    tk = sorted(ticks, key=lambda r: (r[1], r[2], r[3]))
    out = []
    for t in range(open_ + MIN, close + 1, MIN):
        win = ss[bisect.bisect_right(keys, t - w):bisect.bisect_right(keys, t)]
        if win:
            d = depth_behaviour(win, tk, t, tick, cfg)
            out.append(_det("DEPTH_BEHAVIOUR", und, tok, "depth", None, t, t, (f"depth@{_hhmm(t)}",), jsonable(d),
                            cfg.version, DEPTH_LABEL))
    return out


# ---------------------------------------------------------------- Phase 8 score parts (pure, weight 0 in v17: Q-13-6)
def _latest(dets, as_of: int, types):
    return max((x for x in dets if x.type in types and x.confirmed_ts <= as_of), key=lambda x: x.confirmed_ts, default=None)


def profile_part(d: int, price, dets, as_of: int) -> tuple:
    """(1.0 price on the trade side of the session POC / 0.0 / Unavailable, detail)."""
    last = _latest(dets, as_of, SNAPSHOT_TYPES)
    if last is None:
        u = Unavailable("NO_VOLUME_PROFILE: no profile snapshot at as_of")
        return u, f"volume profile: UNAVAILABLE ({u.reason})"
    if last.type == "PROFILE_UNAVAILABLE":
        return Unavailable(last.attrs["reason"]), f"volume profile ({last.label}): UNAVAILABLE ({last.attrs['reason']})"
    if isinstance(price, Unavailable):
        return price, f"volume profile: price {price.reason}"
    poc = next(x for x in dets if x.type == "PROFILE_POC" and x.confirmed_ts == last.confirmed_ts)
    m = poc.attrs["method"]
    side = "above" if price > poc.level else "below" if price < poc.level else "at"
    return (1.0 if (price - poc.level) * d > 0 else 0.0), (
        f"price {side} session POC {poc.level / 100:.2f} at {_hhmm(poc.confirmed_ts)} ({m}"
        f"{': ' + APPROX_NOTE if m == APPROXIMATE else ''}); weight 0 until out-of-sample evidence (Q-13-6)")


def depth_part(d: int, dets, as_of: int) -> tuple:
    """(1.0 visible imbalance with the trade and no possible absorption against it / 0.0 / Unavailable, detail)."""
    last = _latest(dets, as_of, ("DEPTH_BEHAVIOUR",))
    if last is None or as_of - last.confirmed_ts >= MIN:
        u = Unavailable("NOT_TIER_B: no Tier B depth behaviour for the price token at as_of")
        return u, f"depth behaviour ({DEPTH_BASIS}): UNAVAILABLE"
    imb, ab = last.attrs["imbalance"], last.attrs["possible_absorption"]
    if isinstance(imb, dict):
        return Unavailable(imb["UNAVAILABLE"]), f"depth behaviour ({DEPTH_BASIS}): imbalance UNAVAILABLE"
    against = ab == ("POSSIBLE_ABSORPTION_AT_OFFER" if d > 0 else "POSSIBLE_ABSORPTION_AT_BID")
    return (1.0 if imb * d > 0 and not against else 0.0), (
        f"depth behaviour {DEPTH_BASIS}: imbalance {imb:+.2f}, {ab or 'no possible absorption'}; weight 0 (Q-13-6)")


# ---------------------------------------------------------------- edge: recorded inputs
def load_ticks(day_dir: Path, tokens) -> dict | None:
    """{token: [(exchange_ts s, receive_ns, conn, seq, ltp, volume)]} from buffer.sqlite (read-only) or, after compaction,
    Parquet. None = no tick store for the day (=> candle-based APPROXIMATE profiles)."""
    toks = sorted(set(tokens))
    out = {t: [] for t in toks}
    buf = Path(day_dir) / "buffer.sqlite"
    if buf.exists():
        db = sqlite3.connect(f"file:{buf}?mode=ro", uri=True)
        try:
            for r in db.execute(f"SELECT token, exchange_ts, receive_ns, conn, seq, ltp, volume FROM ticks WHERE token IN "
                                f"({','.join('?' * len(toks))})", toks):
                out[r[0]].append(r[1:])
        finally:
            db.close()
        return out
    d = Path(day_dir) / "parquet" / "ticks"
    files = sorted(d.rglob("*.parquet")) if d.exists() else []
    if not files:
        return None
    import pyarrow.parquet as pq
    for f in files:
        t = pq.read_table(f, columns=["token", "exchange_ts_ns", "receive_ns", "conn", "seq", "ltp", "volume"],
                          filters=[("token", "in", toks)]).to_pydict()
        for i, tok in enumerate(t["token"]):
            ex = t["exchange_ts_ns"][i]
            out[tok].append((None if ex is None else ex // S, t["receive_ns"][i], t["conn"][i], t["seq"][i], t["ltp"][i],
                             t["volume"][i]))
    return out


def add_profile(dets: dict, near: dict, master, rows, day_dir: Path, cfg, day: date) -> dict:
    """Configs with `profile` (v17+): {underlying: Phase 5 detections + profile, rejection and depth detections}. Earlier
    configs: `dets` unchanged. near = structure.near_candles(...); rows = snapshot rows (Tier B depth snapshots)."""
    if "profile" not in cfg.values:
        return dets
    ticks = load_ticks(day_dir, [tok for tok, _ in near.values()])
    depth = defaultdict(list)
    for kind, key, _ts, payload in rows:
        if kind == "depth":
            depth[int(key)].append(json.loads(payload))
    out = dict(dets)
    for und, (tok, cs) in sorted(near.items()):
        ts = master.get(tok, (None,) * 7)[6]
        tick = int(Decimal(str(ts)) * 100) if ts not in (None, "") else 0
        tk = None if ticks is None else ticks.get(tok, [])
        extra = profile_detections(und, tok, cs["1m"], tk, tick, dets.get(und, []), day, cfg) + \
            depth_detections(und, tok, depth.get(tok, []), tk or [], tick, day, cfg)
        out[und] = sorted(dets.get(und, []) + extra, key=lambda x: (x.confirmed_ts, x.timeframe, x.type, x.id))
    return out
