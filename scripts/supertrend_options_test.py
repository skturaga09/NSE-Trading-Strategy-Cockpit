"""Supertrend(10,3) 5-minute flips traded the owner's way, on REAL option prices (research only; owner rules 2026-11-13).

Owner's rules (answered 2026-11-13):
- Buy 1 strike in the money: UP flip -> CE one strike below the at-the-money strike, DOWN flip -> PE one strike above.
  At the money = the listed strike nearest the stock price at the flip close; strikes from the exchange master.
  Expiry: the current month (nearest listed expiry). Always 1 lot.
- Exit: the Supertrend line is the stop, plus the opposite flip. Tested two ways:
    LINE  sell in the first minute the stock trades through the line (line of the last closed 5-minute candle)
    CLOSE sell when a 5-minute candle closes through it (= the opposite flip)
- Holding: the owner said "depends" without a rule, so both are shown:
    INTRADAY  also sold at 15:15
    OVERNIGHT held across days until the stop; still open at the end = valued at the last price (marked OPEN)
Prices: entry = the option's first traded 1-minute candle (its open) at or after the flip close; an exit = the option's
first traded minute at or after the exit moment. No option trade within 5 minutes of a moment = that trade is skipped
(NO FILL). ASSUMED 1 % half-spread per side; charges from the verified schedule (engine.costs.round_trip).
Window: only contracts still listed have intraday history (F-HIST-7), so this covers the November series as near month
(2026-10-28 onward). NIFTY is left out: its weekly options of that period have expired (no history).

  python3 scripts/supertrend_options_test.py
Read-only Kite GETs; candles cached under data/engine/backtest/st_opt/.
"""

import bisect
import json
import sys
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard.supertrend import supertrend                         # noqa: E402
from engine import paper as P                                       # noqa: E402
from engine.backfill import TokenBucket                             # noqa: E402
from engine.broker import KiteSession                               # noqa: E402
from engine.candles import IST                                      # noqa: E402
from engine.costs import round_trip                                 # noqa: E402
from engine.universe import Registry                                # noqa: E402
from supertrend_research import SPOT_CACHE_TAG, fetch, load_rows, to15    # noqa: E402

START, HALF, CUT = date(2026, 10, 28), 0.01, dtime(15, 15)
LAST_ENTRY = "14:00"                    # owner 2026-11-13: no new entry on a flip closing at/after 14:00
PREMIUM_STOP = 0.75                     # drawdown test 2026-11-13: also sell if the option trades 25 % below entry
LIMITS = {"max_open": 4, "max_per_day": 5, "max_premium": 50_000, "day_stop": -30_000}   # owner: the engine limits (D-71)
NO_FILL_MIN = 5


def minute_bars(session, bucket, token: int, start: date, end: date, cache: Path) -> list:
    """[(start datetime, o, h, l, c)] 1-minute candles."""
    f = cache / f"m_{token}_{start}_{end}.json"
    if not f.exists():
        bucket.take()
        f.write_text(json.dumps(session.historical(token, "minute", f"{start} 09:15:00", f"{end} 15:30:00", False)))
    return [(datetime.fromisoformat(r[0]).astimezone(IST), *r[1:5]) for r in json.loads(f.read_text())]


def fill(bars: list, starts: list, at: datetime, price_ix: int = 1):
    """The option's first traded minute starting at or after `at` (within NO_FILL_MIN): (time, price) or None."""
    i = bisect.bisect_left(starts, at)
    if i < len(bars) and bars[i][0] - at <= timedelta(minutes=NO_FILL_MIN):
        return bars[i][0], bars[i][price_ix]
    return None


def pick_itm(chain: list, kind: str, spot: float, day: date):
    """1 strike ITM of the nearest listed expiry on/after `day`: chain rows (expiry, strike, kind, token, lot)."""
    exps = sorted({e for e, _, k, _, _ in chain if k == kind and e >= day})
    if not exps:
        return None
    rows = sorted((c for c in chain if c[0] == exps[0] and c[2] == kind), key=lambda c: c[1])
    strikes = [c[1] for c in rows]
    atm = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - spot), strikes[i]))
    j = atm - 1 if kind == "CE" else atm + 1
    return rows[j] if 0 <= j < len(rows) else None


