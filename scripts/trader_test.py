"""Trader's test of recorded days: take EVERY setup the engine signalled (rejected ones too), once, the way a trader would.

- Entry: at the setup's first recommendation, on the recorded order book. BUY walks the asks and SELL walks the bids
  (Phase 9 paper_fill on the real 5-level depth), so the spread and slippage are paid.
- Size: the recommendation's own lots (risk-based; lot size from the exchange instrument master).
- Exits: the engine's own live monitor (Phase 9 run_trades) with your limits: stop, max loss per trade, daily-loss exit,
  15:10 square-off. Exits fill on the book as well.
- Charges: every component in the verified schedule (brokerage, STT, exchange, SEBI, stamp, GST, IPFT) on both legs.
Each trade runs on its own (no position or capital limits), so this answers "what if I had taken all of them".
Research only: nothing is written to the paper ledger or any engine store.

  python3 scripts/trader_test.py 2026-11-06 [more dates] [--set risk.max_daily_loss_inr=30000] [--save rows.json | --load rows.json]
"""

import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import paper as P                                                        # noqa: E402
from engine import signals as G                                                      # noqa: E402
from engine.candles import IST, S, Unavailable                                       # noqa: E402
from engine.costs import round_trip                                                  # noqa: E402
from engine.ledger import (_Inputs, _latest_version, cfg_opp_version, cfg_str_version, day_events,  # noqa: E402
                           trade_from_payload)
from engine.signal_report import QuoteBook, read                                    # noqa: E402

hm = lambda ns: datetime.fromtimestamp(ns / S, IST).strftime("%H:%M")  # noqa: E731
rs = lambda x: f"₹{x:,.0f}"  # noqa: E731


def trade_one(cfg, day_dir: Path, rec: dict, recs: list, buf) -> dict:
    p = json.loads(rec["payload"])
    row = {"time": hm(rec["as_of"]), "symbol": p["underlying"], "dir": p["direction"], "engine": rec["status"],
           "why_rejected": [g["name"] for g in p["gates"] if not g["passed"]]}
    qty, lot, tok = p.get("quantity"), p.get("lot_size"), p.get("token")
    if not isinstance(qty, int) or not isinstance(lot, int) or not isinstance(tok, int):
        return {**row, "result": "NOT TRADABLE", "note": "no contract / size (no stop or target defined)"}
    qb = QuoteBook(buf)
    qb.load([tok])
    f = P.paper_fill(p["side"], qty, lot, qb.quotes([tok], rec["as_of"]).get(tok), rec["as_of"], cfg)
    if isinstance(f, Unavailable):
        return {**row, "result": "NO FILL", "note": f.reason}
    t = trade_from_payload(p, P.SIMULATED, f"TT:{rec['recommendation_id']}", f.avg_price, f.qty_filled, rec["as_of"],
                           cfg.version)
    res = P.run_trades([t], day_events(day_dir, {t.price_token, t.contract_token}, rec["as_of"]),
                       _Inputs(day_dir, [t], recs, cfg_opp_version(day_dir), cfg_str_version(day_dir)), cfg,
                       {P.SIMULATED: 0.0})
    exits = [x for x in res.fills if x.trade_id == t.id]
    reason = next((d.rule_id for d in reversed(res.decisions) if d.decision == P.EXIT_REQUIRED), "")
    sgn, prod = (1 if t.side == "BUY" else -1), ("FUT" if t.kind == "FUT" else "OPT")
    gross = sum(sgn * (x.avg_price - f.avg_price) * x.qty_filled / 100 for x in exits)
    costs = sum(round_trip(cfg, prod, t.side, f.avg_price / 100, x.avg_price / 100, x.qty_filled, t.day).total_inr
                for x in exits)
    out_qty = sum(x.qty_filled for x in exits)
    base = {**row, "lots": f.qty_filled // lot, "qty": f.qty_filled, "entry": f.avg_price / 100,
            "entry_slip": f.slippage_per_unit / 100}
    if out_qty < f.qty_filled:
        nf = [n.reason for n in res.no_fills if n.trade_id == t.id]
        return {**base, "result": "NOT CLOSED", "note": (nf[-1] if nf else "no exit fill on the recorded book")}
    last = max(exits, key=lambda x: x.as_of)
    return {**base, "result": "CLOSED", "exit": last.avg_price / 100, "exit_time": hm(last.as_of), "exit_reason": reason,
            "gross": gross, "costs": costs, "net": gross - costs}


