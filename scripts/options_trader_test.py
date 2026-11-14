"""Options trader's test (APPROXIMATE): take every setup the engine signalled as a long option, one lot, the way an
options trader would, and price it on the option's real 1-minute candles.

- Contract: bullish -> call, bearish -> put; strike = the master strike nearest the future's price at the signal;
  expiry = the nearest one with at least contracts.min_dte_days left (the Phase 7 selector's expiry rule). One lot.
- Prices: Kite historical 1-minute candles of that option for the day (read-only GET, rate-limited, F-HIST-1/2).
  Entry at the close of the candle ending at the signal; exit at the close of the exit minute.
- Spread: the day has no recorded option order book, so each side pays an ASSUMED half-spread of --half-spread-pct
  (default 1 % of premium = half of the engine's 2 % options spread cap). Result labelled APPROXIMATE.
- Exits (same rules as scripts/trader_test.py): the future closes through the setup's structural stop
  (HARD_STOP_UNDERLYING), the trade's net P&L reaches -risk.max_daily_loss_inr (DAILY_LOSS_LIMIT), or
  monitor.squareoff_cutoff (SQUAREOFF_CUTOFF).
- Charges: the verified option schedule (engine.costs.round_trip, product OPT).
Research only: nothing is written to any engine store.

  python3 scripts/options_trader_test.py 2026-11-06 [--half-spread-pct 1.0] [--save rows.json | --load rows.json]
"""

import bisect
import csv
import gzip
import io
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import paper as P                                       # noqa: E402
from engine.backfill import TokenBucket                             # noqa: E402
from engine.broker import KiteSession                               # noqa: E402
from engine.candles import IST, S                                   # noqa: E402
from engine.costs import round_trip                                 # noqa: E402
from engine.ledger import _latest_version                           # noqa: E402
from engine.signal_report import read                               # noqa: E402
from trader_test import account_view, rs, summary_rows              # noqa: E402

MIN = 60 * S
hm = lambda ns: datetime.fromtimestamp(ns / S, IST).strftime("%H:%M")  # noqa: E731
_ns = lambda d, hhmm: int(datetime.combine(d, datetime.strptime(hhmm, "%H:%M").time(), IST).timestamp()) * S  # noqa: E731