def exits(side: int, entry_t: datetime, st: list, cs5: list, m1: list, overnight: bool) -> dict:
    """Exit moments for one trade: {'LINE': (t, why), 'CLOSE': (t, why)}; t None = still open at the data's end.
    st/cs5: 5-minute Supertrend + candles; m1: the stock's 1-minute candles (start, o, h, l, c)."""
    ends5 = [c[0] + timedelta(minutes=5) for c in cs5]
    out = {}
    # CLOSE: the first 5-minute candle after entry whose trend is the other way; exit at its close
    k = bisect.bisect_left(ends5, entry_t + timedelta(seconds=1))
    t_close = None
    while k < len(cs5):
        if not overnight and ends5[k] > datetime.combine(entry_t.date(), CUT, IST):
            break
        if st[k] and st[k][0] != side:
            t_close = (ends5[k], "OPPOSITE_FLIP")
            break
        k += 1
    if t_close is None and not overnight:
        t_close = (datetime.combine(entry_t.date(), CUT, IST), "TIME_15:15")
    out["CLOSE"] = t_close or (None, "OPEN")
    # LINE: the first minute after entry that trades through the line of the last closed 5-minute candle
    i = bisect.bisect_left([m[0] for m in m1], entry_t)
    t_line = None
    for m in m1[i:]:
        if not overnight and m[0] >= datetime.combine(entry_t.date(), CUT, IST):
            t_line = (datetime.combine(entry_t.date(), CUT, IST), "TIME_15:15")
            break
        j = bisect.bisect_right(ends5, m[0]) - 1          # last 5-minute candle closed by this minute's start
        if j < 0 or st[j] is None:
            continue
        line = st[j][1]
        if (side == 1 and m[3] <= line) or (side == -1 and m[2] >= line):
            t_line = (m[0], "LINE_STOP")
            break
    if t_line is None and not overnight:
        t_line = (datetime.combine(entry_t.date(), CUT, IST), "TIME_15:15")
    out["LINE"] = t_line or (None, "OPEN")
    return out


def _trend_at(states: list, ends: list, t: datetime):
    j = bisect.bisect_right(ends, t) - 1
    return states[j][0] if j >= 0 and states[j] else None


def exit_depends(side: int, entry_t: datetime, st: list, ends5: list, st15: list, ends15: list, m1: list) -> tuple:
    """Owner's rule: the line stop at any time; at each 15:15 hold overnight only if the 5-minute AND 15-minute trends
    both still point `side`, else sell at 15:15; next day the line stop sells the moment it flips. -> (time | None, why)."""
    check = datetime.combine(entry_t.date(), CUT, IST)
    agree = lambda t: _trend_at(st, ends5, t) == side and _trend_at(st15, ends15, t) == side   # noqa: E731
    for m in m1[bisect.bisect_left([x[0] for x in m1], entry_t):]:
        while m[0] >= check:                    # a 15:15 decision passed (also across nights and weekends)
            if not agree(check):
                return check, "15:15 (5m/15m not both agreeing)"
            check = datetime.combine(check.date() + timedelta(days=1), CUT, IST)
        j = bisect.bisect_right(ends5, m[0]) - 1
        if j >= 0 and st[j] and ((side == 1 and m[3] <= st[j][1]) or (side == -1 and m[2] >= st[j][1])):
            return m[0], "LINE_STOP"
    if m1 and check.date() <= m1[-1][0].date() and not agree(check):   # the data's last 15:15
        return check, "15:15 (5m/15m not both agreeing)"
    return None, "OPEN"


