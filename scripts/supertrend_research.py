"""Which conditions make a 5-minute Supertrend(10,3) flip worth trading? (research only; owner question 2026-11-13)

Event: every flip of Supertrend(10,3) on a stock's 5-minute cash candles (the Supertrend board's signal), candle start
<= 14:55. Trade it as is: enter at the flip candle's close, exit at the next opposite flip's close or the 15:10 close.
Rupees (APPROXIMATE, as scripts/trend_backtest.py): one at-the-money lot, option move = 0.5 x stock move, minus
--cost-inr per trade; no time decay, no IV change, today's lot size.

Conditions measured at the flip, from data up to its close only (decided before looking at any result):
  agree15   the 15-minute Supertrend(10,3) (closed 15-minute candles) points the same way
  nifty     NIFTY 50's 5-minute Supertrend points the same way
  vwap      the close is on the trade's side of the day's VWAP
  rvol      flip-candle volume / the same time slot's average over the previous 10 sessions (<1, 1-2, >=2)
  chop      5-minute flips in the 24 candles (2 hours) before this one (0, 1, 2+)
  hour      time of the flip candle
  dayside   the stock is already up (UP flip) / down (DOWN flip) on the day vs the previous close
  oi        near-month futures OI change over the 15 minutes to the flip, with price: UP + OI up = long build-up,
            UP + OI down = short covering, DOWN + OI up = short build-up, DOWN + OI down = long unwinding.
            Only since the November contract became near month (2026-10-28; intraday history exists only for
            live contracts, F-HIST-7), so its sample is short.
A condition is called useful only if it improves the average rupees per trade in BOTH halves of the period.

  python3 scripts/supertrend_research.py [--cost-inr 300]
Read-only Kite GETs; 5-minute cash candles reused from data/engine/backtest/trend_5m/, futures OI cached in st_oi/.
"""

import bisect
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.supertrend import supertrend                         # noqa: E402
from engine import paper as P                                       # noqa: E402
from engine.backfill import TokenBucket                             # noqa: E402
from engine.broker import KiteSession                               # noqa: E402
from engine.candles import IST                                      # noqa: E402
from engine.universe import Registry                                # noqa: E402

DELTA, OI_FROM, SPOT_CACHE_TAG = 0.5, date(2026, 10, 28), "2026-11-10_200"


def load_rows(f: Path) -> list:
    return [(datetime.fromisoformat(r[0]).astimezone(IST), *r[1:]) for r in json.loads(f.read_text())]


def fetch(session, bucket, token: int, start: date, end: date, oi: bool, f: Path) -> list:
    if not f.exists():
        bucket.take()
        f.write_text(json.dumps(session.historical(token, "5minute", f"{start} 09:15:00", f"{end} 15:30:00", oi)))
    return load_rows(f)


def to15(cs: list) -> list:
    """5-minute -> 15-minute candles aligned to 09:15: (start, o, h, l, c, v)."""
    out = {}
    for t, o, h, l, c, v, *_ in cs:
        s = t - timedelta(minutes=(t.hour * 60 + t.minute - 555) % 15)
        b = out.get(s)
        out[s] = (s, o, h, l, c, v) if b is None else (s, b[1], max(b[2], h), min(b[3], l), c, b[5] + v)
    return list(out.values())