def options_master(day_dir: Path) -> dict:
    """underlying -> [(expiry, strike, kind, token, lot)] from the day's stored exchange master."""
    out = {}
    with gzip.open(day_dir / "instruments.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            if r["segment"] == "NFO-OPT":
                out.setdefault(r["name"], []).append((r["expiry"], float(r["strike"]), r["instrument_type"],
                                                      int(r["instrument_token"]), int(r["lot_size"])))
    return out


def pick(chain: list, kind: str, fut_rupees: float, day: date, min_dte: int):
    exps = sorted({e for e, *_ in chain if (date.fromisoformat(e) - day).days >= min_dte})
    if not exps:
        return None
    rows = [c for c in chain if c[0] == exps[0] and c[2] == kind]
    return min(rows, key=lambda c: (abs(c[1] - fut_rupees), c[1])) if rows else None


def future_bars(day_dir: Path) -> dict:
    """underlying -> sorted [(end_ns, close_rupees)] of the near-month future (Phase 3 candles, as stored)."""
    db = sqlite3.connect(f"file:{day_dir / 'dashboard.sqlite'}?mode=ro", uri=True)
    out = {}
    try:
        v = _latest_version(day_dir / "dashboard.sqlite", "candles")
        for und, end, p in db.execute("SELECT underlying, end_ns, payload FROM candles WHERE config_version=? ORDER BY end_ns", (v,)):
            d = json.loads(p)
            if d.get("interval") == "1m" and not isinstance(d["close"], dict):
                out.setdefault(und, []).append((end, d["close"] / 100))
    finally:
        db.close()
    return out


def option_bars(session, bucket, token: int, day: date, cache: dict) -> list:
    """[(end_ns, close_rupees)] from Kite historical minute candles (start time + 1 min = candle end)."""
    if token not in cache:
        bucket.take()
        rows = session.historical(token, "minute", f"{day} 09:15:00", f"{day} 15:30:00", False)
        cache[token] = [(int(datetime.fromisoformat(r[0]).timestamp()) * S + MIN, float(r[4])) for r in rows]
    return cache[token]


def at_or_before(bars: list, ns: int):
    i = bisect.bisect_right([b[0] for b in bars], ns)
    return bars[i - 1] if i else None


def trade_one(rec: dict, chain: list, fut: list, session, bucket, cache, day: date, cfg, half: float) -> dict:
    p = json.loads(rec["payload"])
    row = {"day": str(day), "time": hm(rec["as_of"]), "symbol": p["underlying"], "dir": p["direction"],
           "engine": rec["status"], "why_rejected": [g["name"] for g in p["gates"] if not g["passed"]]}
    stop = p.get("underlying_invalidation")
    f0 = at_or_before(fut, rec["as_of"])
    if not isinstance(stop, int) or f0 is None:
        return {**row, "result": "NOT TRADABLE", "note": "no structural stop or no future price"}
    kind = "CE" if p["direction"] == "LONG" else "PE"
    c = pick(chain, kind, f0[1], day, cfg.get("contracts.min_dte_days"))
    if c is None:
        return {**row, "result": "NOT TRADABLE", "note": f"no {kind} contract in the master"}
    exp, strike, _, tok, lot = c
    ob = option_bars(session, bucket, tok, day, cache)
    e0 = at_or_before(ob, rec["as_of"])
    if e0 is None or rec["as_of"] - e0[0] > 5 * MIN:
        return {**row, "result": "NO FILL", "note": f"{p['underlying']} {strike:g}{kind}: no option trade near the signal"}
    entry = e0[1] * (1 + half)
    cutoff = _ns(day, cfg.get("monitor.squareoff_cutoff"))
    cap, long_ = cfg.get("risk.max_daily_loss_inr"), p["direction"] == "LONG"
    exit_ns, exit_px, why = None, None, "SQUAREOFF_CUTOFF"
    for end, fclose in (b for b in fut if rec["as_of"] < b[0] <= cutoff):
        o = at_or_before(ob, end)
        px = o[1] * (1 - half) if o else None
        if (fclose <= stop / 100) if long_ else (fclose >= stop / 100):
            exit_ns, exit_px, why = end, px, "HARD_STOP_UNDERLYING"
            break
        if px is not None:
            net = (px - entry) * lot - round_trip(cfg, "OPT", "BUY", entry, px, lot, day).total_inr
            if net <= -cap:
                exit_ns, exit_px, why = end, px, "DAILY_LOSS_LIMIT"
                break
        exit_ns, exit_px = end, px
    if exit_px is None:
        return {**row, "result": "NOT CLOSED", "note": "no option price at the exit minute"}
    gross = (exit_px - entry) * lot
    costs = round_trip(cfg, "OPT", "BUY", entry, exit_px, lot, day).total_inr
    return {**row, "result": "CLOSED", "contract": f"{p['underlying']} {strike:g} {kind} {exp}", "lots": 1, "qty": lot,
            "entry": entry, "capital": entry * lot, "exit": exit_px, "exit_time": hm(exit_ns), "exit_reason": why,
            "gross": gross, "costs": costs, "net": gross - costs}


def run_day(d: str, cfg, half: float) -> list:
    day, day_dir = date.fromisoformat(d), cfg.root / d
    try:
        v = _latest_version(day_dir / "signals.sqlite", "recommendations")
    except ValueError:      # no recommendation at all that day (e.g. an exchange holiday)
        return []
    recs = read(day_dir, v)["recommendations"]
    first = {}
    for r in recs:
        first.setdefault(r["signal_id"], r)
    chains, futs = options_master(day_dir), future_bars(day_dir)
    session, bucket, cache = KiteSession.load(), TokenBucket(cfg.get("historical.rate_per_s")), {}
    return [trade_one(r, chains.get(json.loads(r["payload"])["underlying"], []),
                      futs.get(json.loads(r["payload"])["underlying"], []), session, bucket, cache, day, cfg, half)
            for r in sorted(first.values(), key=lambda r: r["as_of"])]


def report(rows: list, cfg, half_pct: float) -> str:
    closed = [r for r in rows if r["result"] == "CLOSED"]
    taken, notes = account_view(rows, cfg)
    L = ["# Options trader's test (APPROXIMATE): every signal taken as a long option, one lot", "",
         f"Days: {', '.join(sorted({r['day'] for r in rows}))}. Setups: {len(rows)}. Traded and closed: {len(closed)}.",
         f"Prices: real Kite 1-minute option candles. Spread: ASSUMED {half_pct:g} % of premium per side (no recorded "
         "option order book). Charges: verified option schedule.", "",
         "## A. Every signal taken (one lot each), no account limits", ""] + summary_rows(closed)
    L += ["", "## B. Your account: signals in time order, only when they fit your rules", "",
          f"Capital ₹{cfg.get('risk.capital_inr'):,} with {cfg.get('risk.capital_reserve_pct')}% reserve, max "
          f"{rs(cfg.get('risk.max_capital_per_trade_inr'))} premium per trade, max {cfg.get('risk.max_open_positions')} open, "
          f"stop for the day at -{rs(cfg.get('risk.max_daily_loss_inr'))}.", ""]
    L += summary_rows(taken) if taken else ["No signal fitted your rules."]
    L += ["", "Taken: " + (", ".join(f"{r['time']} {r['contract']} {rs(r['net'])}" for r in taken) or "none"), "",
          f"Skipped by your rules: {len(notes)}", ""] + [f"- {n}" for n in notes[:15]]
    L += ["", "## Every setup", "",
          "| time | contract | lot | premium in ₹ | out ₹ (time, why) | gross | charges | **net** | engine said |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["time"]):
        verdict = r["engine"] + (f" ({', '.join(r['why_rejected'])})" if r["why_rejected"] else "")
        if r["result"] == "CLOSED":
            L.append(f"| {r['time']} | {r['contract']} | {r['qty']} | {r['entry']:,.2f} ({rs(r['capital'])}) | "
                     f"{r['exit']:,.2f} ({r['exit_time']}, {r['exit_reason']}) | {rs(r['gross'])} | {rs(r['costs'])} | "
                     f"**{rs(r['net'])}** | {verdict} |")
        else:
            L.append(f"| {r['time']} | {r['symbol']} {r['dir']} | — | — | {r['result']}: {r['note']} | — | — | — | {verdict} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    opt = lambda name: [args[i + 1] for i, a in enumerate(args) if a == name]  # noqa: E731
    half_pct = float((opt("--half-spread-pct") or ["1.0"])[0])
    days = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))] \
        or [date.today().isoformat()]
    cfg = P.load()
    load, save = opt("--load"), opt("--save")
    rows = json.loads(Path(load[0]).read_text()) if load else [r for d in days for r in run_day(d, cfg, half_pct / 100)]
    if save:
        Path(save[0]).write_text(json.dumps(rows, indent=1))
    print(report(rows, cfg, half_pct))
    return 0


if __name__ == "__main__":
    sys.exit(main())
