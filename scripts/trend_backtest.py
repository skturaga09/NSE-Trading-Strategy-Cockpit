"""With-the-trend option buying: a simple opening-range breakout in the market's direction (research only, D-73).

Rules, fixed before any result was seen (no tuning: change them only with a new decision and a fresh out-of-sample run):
- Opening range (OR) = the first 15 minutes, 09:15-09:30 (three 5-minute candles of the stock's cash price).
- Buy a CALL when a 5-minute candle ending 09:35-13:30 closes above the OR high, above the stock's VWAP for the day, and
  NIFTY 50 is above its day open at that candle. Buy a PUT on the mirror image. First signal per stock per day only.
- Skip when the OR is wider than 2 % of the price (stop too far for an option buyer).
- Stop = the other side of the OR (the stock closes or trades through it); target = 2x the risk; else exit at 15:10.
  A candle touching both stop and target counts as the stop (conservative).
- Account: your limits (risk.max_open_positions open at once, risk.max_daily_trades per day, risk.max_daily_loss_inr).

Rupees:
- Section A (APPROXIMATE, long history): one at-the-money lot, option move = 0.5 x stock move (delta 0.5), minus
  --cost-inr per trade (charges + spread). Ignores time decay and volatility changes; lot = today's lot size.
- Section B (real prices, recent days only): the same signals priced on Kite's real 1-minute candles of the nearest
  at-the-money option with >= contracts.min_dte_days to expiry (only contracts still listed have history, F-HIST-7),
  ASSUMED 1 % half-spread per side, verified charges (engine.costs.round_trip).

  python3 scripts/trend_backtest.py [--days 200] [--real-from 2026-10-28] [--cost-inr 300]
Read-only Kite GETs (F-HIST-1/5, F-RATE-2); candles cached under data/engine/backtest/trend_5m/.
"""

import json
import sys
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import paper as P                                       # noqa: E402
from engine.backfill import TokenBucket                             # noqa: E402
from engine.broker import KiteSession                               # noqa: E402
from engine.candles import IST                                      # noqa: E402
from engine.costs import round_trip                                 # noqa: E402
from engine.universe import Registry                                # noqa: E402
from trader_test import rs, summary_rows                            # noqa: E402

OR_END, LAST_SIGNAL, EXIT_AT = dtime(9, 30), dtime(13, 30), dtime(15, 10)
MAX_OR_PCT, RR, DELTA = 2.0, 2.0, 0.5


# ---------------------------------------------------------------- data
def candles(session, bucket, token: int, days: int, today: date, cache: Path) -> list:
    """[(start datetime IST, o, h, l, c, v)] 5-minute candles for the last `days` calendar days before today."""
    f = cache / f"{token}_{today}_{days}.json"
    if not f.exists():
        rows, end = [], today - timedelta(days=1)
        while end > today - timedelta(days=days):
            start = max(today - timedelta(days=days), end - timedelta(days=99))   # F-HIST-5: 5minute <= 100 days
            bucket.take()
            rows = session.historical(token, "5minute", f"{start} 09:15:00", f"{end} 15:30:00", False) + rows
            end = start - timedelta(days=1)
        f.write_text(json.dumps(rows))
    return [(datetime.fromisoformat(r[0]).astimezone(IST), *r[1:6]) for r in json.loads(f.read_text())]


def by_day(cs: list) -> dict:
    out = defaultdict(list)
    for c in cs:
        out[c[0].date()].append(c)
    return out


# ---------------------------------------------------------------- the rule (pure)
def signal(day_cs: list, nifty_day: list) -> dict | None:
    """First with-the-trend OR breakout of one stock-day -> trade dict, or None."""
    orc = [c for c in day_cs if c[0].time() < OR_END]
    if len(orc) < 3:
        return None
    hi, lo = max(c[2] for c in orc), min(c[3] for c in orc)
    if (hi - lo) / lo * 100 > MAX_OR_PCT:
        return None
    n_open = nifty_day[0][1] if nifty_day else None
    nifty_at = {c[0]: c[4] for c in nifty_day}
    pv = vol = 0.0
    for c in day_cs:
        pv, vol = pv + (c[2] + c[3] + c[4]) / 3 * c[5], vol + c[5]
        end = (c[0] + timedelta(minutes=5)).time()
        if c[0].time() < OR_END or end > LAST_SIGNAL or vol <= 0 or n_open is None or c[0] not in nifty_at:
            continue
        vwap, n = pv / vol, nifty_at[c[0]]
        side = 1 if c[4] > hi and c[4] > vwap and n > n_open else -1 if c[4] < lo and c[4] < vwap and n < n_open else 0
        if side:
            stop = lo if side > 0 else hi
            return {"t": c[0] + timedelta(minutes=5), "side": side, "entry": c[4], "stop": stop,
                    "target": c[4] + side * RR * abs(c[4] - stop)}
    return None


