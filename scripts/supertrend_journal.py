"""Supertrend paper-trade journal (owner request 2026-11-13). Advisory and paper only: no order is ever placed.

Every weekday evening (com.clade.engine-supertrend-journal, 16:30) it records the day's candidate trades on REAL option
prices and replays the owner's account, so the rules can be adjusted from our own trades.

Candidate trade (owner's rules, as scripts/supertrend_options_test.py): a 5-minute Supertrend(10,3) flip on the stock's cash
price whose candle closes before 14:00 with the 15-minute trend agreeing; buy 1 lot of the 1-strike-ITM option of the
current month (nearest expiry after the trade day); entry = the option's first traded minute after the flip close.
Exits are kept for three exit styles: "depends" (line stop any time; at 15:15 hold overnight only if 5m and 15m both
agree; next day the line stop sells on the flip), "depends_ps" (the same + sell if the option trades 25 % below entry),
"intraday" (line stop, out by 15:15). A position still open on its contract's expiry day is sold at 15:15 that day.
Candidates are SAVED (data/engine/supertrend_journal.sqlite) because Kite keeps minute history only for listed contracts
(F-HIST-7): once a contract expires its trades can no longer be re-priced. Open ones are re-priced each evening.

Universe and account match the live paper account (owner 2026-11-16): the Supertrend board's stocks and indices
(dashboard.supertrend._tokens, ~222) and its ₹1,00,000 start (supertrend_paper.START_CASH); a trade may use the whole
cash balance; profits are reused and losses shrink it. Signals in time order, same candle -> strongest volume first;
max 4 open, 5 trades a day.
Versions replayed side by side from the same candidates:
  MAIN  the owner's rules: line stop, the live day loss budget (10 % of the day's opening balance + today's closed P&L,
        each open lot counting RISK = 30 % of its premium; supertrend_trades.view), 2 losses in a row -> done for the day
  NO_DAY_LIMITS   MAIN without the day loss budget and the 2-loss rule (do they help?)
  PREMIUM_STOP    MAIN + sell if the option trades 25 % below entry (does it help?)
Output for the dashboard: data/engine/supertrend_journal.json.

  python3 scripts/supertrend_journal.py                  # today (after the close), re-price open trades, replay
  python3 scripts/supertrend_journal.py --from 2026-10-28  # backfill each trading day since then
  python3 scripts/supertrend_journal.py --replay-only
ASSUMED 1 % half-spread per side (no quote history); charges from the verified schedule (engine.costs.round_trip).
"""

import bisect
import json
import sqlite3
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
from dashboard.option_chain import _instruments                     # noqa: E402
from dashboard.supertrend import _tokens                            # noqa: E402
from dashboard.supertrend_paper import START_CASH                   # noqa: E402
from dashboard.supertrend_trades import LIMITS as LIVE, RISK        # noqa: E402
from supertrend_options_test import (CUT, HALF, LAST_ENTRY, NO_FILL_MIN, PREMIUM_STOP, _trend_at, account,  # noqa: E402
                                     exit_depends, exits, fill)
from supertrend_research import to15                                # noqa: E402

CAPITAL = START_CASH                 # the live paper account's start, so the replay's budget is the same
NO_CAP = float("inf")
VERSIONS = (
    ("MAIN", "Your rules: line stop · day loss budget 10% of balance (each lot counts 30% of its premium) · "
             "2 losses in a row = done for the day", "depends",
     {"max_premium": NO_CAP, "risk_budget": (LIVE["day_loss_pct"], RISK), "cooldown": 2}),
    ("NO_DAY_LIMITS", "Without the day loss budget and the 2-loss rule", "depends", {"max_premium": NO_CAP}),
    ("PREMIUM_STOP", "Your rules + sell if the option trades 25% below entry", "depends_ps",
     {"max_premium": NO_CAP, "risk_budget": (LIVE["day_loss_pct"], RISK), "cooldown": 2}),
)
EXIT_KEYS = ("depends", "depends_ps", "intraday")
WARMUP_DAYS = 14                     # calendar days of 5-minute candles before the day: Supertrend 5m/15m fully settled


# ---------------------------------------------------------------- store
def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS cands (id TEXT PRIMARY KEY, day TEXT, final INTEGER, payload TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, payload TEXT)")
    return db