def account(cands: list, exit_key: str, capital: float | None = None, rules: dict | None = None,
            log: list | None = None) -> tuple:
    """Owner's selection: flips in time order, same candle -> strongest volume first; limits LIMITS. -> (taken, skipped).
    `capital`: also a cash account: a trade needs its premium <= capital + closed P&L - premium tied up in open trades.
    `rules` overrides LIMITS; "cooldown": that many losses in a row today -> no new trade until tomorrow;
    "max_premium_pct" / "day_stop_pct": the premium cap / daily loss stop as a share of the balance (needs `capital`;
    the balance = capital + closed P&L, so profits raise them and losses lower them). `log` gets (candidate, decision).
    "risk_budget": (day_pct, risk) = the live view's day loss budget (supertrend_trades.view): day_pct of the day's opening
    balance + today's closed P&L - risk x the premium of open trades; a new lot needs risk x its premium within it."""
    R = {**LIMITS, "cooldown": None, "max_premium_pct": None, "day_stop_pct": None, "risk_budget": None, **(rules or {})}
    taken, skipped = [], defaultdict(int)
    for c in sorted(cands, key=lambda c: (c["t"], -(c["rvol"] or 0), c["sym"])):
        x = c[exit_key]
        if x is None:
            skipped["no option trade at the exit"] += 1
            if log is not None:
                log.append((c, "no option trade at the exit"))
            continue
        t, day = c["t"], c["t"].date()
        open_ = [o for o in taken if o["out_t"] is None or o["out_t"] > t]
        realized = sum(o["net"] for o in taken if o["out_t"] and o["out_t"].date() == day and o["out_t"] <= t)
        cash = None if capital is None else \
            capital + sum(o["net"] for o in taken if o["out_t"] and o["out_t"] <= t) - sum(o["premium"] for o in open_)
        closed_today = [o["net"] for o in sorted(taken, key=lambda o: o["out_t"] or t)
                        if o["out_t"] and o["out_t"].date() == day and o["out_t"] <= t]
        n = R["cooldown"]
        closed_before = lambda u: sum(o["net"] for o in taken if o["out_t"] and o["out_t"] <= u)   # noqa: E731
        cap_prem = R["max_premium"] if R["max_premium_pct"] is None else R["max_premium_pct"] * (capital + closed_before(t))
        day_stop = R["day_stop"] if R["day_stop_pct"] is None else \
            -R["day_stop_pct"] * (capital + closed_before(datetime.combine(day, dtime(9, 0), IST)))
        if R["risk_budget"]:
            pct, risk = R["risk_budget"]
            budget = pct * (capital + closed_before(datetime.combine(day, dtime(9, 0), IST))) + realized \
                - risk * sum(o["premium"] for o in open_)
        why = ((f"premium above ₹{cap_prem:,.0f} for 1 lot" if R["max_premium_pct"] is None else
                f"premium above {R['max_premium_pct']:.0%} of the balance") if c["premium"] > cap_prem else
               "not enough cash" if cash is not None and c["premium"] > cash else
               "already holding this stock" if any(o["sym"] == c["sym"] for o in open_) else
               f"{R['max_open']} positions already open" if len(open_) >= R["max_open"] else
               f"{R['max_per_day']} trades already today" if sum(o["t"].date() == day for o in taken) >= R["max_per_day"] else
               f"day loss budget ({R['risk_budget'][0]:.0%} of the balance) used up" if R["risk_budget"] and
               R["risk_budget"][1] * c["premium"] > budget else
               (f"daily loss stop (−₹{-day_stop:,.0f}) hit" if R["day_stop_pct"] is None else
                f"daily loss stop ({R['day_stop_pct']:.0%} of the balance) hit") if realized <= day_stop else
               f"{n} losses in a row today" if n and len(closed_today) >= n and all(x <= 0 for x in closed_today[-n:]) else None)
        if log is not None:
            log.append((c, why or "TAKEN"))
        if why:
            skipped[why] += 1
            continue
        taken.append({**c, **x})
    return taken, skipped


def compare_row(taken: list, capital: float) -> str:
    if not taken:
        return "0 | — | — | — | — | —"
    cum = peak = dd = 0.0
    low = capital
    for o in sorted(taken, key=lambda o: o["out_t"] or datetime.max.replace(tzinfo=IST)):
        cum += o["net"]
        peak, dd, low = max(peak, cum), max(dd, peak - cum), min(low, capital + cum)
    net = [o["net"] for o in taken]
    return (f"{len(taken)} | ₹{sum(net):+,.0f} | ₹{-dd:,.0f} | ₹{low:,.0f} | ₹{sum(net) - max(net):+,.0f} | "
            f"{sum(x > 0 for x in net) / len(net) * 100:.0f}%")