def exit_of(sig: dict, day_cs: list) -> tuple:
    """-> (exit time, exit stock price, reason) walking the 5-minute candles after the signal."""
    s = sig["side"]
    last = None
    for c in day_cs:
        start, end = c[0], c[0] + timedelta(minutes=5)
        if start < sig["t"]:
            continue
        if (c[3] <= sig["stop"]) if s > 0 else (c[2] >= sig["stop"]):
            px = c[1] if ((c[1] <= sig["stop"]) if s > 0 else (c[1] >= sig["stop"])) else sig["stop"]   # gap through it
            return end, px, "STOP"
        if (c[2] >= sig["target"]) if s > 0 else (c[3] <= sig["target"]):
            return end, sig["target"], "TARGET"
        last = (end, c[4])
        if end.time() >= EXIT_AT:
            return end, c[4], "TIME_15:10"
    return (last[0], last[1], "LAST_CANDLE") if last else (sig["t"], sig["entry"], "NO_CANDLE_AFTER")


def account(trades: list, cfg) -> tuple[list, int]:
    """Time-ordered: at most risk.max_open_positions open, risk.max_daily_trades a day, stop at -risk.max_daily_loss_inr."""
    taken, skipped = [], 0
    for day, ts in sorted(group(trades, "day").items()):
        opened = []
        for t in sorted(ts, key=lambda t: (t["t"], t["symbol"])):
            open_now = [o for o in opened if o["exit_t"] > t["t"]]
            closed = sum(o["net"] for o in opened if o["exit_t"] <= t["t"])
            if len(opened) >= cfg.get("risk.max_daily_trades") or len(open_now) >= cfg.get("risk.max_open_positions") \
                    or closed <= -cfg.get("risk.max_daily_loss_inr"):
                skipped += 1
                continue
            opened.append(t)
        taken += opened
    return taken, skipped