def run_day(d: str, cfg) -> list[dict]:
    day_dir = cfg.root / d
    version = _latest_version(day_dir / "signals.sqlite", "recommendations")
    recs = read(day_dir, version)["recommendations"]
    first = {}
    for r in recs:                         # a trader takes a setup once: at its first recommendation
        first.setdefault(r["signal_id"], r)
    buf = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
    buf.row_factory = sqlite3.Row
    try:
        return [{"day": d, **trade_one(cfg, day_dir, r, recs, buf)} for r in sorted(first.values(), key=lambda r: r["as_of"])]
    finally:
        buf.close()


def account_view(rows: list[dict], cfg) -> tuple[list[dict], list[str]]:
    """Your account, in signal order: a setup is taken only if it fits your rules at that moment. Approximation: each
    trade keeps the result of its own run (its exits do not see the other open trades' P&L)."""
    R = lambda k: cfg.get(f"risk.{k}")  # noqa: E731
    usable, frac = R("capital_inr") * (100 - R("capital_reserve_pct")) / 100, cfg.get("contracts.futures_margin.fraction")
    taken, notes, by_day = [], [], {}
    for r in sorted((r for r in rows if r["result"] == "CLOSED"), key=lambda r: (r["day"], r["time"])):
        st = by_day.setdefault(r["day"], {"open": [], "realized": 0.0})
        for o in [o for o in st["open"] if o["exit_time"] <= r["time"]]:
            st["realized"] += o["net"]
            st["open"].remove(o)
        margin = r.get("capital", r["entry"] * r["qty"] * frac)   # options: the full premium paid
        why = ("day stopped: losses reached the daily cap" if st["realized"] <= -R("max_daily_loss_inr") else
               "already at the open-position limit" if len(st["open"]) >= R("max_open_positions") else
               f"needs {rs(margin)} margin > {rs(R('max_capital_per_trade_inr'))} per-trade limit"
               if margin > R("max_capital_per_trade_inr") else
               "not enough free capital" if margin + sum(o["margin"] for o in st["open"]) > usable else None)
        if why:
            notes.append(f"{r['day']} {r['time']} {r['symbol']}: skipped ({why})")
            continue
        st["open"].append({**r, "margin": margin})
        taken.append(r)
    return taken, notes


def summary_rows(closed: list[dict]) -> list[str]:
    wins, losses = [r for r in closed if r["net"] > 0], [r for r in closed if r["net"] <= 0]
    eq = peak = dd = 0.0
    for r in sorted(closed, key=lambda r: (r["day"], r["exit_time"])):
        eq += r["net"]
        peak, dd = max(peak, eq), min(dd, eq - peak)
    lw = -sum(r["net"] for r in losses)
    return ["| | |", "|---|---|",
            f"| Net P&L after all charges | **{rs(sum(r['net'] for r in closed))}** |",
            f"| Gross P&L (before charges) | {rs(sum(r['gross'] for r in closed))} |",
            f"| Charges paid | {rs(sum(r['costs'] for r in closed))} |",
            f"| Trades: winners / losers | {len(closed)}: {len(wins)} / {len(losses)} ({100 * len(wins) / max(len(closed), 1):.0f}% win rate) |",
            f"| Average winner / average loser | {rs(sum(r['net'] for r in wins) / max(len(wins), 1))} / "
            f"{rs(-lw / max(len(losses), 1))} |",
            f"| Biggest winner / biggest loser | {rs(max((r['net'] for r in closed), default=0))} / "
            f"{rs(min((r['net'] for r in closed), default=0))} |",
            f"| Profit factor (₹ won ÷ ₹ lost, after charges) | {(sum(r['net'] for r in wins) / lw) if lw else float('nan'):.2f} |",
            f"| Worst drawdown (in exit order) | {rs(dd)} |"]