def account_report(name: str, taken: list, skipped: dict, n_cands: int) -> list:
    L = ["", f"## {name}", ""]
    if not taken:
        return L + ["No trade taken."]
    net = [o["net"] for o in taken]
    wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
    cum = peak = dd = 0.0
    for o in sorted(taken, key=lambda o: o["out_t"] or datetime.max.replace(tzinfo=IST)):
        cum += o["net"]
        peak, dd = max(peak, cum), max(dd, peak - cum)
    by_day = defaultdict(float)
    for o in taken:
        by_day[str((o["out_t"] or o["t"]).date())] += o["net"]
    L += [f"- Candidates (5m flip before {LAST_ENTRY} with 15m agreeing): {n_cands}; **taken: {len(taken)}** "
          f"({len(taken) / max(len({o['t'].date() for o in taken}), 1):.1f} per trading day with a trade)",
          f"- **Total net: ₹{sum(net):+,.0f}** · win rate {len(wins) / len(net) * 100:.0f}% · avg win ₹{sum(wins) / max(len(wins), 1):+,.0f} · "
          f"avg loss ₹{sum(losses) / max(len(losses), 1):+,.0f} · worst drawdown ₹{-dd:,.0f}",
          f"- Held overnight: {sum(o['nights'] > 0 for o in taken)} trades · still OPEN at the end (valued at the last price): "
          f"{sum(o['out_t'] is None for o in taken)}",
          "- Net by exit day: " + " · ".join(f"{d[5:]} ₹{v:+,.0f}" for d, v in sorted(by_day.items())),
          "- Skipped: " + (" · ".join(f"{k} {v}" for k, v in sorted(skipped.items())) or "none"), "",
          "| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |", "|---|---|---|---|---|---|---|---|"]
    for o in sorted(taken, key=lambda o: o["t"]):
        out = o["out_t"].strftime("%m-%d %H:%M") if o["out_t"] else "open"
        L.append(f"| {o['t']:%m-%d %H:%M} | {o['sym']} | {o['contract']} | ₹{o['premium']:,.0f} | {out} | {o['why']} | "
                 f"{o['nights']} | **₹{o['net']:+,.0f}** |")
    return L