def _enc(x):
    return x.isoformat() if isinstance(x, (datetime, date)) else x


def save(db, cand: dict) -> None:
    final = all(cand[k] is None or cand[k]["out_t"] is not None for k in EXIT_KEYS)
    db.execute("INSERT OR REPLACE INTO cands VALUES (?,?,?,?)",
               (cand["id"], cand["t"][:10] if isinstance(cand["t"], str) else cand["t"].date().isoformat(), int(final),
                json.dumps(cand, default=_enc)))


def load(db, where: str = "") -> list:
    out = []
    for (p,) in db.execute(f"SELECT payload FROM cands {where} ORDER BY id"):
        c = json.loads(p)
        c["t"] = datetime.fromisoformat(c["t"])
        for k in EXIT_KEYS:
            if c.get(k) and c[k]["out_t"]:
                c[k]["out_t"] = datetime.fromisoformat(c[k]["out_t"])
        out.append(c)
    return out


# ---------------------------------------------------------------- pricing (pure given the bars)
def price_exits(c: dict, st, ends5, st15, ends15, cs5, m1, ob, cfg) -> dict:
    """The candidate's three exits on data so far; a position past its expiry's 15:15 is sold then."""
    side, t, entry_raw = c["side"], c["t"], c["entry_px"]
    starts = [b[0] for b in ob]
    expiry_cut = datetime.combine(date.fromisoformat(c["expiry"]), CUT, IST)
    dep = exit_depends(side, t, st, ends5, st15, ends15, m1)
    ps = next(((b[0], min(b[1], PREMIUM_STOP * entry_raw)) for b in ob[bisect.bisect_right(starts, datetime.fromisoformat(c["entry_t"])):]
               if b[3] <= PREMIUM_STOP * entry_raw), None)
    ps_exit = (ps[0], "PREMIUM_STOP_25%") if ps and (dep[0] is None or ps[0] < dep[0]) else dep
    out = {}
    for key, (xt, why) in (("depends", dep), ("depends_ps", ps_exit), ("intraday", exits(side, t, st, cs5, m1, False)["LINE"])):
        if (xt is None or xt > expiry_cut) and ob and ob[-1][0] >= expiry_cut - timedelta(minutes=30):
            xt, why = expiry_cut, "EXPIRY_DAY 15:15"
        if why == "PREMIUM_STOP_25%":
            x = ps
        elif xt is None:
            x = (ob[-1][0], ob[-1][4]) if ob else None
        else:
            x = fill(ob, starts, xt) or fill(ob, starts, xt - timedelta(minutes=NO_FILL_MIN), 4)
        if x is None:
            out[key] = None
            continue
        entry, exit_ = entry_raw * (1 + HALF), x[1] * (1 - HALF)
        costs = round_trip(cfg, "OPT", "BUY", entry, exit_, c["lot"], t.date()).total_inr
        out[key] = {"out_t": xt, "why": why, "net": (exit_ - entry) * c["lot"] - costs, "mark": x[1], "mark_t": x[0],
                    "nights": ((xt or x[0]).date() - t.date()).days}
    return out


# ---------------------------------------------------------------- one evening
class Kite:
    def __init__(self, cfg):
        self.session, self.bucket = KiteSession.load(), TokenBucket(cfg.get("historical.rate_per_s"))

    def bars(self, token: int, interval: str, start: date, end: date) -> list:
        self.bucket.take()
        rows = self.session.historical(token, interval, f"{start} 09:15:00", f"{end} 15:30:00", False)
        return [(datetime.fromisoformat(r[0]).astimezone(IST), *r[1:6]) for r in rows]


def is_trading_day(cfg, d: date) -> bool:
    return d.weekday() < 5 and all(h["date"] != d for h in cfg.get("restrictions.holidays"))


def universe() -> tuple:
    """The live board's symbols -> spot token, and each one's option chain from TODAY's NFO master (a backfill only
    reaches back while those contracts are listed: Kite keeps minute history only for listed contracts, F-HIST-7)."""
    chains = defaultdict(list)
    for r in _instruments():
        if r["instrument_type"] in ("CE", "PE"):
            chains[r["name"]].append((date.fromisoformat(r["expiry"]), float(r["strike"]), r["instrument_type"],
                                      int(r["instrument_token"]), int(r["lot_size"])))
    return {s: int(t) for s, t in _tokens().items()}, chains