def report(rows: list[dict], cfg=None) -> str:
    closed = [r for r in rows if r["result"] == "CLOSED"]
    L = ["# Trader's test: every signal taken (SIMULATED on the recorded order book)", "",
         f"Days: {', '.join(sorted({r['day'] for r in rows}))}. Setups: {len(rows)}. Traded and closed: {len(closed)}. "
         f"Not tradable / no fill / not closed: {len(rows) - len(closed)}.", "",
         "## A. Every signal taken, no account limits", ""] + summary_rows(closed)
    if cfg is not None:
        taken, notes = account_view(rows, cfg)
        L += ["", "## B. Your account: signals in time order, only when they fit your rules", "",
              f"Capital ₹{cfg.get('risk.capital_inr'):,} with {cfg.get('risk.capital_reserve_pct')}% reserve, "
              f"max {rs(cfg.get('risk.max_capital_per_trade_inr'))} margin per trade "
              f"(futures margin estimated at {cfg.get('contracts.futures_margin.fraction'):.0%} of value), "
              f"max {cfg.get('risk.max_open_positions')} open, stop for the day at "
              f"-{rs(cfg.get('risk.max_daily_loss_inr'))}. Approximate: each trade keeps its own result.", ""]
        L += summary_rows(taken) if taken else ["No signal fitted your rules."]
        L += ["", "Taken: " + (", ".join(f"{r['time']} {r['symbol']} {rs(r['net'])}" for r in taken) or "none"), "",
              f"Skipped by your rules: {len(notes)}" + ("" if not notes else " (first 15 below)"), ""]
        L += [f"- {n}" for n in notes[:15]]
    L += ["", "## Every setup", "",
         "| day | time | symbol | dir | lots | entry ₹ | exit ₹ (time, why) | gross | charges | **net** | engine said |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["day"], r["time"])):
        verdict = r["engine"] + (f" ({', '.join(r['why_rejected'])})" if r["why_rejected"] else "")
        if r["result"] == "CLOSED":
            L.append(f"| {r['day']} | {r['time']} | {r['symbol']} | {r['dir']} | {r['lots']} | {r['entry']:,.2f} | "
                     f"{r['exit']:,.2f} ({r['exit_time']}, {r['exit_reason']}) | {rs(r['gross'])} | {rs(r['costs'])} | "
                     f"**{rs(r['net'])}** | {verdict} |")
        else:
            L.append(f"| {r['day']} | {r['time']} | {r['symbol']} | {r['dir']} | — | — | {r['result']}: {r['note']} | — | — | — | "
                     f"{verdict} |")
    return "\n".join(L) + "\n"


def with_overrides(cfg, sets: list[str]):
    """--set risk.max_daily_loss_inr=30000: a what-if on one rule; the report header says which."""
    import copy
    from engine.config import EngineConfig
    v = copy.deepcopy(dict(cfg.values))
    for s in sets:
        key, val = s.split("=", 1)
        *head, last = key.split(".")
        node = v
        for h in head:
            node = node[h]
        node[last] = type(node[last])(val)
    return EngineConfig(f"{cfg.version}+{'+'.join(sets)}", cfg.sha256, v)


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    opt = lambda name: [args[i + 1] for i, a in enumerate(args) if a == name]  # noqa: E731
    sets, save, load = opt("--set"), opt("--save"), opt("--load")
    days = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or not args[i - 1].startswith("--"))] \
        or [date.today().isoformat()]
    cfg = with_overrides(P.load(), sets) if sets else P.load()
    if sets:
        print(f"> What-if: {', '.join(sets)} (config {cfg.version}). Everything else as configured.\n")
    # --save rows.json keeps the simulated trades; --load rows.json rebuilds the report without re-simulating
    rows = json.loads(Path(load[0]).read_text()) if load else [r for d in days for r in run_day(d, cfg)]
    if save:
        Path(save[0]).write_text(json.dumps(rows, indent=1))
    print(report(rows, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