def main(argv=None) -> int:
    cfg, today = P.load(), datetime.now(IST).date()
    end = today - timedelta(days=1)
    reg = Registry(cfg)
    uni = reg.get_universe(today)
    root = cfg.root / "backtest"
    cache = root / "st_opt"
    cache.mkdir(parents=True, exist_ok=True)
    session, bucket = KiteSession.load(), TokenBucket(cfg.get("historical.rate_per_s"))
    nifty_u = cfg.get("positioning.beta.index_underlying")
    results = {(e, h): [] for e in ("LINE", "CLOSE") for h in ("INTRADAY", "OVERNIGHT")}
    skipped = defaultdict(int)
    opt_cache, cands = {}, []
    for m in sorted(uni.members, key=lambda m: m.underlying):
        f = root / "trend_5m" / f"{m.spot_token}_{SPOT_CACHE_TAG}.json"
        if m.underlying == nifty_u or not m.spot_token or not f.exists():
            continue
        cs5 = load_rows(f) + fetch(session, bucket, m.spot_token, date(2026, 11, 10), end, False,
                                   root / "st_oi" / f"spot_{m.spot_token}_{end}.json")
        cs5 = [c[:6] for c in cs5]
        st = supertrend(cs5)
        ends5 = [c[0] + timedelta(minutes=5) for c in cs5]
        c15 = to15(cs5)
        st15, ends15 = supertrend(c15), [c[0] + timedelta(minutes=15) for c in c15]
        slot, rvol = defaultdict(list), []
        for c in cs5:                               # flip-candle volume vs the same slot's last 10 sessions
            h = slot[(c[0].hour, c[0].minute)]
            rvol.append(c[5] / (sum(h[-10:]) / 10) if len(h) >= 10 and sum(h[-10:]) else None)
            h.append(c[5])
        m1 = minute_bars(session, bucket, m.spot_token, START, end, cache)
        chain = [(c.expiry, float(c.strike), c.instrument_type, c.token, c.lot_size)
                 for c in reg.get_contracts(m.underlying, today) if c.instrument_type in ("CE", "PE")]
        for k in range(1, len(cs5)):
            t0 = cs5[k][0]
            if t0.date() < START or t0.weekday() >= 5 or not (st[k] and st[k - 1]) or st[k][0] == st[k - 1][0]:
                continue
            flip_close = t0 + timedelta(minutes=5)
            if flip_close.time() > dtime(15, 10):
                skipped["flip after 15:10"] += 1
                continue
            side = st[k][0]
            kind = "CE" if side == 1 else "PE"
            c = pick_itm(chain, kind, cs5[k][4], t0.date())
            if c is None:
                skipped["no ITM strike listed"] += 1
                continue
            exp, strike, _, tok, lot = c
            if tok not in opt_cache:
                ob = minute_bars(session, bucket, tok, START, end, cache)
                opt_cache[tok] = (ob, [b[0] for b in ob])
            ob, starts = opt_cache[tok]
            e = fill(ob, starts, flip_close)
            if e is None:
                skipped["NO FILL at entry (option not traded within 5 min)"] += 1
                continue
            if flip_close.strftime("%H:%M") < LAST_ENTRY and _trend_at(st15, ends15, flip_close) == side:
                cand = {"sym": m.underlying, "t": flip_close, "rvol": rvol[k], "lot": lot, "premium": e[1] * (1 + HALF) * lot,
                        "contract": f"{m.underlying} {strike:g} {kind} {exp}"}
                dep = exit_depends(side, flip_close, st, ends5, st15, ends15, m1)
                ps = next(((b[0], min(b[1], PREMIUM_STOP * e[1])) for b in ob[bisect.bisect_right(starts, e[0]):]
                           if b[3] <= PREMIUM_STOP * e[1]), None)      # first minute the option trades 25 % below entry
                ps_exit = (ps[0], "PREMIUM_STOP_25%") if ps and (dep[0] is None or ps[0] < dep[0]) else dep
                for key, (xt, why) in (("depends", dep), ("intraday", exits(side, flip_close, st, cs5, m1, False)["LINE"]),
                                       ("depends_ps", ps_exit)):
                    x = (ps[0], ps[1]) if why == "PREMIUM_STOP_25%" else (ob[-1][0], ob[-1][4]) if xt is None and ob else \
                        fill(ob, starts, xt) or fill(ob, starts, xt - timedelta(minutes=NO_FILL_MIN), 4) if xt else None
                    if x is None:
                        cand[key] = None
                        continue
                    entry, exit_ = e[1] * (1 + HALF), x[1] * (1 - HALF)
                    costs = round_trip(cfg, "OPT", "BUY", entry, exit_, lot, t0.date()).total_inr
                    cand[key] = {"out_t": xt, "why": why, "net": (exit_ - entry) * lot - costs,
                                 "nights": ((xt or ob[-1][0]).date() - flip_close.date()).days}   # calendar nights (a weekend counts 3)
                cands.append(cand)
            for hold in ("INTRADAY", "OVERNIGHT"):
                for ex, (xt, why) in exits(side, flip_close, st, cs5, m1, hold == "OVERNIGHT").items():
                    if xt is None:
                        x = (ob[-1][0], ob[-1][4]) if ob else None
                    else:
                        x = fill(ob, starts, xt) or (fill(ob, starts, xt - timedelta(minutes=NO_FILL_MIN), 4))
                    if x is None:
                        skipped[f"{ex}/{hold}: NO FILL at exit"] += 1
                        continue
                    entry, exit_ = e[1] * (1 + HALF), x[1] * (1 - HALF)
                    costs = round_trip(cfg, "OPT", "BUY", entry, exit_, lot, t0.date()).total_inr
                    results[(ex, hold)].append({
                        "sym": m.underlying, "day": str(t0.date()), "time": flip_close.strftime("%H:%M"),
                        "side": "UP" if side == 1 else "DOWN", "contract": f"{m.underlying} {strike:g} {kind} {exp}",
                        "lot": lot, "entry": entry, "exit": exit_, "why": why, "out": x[0], "capital": entry * lot,
                        "gross": (exit_ - entry) * lot, "costs": costs, "net": (exit_ - entry) * lot - costs,
                        "hold_min": (x[0] - e[0]).total_seconds() / 60})
    out = [report(results, skipped)]
    for name, key, cap in (("YOUR ACCOUNT, your rules: hold overnight only when 5m and 15m agree at 15:15", "depends", None),
                           ("Same picks and limits, but always out by 15:15 (for comparison)", "intraday", None),
                           ("₹50,000 CAPITAL, your rules (cash-limited: profits reused, losses shrink what you can buy)", "depends", 50_000),
                           ("₹50,000 CAPITAL, always out by 15:15 (for comparison)", "intraday", 50_000)):
        out += account_report(name, *account(cands, key, cap), len(cands))
    # drawdown rules for ₹50,000, fixed before looking (owner request 2026-11-13); one table, then each in full
    variants = (("A. your rules (baseline)", "depends", {}),
                ("B. + premium stop: sell if the option trades 25 % below entry", "depends_ps", {}),
                ("C. + daily loss stop ₹5,000 (10 % of capital)", "depends", {"day_stop": -5_000}),
                ("D. + max ₹15,000 premium per trade (30 % of capital)", "depends", {"max_premium": 15_000}),
                ("E. + after 2 losses in a row, no new trade until tomorrow", "depends", {"cooldown": 2}),
                ("F. all of B + C + D + E", "depends_ps", {"day_stop": -5_000, "max_premium": 15_000, "cooldown": 2}))
    out += ["", "## ₹50,000: drawdown rules compared (each fixed before looking; same 11 days)", "",
            "| version | trades | total net ₹ | worst drawdown ₹ | lowest balance ₹ | without the best trade ₹ | win rate |",
            "|---|---|---|---|---|---|---|"]
    detail = []
    for name, key, rules in variants:
        taken, sk = account(cands, key, 50_000, rules)
        out.append("| " + name + " | " + compare_row(taken, 50_000) + " |")
        detail += account_report("₹50,000 · " + name, taken, sk, len(cands))
    out += detail
    print("\n".join(out))
    return 0