def group(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


# ---------------------------------------------------------------- run
def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    opt = lambda name, d: (args[args.index(name) + 1] if name in args else d)  # noqa: E731
    days, cost, real_from = int(opt("--days", "200")), float(opt("--cost-inr", "300")), date.fromisoformat(opt("--real-from", "2026-10-28"))
    cfg, today = P.load(), datetime.now(IST).date()
    reg = Registry(cfg)
    uni = reg.get_universe(today)
    cache = cfg.root / "backtest" / "trend_5m"
    cache.mkdir(parents=True, exist_ok=True)
    session, bucket = KiteSession.load(), TokenBucket(cfg.get("historical.rate_per_s"))
    idx = next(m for m in uni.members if m.underlying == cfg.get("positioning.beta.index_underlying"))
    nifty = by_day(candles(session, bucket, idx.spot_token, days, today, cache))
    trades = []
    for m in sorted(uni.members, key=lambda m: m.underlying):
        cs = reg.get_contracts(m.underlying, today)
        futs = sorted((c for c in cs if c.instrument_type == "FUT" and c.expiry >= today), key=lambda c: c.expiry)
        if not futs or not m.spot_token:
            continue
        lot = futs[0].lot_size
        for d, dc in by_day(candles(session, bucket, m.spot_token, days, today, cache)).items():
            sig = signal(dc, nifty.get(d, []))
            if sig is None:
                continue
            et, epx, why = exit_of(sig, dc)
            move = sig["side"] * (epx - sig["entry"])
            trades.append({"day": str(d), "time": sig["t"].strftime("%H:%M"), "t": sig["t"], "exit_t": et, "exit_time": et.strftime("%H:%M"),
                           "symbol": m.underlying, "dir": "LONG" if sig["side"] > 0 else "SHORT", "lot": lot,
                           "entry_px": sig["entry"], "exit_px": epx, "exit_reason": why, "stock_move_pct": move / sig["entry"] * 100,
                           "net": DELTA * move * lot - cost, "gross": DELTA * move * lot, "costs": cost})
    taken, skipped = account(trades, cfg)
    sessions = sorted({t["day"] for t in trades})
    half = sessions[len(sessions) // 2] if sessions else ""
    L = ["# With-the-trend option buying: opening-range breakout in NIFTY's direction (research, D-73)", "",
         f"Sessions: {len(sessions)} ({sessions[0] if sessions else '—'} to {sessions[-1] if sessions else '—'}), "
         f"{len(uni.members)} underlyings. Rules fixed before testing (see the script's docstring).", "",
         f"## A. APPROXIMATE (delta {DELTA}, {rs(cost)} cost per trade): every signal", ""] + summary_rows(trades)
    L += ["", f"## A2. Your account (max {cfg.get('risk.max_open_positions')} open, {cfg.get('risk.max_daily_trades')}/day, "
          f"stop at -{rs(cfg.get('risk.max_daily_loss_inr'))}); {skipped} signals skipped by the limits", ""] + summary_rows(taken)
    L += ["", "### Same rules, first half vs second half of the sessions (stability check)", "",
          "| period | trades | net | win rate |", "|---|---|---|---|"]
    for name, rows in (("first half", [t for t in taken if t["day"] < half]), ("second half", [t for t in taken if t["day"] >= half])):
        if rows:
            L.append(f"| {name} | {len(rows)} | {rs(sum(r['net'] for r in rows))} | {sum(r['net'] > 0 for r in rows) / len(rows):.0%} |")
    L += ["", "### By month (account)", "", "| month | trades | net |", "|---|---|---|"]
    for mth, rows in sorted(group([{**t, "m": t["day"][:7]} for t in taken], "m").items()):
        L.append(f"| {mth} | {len(rows)} | {rs(sum(r['net'] for r in rows))} |")
    L += ["", "### Calls vs puts (account)", ""]
    for d_, rows in sorted(group(taken, "dir").items()):
        L.append(f"- {'Calls' if d_ == 'LONG' else 'Puts'}: {len(rows)} trades, {rs(sum(r['net'] for r in rows))}")
    L += real_prices([t for t in taken if date.fromisoformat(t["day"]) >= real_from], reg, session, bucket, cfg, today)
    print("\n".join(L))
    return 0


def real_prices(rows: list, reg, session, bucket, cfg, today: date) -> list:
    """Section B: the account's recent trades re-priced on real 1-minute option candles."""
    from options_trader_test import at_or_before, option_bars, pick
    half, out, cache = 0.01, [], {}
    for t in rows:
        d = date.fromisoformat(t["day"])
        chain = [(str(c.expiry), float(c.strike), c.instrument_type, c.token, c.lot_size)
                 for c in reg.get_contracts(t["symbol"], today) if c.instrument_type in ("CE", "PE")]
        c = pick(chain, "CE" if t["dir"] == "LONG" else "PE", t["entry_px"], d, cfg.get("contracts.min_dte_days"))
        if c is None:
            continue
        exp, strike, kind, tok, lot = c
        bars = option_bars(session, bucket, tok, d, cache)
        ns = lambda x: int(x.timestamp()) * 1_000_000_000  # noqa: E731
        e0, x0 = at_or_before(bars, ns(t["t"])), at_or_before(bars, ns(t["exit_t"]))
        if e0 is None or x0 is None:
            continue
        entry, exit_ = e0[1] * (1 + half), x0[1] * (1 - half)
        costs = round_trip(cfg, "OPT", "BUY", entry, exit_, lot, d).total_inr
        out.append({**t, "contract": f"{t['symbol']} {strike:g} {kind} {exp}", "qty": lot, "entry": entry, "exit": exit_,
                    "capital": entry * lot, "gross": (exit_ - entry) * lot, "costs": costs, "net": (exit_ - entry) * lot - costs})
    L = ["", f"## B. Real option prices (Kite 1-minute candles), account trades since {rows[0]['day'] if rows else '—'}", ""]
    if not out:
        return L + ["No trade could be priced on real option candles."]
    L += summary_rows(out) + ["", "| day | time | option | premium ₹ | out ₹ (why) | net |", "|---|---|---|---|---|---|"]
    L += [f"| {r['day']} | {r['time']} | {r['contract']} | {r['entry']:,.2f} | {r['exit']:,.2f} ({r['exit_reason']}) | "
          f"**{rs(r['net'])}** |" for r in out]
    return L


if __name__ == "__main__":
    sys.exit(main())