def trades_for(sym: str, cs: list, nifty_dir: dict, oi: dict, lot: int, cost: float, is_index: bool = False) -> list:
    st = supertrend(cs)
    c15 = to15(cs)
    st15 = supertrend(c15)
    ends15 = [c[0] + timedelta(minutes=15) for c in c15]
    day_of = [c[0].date() for c in cs]
    # VWAP per session, previous close per session, same-slot volume history
    vwap, cum = [], {}
    prev_close, last_close = {}, None
    slot_hist = defaultdict(list)
    rvol = []
    for i, (t, o, h, l, c, v, *_) in enumerate(cs):
        d = t.date()
        if d not in cum:
            cum[d] = [0.0, 0.0]
            prev_close[d] = last_close
        pv = cum[d]
        pv[0] += (h + l + c) / 3 * v
        pv[1] += v
        vwap.append(pv[0] / pv[1] if pv[1] else None)
        hist = slot_hist[(t.hour, t.minute)]
        rvol.append(v / (sum(hist[-10:]) / 10) if len(hist) >= 10 and sum(hist[-10:]) else None)
        hist.append(v)
        last_close = c
    flips = [i for i in range(1, len(st)) if st[i] and st[i - 1] and st[i][0] != st[i - 1][0]]
    out = []
    for i in flips:
        t, c = cs[i][0], cs[i][4]
        if t.strftime("%H:%M") > "14:55":
            continue
        side = st[i][0]
        j, why = i, "TIME_15:10"
        for k in range(i + 1, len(cs)):
            if day_of[k] != day_of[i] or cs[k][0].strftime("%H:%M") > "15:05":
                break
            j = k
            if st[k][0] != side:
                why = "OPPOSITE_FLIP"
                break
        move = side * (cs[j][4] - c)
        k15 = bisect.bisect_right(ends15, t + timedelta(minutes=5)) - 1    # last 15-minute candle closed by the flip close
        d15 = st15[k15][0] if k15 >= 0 and st15[k15] else None
        nd = nifty_dir.get(t)
        pc = prev_close.get(t.date())
        recent = bisect.bisect_left(flips, i) - bisect.bisect_left(flips, i - 24)
        o = oi.get(t)
        o0 = oi.get(t - timedelta(minutes=15))
        oi_lbl = None
        if o is not None and o0:
            up_oi = o > o0
            oi_lbl = ("long build-up" if up_oi else "short covering") if side == 1 else \
                     ("short build-up" if up_oi else "long unwinding")
        out.append({
            "sym": sym, "day": str(t.date()), "t": t, "side": "UP" if side == 1 else "DOWN", "why": why,
            "move_pct": move / c * 100, "net": DELTA * move * lot - cost,
            "agree15": None if d15 is None else ("agree" if d15 == side else "conflict"),
            "nifty": None if nd is None or is_index else ("same" if nd == side else "against"),
            "vwap": None if vwap[i] is None or is_index else ("with" if side * (c - vwap[i]) > 0 else "against"),
            "rvol": None if rvol[i] is None else ("<1" if rvol[i] < 1 else "1-2" if rvol[i] < 2 else ">=2"),
            "chop": "0" if recent == 0 else "1" if recent == 1 else "2+",
            "hour": "09:15-10:00" if t.hour < 10 else "10-12" if t.hour < 12 else "12-14" if t.hour < 14 else "14-15",
            "dayside": None if not pc else ("already moving that way" if side * (c - pc) > 0 else "against the day"),
            "oi": oi_lbl,
        })
    return out


def stats(rows: list) -> tuple:
    if not rows:
        return 0, None, None, None
    n = len(rows)
    return n, sum(r["net"] > 0 for r in rows) / n * 100, sum(r["move_pct"] for r in rows) / n, sum(r["net"] for r in rows) / n