def summary(rows: list) -> str:
    if not rows:
        return "0 | — | — | — | — | — | —"
    n, net = len(rows), [r["net"] for r in rows]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]
    return (f"{n} | {len(wins) / n * 100:.0f}% | ₹{sum(net) / n:+,.0f} | ₹{sum(wins) / max(len(wins), 1):+,.0f} / "
            f"₹{sum(losses) / max(len(losses), 1):+,.0f} | ₹{sum(net):+,.0f} | ₹{sum(r['capital'] for r in rows) / n:,.0f} | "
            f"{sorted(r['hold_min'] for r in rows)[n // 2]:.0f} min")


def report(results: dict, skipped: dict) -> str:
    any_rows = [r for v in results.values() for r in v]
    days = sorted({r["day"] for r in any_rows})
    L = ["# Supertrend(10,3) 5-minute flips on REAL option prices: 1 strike ITM, 1 lot (research)", "",
         f"Sessions {days[0] if days else '—'} to {days[-1] if days else '—'} ({len(days)}), "
         f"{len({r['sym'] for r in any_rows})} stocks. ASSUMED 1 % half-spread per side + verified charges.", "",
         "| exit | holding | trades | win rate | avg net ₹ / trade | avg win / avg loss | total net ₹ | avg premium paid | median hold |",
         "|---|---|---|---|---|---|---|---|---|"]
    for (ex, hold), rows in results.items():
        L.append(f"| {ex} | {hold} | {summary(rows)} |")
    L += ["", "## How solid is it?", "", "| exit | holding | still OPEN at the end (valued at last price) | avg net ₹ without the best day | avg net ₹ if the buy/sell gap is 2 % per side, not 1 % |",
          "|---|---|---|---|---|"]
    for (ex, hold), rows in results.items():
        if not rows:
            continue
        by_day = defaultdict(float)
        for r in rows:
            by_day[r["day"]] += r["net"]
        best = max(by_day, key=by_day.get)
        rest = [r for r in rows if r["day"] != best]
        wider = sum(r["net"] - 0.01 * (r["entry"] / 1.01 + r["exit"] / 0.99) * r["lot"] for r in rows) / len(rows)
        L.append(f"| {ex} | {hold} | {sum(r['why'] == 'OPEN' for r in rows)} | ₹{sum(r['net'] for r in rest) / max(len(rest), 1):+,.0f} "
                 f"(best day {best}: ₹{by_day[best]:+,.0f}) | ₹{wider:+,.0f} |")
    L += ["", "## Split (LINE stop, INTRADAY)", "", "| group | trades | win rate | avg net ₹ | avg win / avg loss | total | premium | hold |",
          "|---|---|---|---|---|---|---|---|"]
    base = results[("LINE", "INTRADAY")]
    for name, f in (("UP flips (CE)", lambda r: r["side"] == "UP"), ("DOWN flips (PE)", lambda r: r["side"] == "DOWN"),
                    ("flip before 14:00", lambda r: r["time"] < "14:00"), ("flip 14:00 or later", lambda r: r["time"] >= "14:00")):
        L.append(f"| {name} | {summary([r for r in base if f(r)])} |")
    L += ["", "## Per day (LINE stop, INTRADAY)", "", "| day | trades | win rate | avg net ₹ | avg win / avg loss | total | premium | hold |",
          "|---|---|---|---|---|---|---|---|"]
    for d in days:
        L.append(f"| {d} | {summary([r for r in base if r['day'] == d])} |")
    L += ["", "## Not traded", ""] + [f"- {k}: {v}" for k, v in sorted(skipped.items())]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