def run_day(cfg, db, kite, uni: dict, chains: dict, day: date) -> dict:
    """Record `day`'s candidates and re-price every open one with data through `day`. `uni`, `chains`: universe()."""
    open_by_sym = defaultdict(list)
    for c in load(db, "WHERE final = 0"):
        if c["t"].date() < day:
            open_by_sym[c["sym"]].append(c)
    stats = defaultdict(int)
    for sym, spot_token in sorted(uni.items()):
        olds = open_by_sym.get(sym, [])
        first = min([c["t"].date() for c in olds] + [day])
        cs5 = [c[:6] for c in kite.bars(spot_token, "5minute", first - timedelta(days=WARMUP_DAYS), day)]
        if not cs5:
            continue
        st, ends5 = supertrend(cs5), [c[0] + timedelta(minutes=5) for c in cs5]
        c15 = to15(cs5)
        st15, ends15 = supertrend(c15), [c[0] + timedelta(minutes=15) for c in c15]
        m1 = [c[:5] for c in kite.bars(spot_token, "minute", first, day)]
        slot, rvol = defaultdict(list), []
        for c in cs5:
            h = slot[(c[0].hour, c[0].minute)]
            rvol.append(c[5] / (sum(h[-10:]) / 10) if len(h) >= 10 and sum(h[-10:]) else None)
            h.append(c[5])
        for c in olds:                                                       # re-price positions still open
            ob = [b[:5] for b in kite.bars(c["token"], "minute", c["t"].date(), day)]
            c.update(price_exits(c, st, ends5, st15, ends15, cs5, m1, ob, cfg))
            save(db, c)
        chain = chains.get(sym, [])
        for k in range(1, len(cs5)):
            t0 = cs5[k][0]
            if t0.date() != day or not (st[k] and st[k - 1]) or st[k][0] == st[k - 1][0]:
                continue
            stats["5m flips"] += 1
            t, side = t0 + timedelta(minutes=5), st[k][0]
            if t.strftime("%H:%M") >= LAST_ENTRY:
                stats[f"flip at/after {LAST_ENTRY}"] += 1
                continue
            if _trend_at(st15, ends15, t) != side:
                stats["15m not agreeing"] += 1
                continue
            kind = "CE" if side == 1 else "PE"
            exps = sorted({e for e, _, kk, _, _ in chain if kk == kind and e > day})     # current month, not expiring today
            rows = sorted((x for x in chain if exps and x[0] == exps[0] and x[2] == kind), key=lambda x: x[1])
            if not rows:
                stats["no option listed"] += 1
                continue
            strikes = [x[1] for x in rows]
            atm = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - cs5[k][4]), strikes[i]))
            j = atm - 1 if kind == "CE" else atm + 1
            if not 0 <= j < len(rows):
                stats["no 1-strike-ITM option listed"] += 1
                continue
            exp, strike, _, tok, lot = rows[j]
            ob = [b[:5] for b in kite.bars(tok, "minute", day, day)]
            e = fill(ob, [b[0] for b in ob], t)
            if e is None:
                stats["option not traded within 5 min of the flip"] += 1
                continue
            c = {"id": f"{t.isoformat()}|{sym}", "sym": sym, "t": t, "side": side, "kind": kind,
                 "contract": f"{sym} {strike:g} {kind} {exp}", "token": tok, "lot": lot, "expiry": str(exp),
                 "rvol": rvol[k], "entry_t": e[0].isoformat(), "entry_px": e[1], "premium": e[1] * (1 + HALF) * lot}
            c.update(price_exits(c, st, ends5, st15, ends15, cs5, m1, ob, cfg))
            save(db, c)
            stats["candidates"] += 1
    db.execute("INSERT OR REPLACE INTO days VALUES (?,?)", (day.isoformat(), json.dumps(stats)))
    db.commit()
    return dict(stats)