def fmt(s: tuple) -> str:
    n, w, m, a = s
    return f"{n} | —  | — | —" if not n else f"{n} | {w:.0f}% | {m:+.3f}% | ₹{a:+,.0f}"


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cost = float(args[args.index("--cost-inr") + 1]) if "--cost-inr" in args else 300.0
    cfg, today = P.load(), datetime.now(IST).date()
    reg = Registry(cfg)
    uni = reg.get_universe(today)
    root = cfg.root / "backtest"
    oi_cache = root / "st_oi"
    oi_cache.mkdir(parents=True, exist_ok=True)
    session, bucket = KiteSession.load(), TokenBucket(cfg.get("historical.rate_per_s"))
    end = today - timedelta(days=1)
    spot = {}
    for m in uni.members:
        f = root / "trend_5m" / f"{m.spot_token}_{SPOT_CACHE_TAG}.json"
        if m.spot_token and f.exists():
            extra = fetch(session, bucket, m.spot_token, date(2026, 11, 10), end, False, oi_cache / f"spot_{m.spot_token}_{end}.json")
            spot[m.underlying] = load_rows(f) + extra
    nifty_u = cfg.get("positioning.beta.index_underlying")
    ncs = spot[nifty_u]
    nifty_dir = {c[0]: s[0] for c, s in zip(ncs, supertrend(ncs)) if s}
    rows = []
    for u, cs in sorted(spot.items()):
        futs = sorted((c for c in reg.get_contracts(u, today) if c.instrument_type == "FUT" and c.expiry >= today), key=lambda c: c.expiry)
        if not futs:
            continue
        fut = futs[0]
        oi_rows = fetch(session, bucket, fut.token, OI_FROM, end, True, oi_cache / f"fut_{fut.token}_{OI_FROM}_{end}.json")
        oi = {r[0]: r[6] for r in oi_rows if len(r) > 6 and r[6]}
        rows += trades_for(u, cs, nifty_dir, oi, fut.lot_size, cost, u == nifty_u)
    days = sorted({r["day"] for r in rows})
    half = days[len(days) // 2]
    first, second = [r for r in rows if r["day"] < half], [r for r in rows if r["day"] >= half]
    oi_rows_all = [r for r in rows if r["oi"]]
    L = ["# Supertrend(10,3) 5-minute flips: which conditions help? (research, APPROXIMATE rupees)", "",
         f"{len(rows)} flips, {len({r['sym'] for r in rows})} underlyings, {len(days)} sessions ({days[0]} to {days[-1]}). "
         f"Halves: {days[0]}..{max(d for d in days if d < half)} | {half}..{days[-1]}. "
         f"₹ = one ATM lot at delta {DELTA}, minus ₹{cost:,.0f} per trade.", "",
         "trades | win rate | avg stock move | avg ₹ per trade (net)", "",
         "| group | all | first half | second half |", "|---|---|---|---|",
         f"| **every flip (baseline)** | {fmt(stats(rows))} | {fmt(stats(first))} | {fmt(stats(second))} |"]
    useful = []
    for key in ("agree15", "nifty", "vwap", "rvol", "chop", "hour", "dayside"):
        L.append(f"| *{key}* | | | |")
        for val in sorted({r[key] for r in rows if r[key] is not None}):
            g = lambda rs: [r for r in rs if r[key] == val]  # noqa: E731
            a, b, c = stats(g(rows)), stats(g(first)), stats(g(second))
            L.append(f"| {key} = {val} | {fmt(a)} | {fmt(b)} | {fmt(c)} |")
            if b[0] and c[0] and b[3] > stats(first)[3] and c[3] > stats(second)[3]:
                useful.append(f"{key} = {val}")
    oi_days = sorted({r["day"] for r in oi_rows_all})
    L += ["", f"## OI (only {len(oi_days)} sessions, {oi_days[0] if oi_days else '—'} to {oi_days[-1] if oi_days else '—'}: too short to trust)", "",
          "| group | all |", "|---|---|", f"| every flip in these sessions | {fmt(stats([r for r in rows if r['day'] in set(oi_days)]))} |"]
    for val in sorted({r["oi"] for r in oi_rows_all}):
        L.append(f"| oi = {val} | {fmt(stats([r for r in oi_rows_all if r['oi'] == val]))} |")
    combo = [r for r in rows if all(r[k] == v for k, v in (x.split(" = ") for x in useful))] if useful else []
    L += ["", "## Conditions that helped in BOTH halves", "", ", ".join(useful) or "none", ""]
    if useful:
        L += [f"All of them together: all {fmt(stats(combo))} | first half {fmt(stats([r for r in combo if r['day'] < half]))} | "
              f"second half {fmt(stats([r for r in combo if r['day'] >= half]))}", ""]
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