# ---------------------------------------------------------------- replay -> dashboard JSON
def replay(db) -> dict:
    cands = load(db)
    days = {d: json.loads(p) for d, p in db.execute("SELECT day, payload FROM days ORDER BY day")}
    out = {"generated_at": datetime.now(IST).isoformat(timespec="seconds"), "capital": CAPITAL, "days": days, "versions": []}
    for vid, label, key, rules in VERSIONS:
        log = []
        taken, _ = account(cands, key, CAPITAL, rules, log)
        closed = sorted((o for o in taken if o["out_t"]), key=lambda o: o["out_t"])
        cum = peak = dd = 0.0
        low = CAPITAL
        for o in closed:
            cum += o["net"]
            peak, dd, low = max(peak, cum), max(dd, peak - cum), min(low, CAPITAL + cum)
        open_mark = sum(o["net"] for o in taken if not o["out_t"])
        by_day = defaultdict(float)
        for o in closed:
            by_day[o["out_t"].date().isoformat()] += o["net"]
        bal, curve = CAPITAL, []
        for d in sorted(set(days) | set(by_day)):
            bal += by_day.get(d, 0.0)
            curve.append({"day": d, "pnl": round(by_day.get(d, 0.0)), "balance": round(bal)})
        skips = defaultdict(lambda: {"count": 0, "would_have_made": 0.0})
        for c, why in log:
            if why != "TAKEN" and c.get(key):
                skips[why]["count"] += 1
                skips[why]["would_have_made"] += c[key]["net"]
        nets = [o["net"] for o in closed]
        wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
        out["versions"].append({
            "id": vid, "label": label, "exit": key,
            "summary": {"start": CAPITAL, "balance": round(CAPITAL + sum(nets)), "closed_pnl": round(sum(nets)),
                        "open_pnl": round(open_mark), "trades": len(taken), "open": len(taken) - len(closed),
                        "win_rate": round(len(wins) / len(nets) * 100) if nets else None,
                        "avg_win": round(sum(wins) / len(wins)) if wins else None,
                        "avg_loss": round(sum(losses) / len(losses)) if losses else None,
                        "worst_drawdown": round(-dd), "lowest_balance": round(low)},
            "curve": curve,
            # prices are the option's traded prices; premium = bought-at x lot; net also pays the 1 % gap each side + charges
            "trades": [{"entry": o["t"].isoformat(), "sym": o["sym"], "contract": o["contract"], "side": o["kind"],
                        "lot": o["lot"], "entry_px": round(o["entry_px"], 2), "exit_px": round(o["mark"], 2),
                        "premium": round(o["entry_px"] * o["lot"]), "exit": o["out_t"].isoformat() if o["out_t"] else None,
                        "why": o["why"], "nights": o["nights"], "net": round(o["net"])}
                       for o in sorted(taken, key=lambda o: o["t"], reverse=True)],
            "skipped": sorted(({"reason": k, "count": v["count"], "would_have_made": round(v["would_have_made"])}
                               for k, v in skips.items()), key=lambda r: -r["count"]),
        })
    return out


def main(argv=None) -> int:
    cfg = P.load()
    try:
        return _main(cfg, argv if argv is not None else sys.argv[1:])
    except Exception as e:                       # e.g. the Kite token expired: say so instead of a silently stale journal
        from engine.alerts import alert_once
        alert_once(cfg.root, "supertrend_journal", "Supertrend journal FAILED", repr(e)[:400])
        raise


def _main(cfg, args: list) -> int:
    db = connect(cfg.root / "supertrend_journal.sqlite")
    now = datetime.now(IST)
    if "--replay-only" not in args:
        start = date.fromisoformat(args[args.index("--from") + 1]) if "--from" in args else now.date()
        if start == now.date() and now.time() < dtime(15, 35):
            print("today's session is not over yet; nothing recorded", file=sys.stderr)
        else:
            kite, (uni, chains) = Kite(cfg), universe()
            d = start
            while d <= now.date():
                if is_trading_day(cfg, d) and (d < now.date() or now.time() >= dtime(15, 35)):
                    print(d, run_day(cfg, db, kite, uni, chains, d), flush=True)
                d += timedelta(days=1)
    data = replay(db)
    (cfg.root / "supertrend_journal.json").write_text(json.dumps(data))
    for v in data["versions"]:
        print(v["id"], v["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
