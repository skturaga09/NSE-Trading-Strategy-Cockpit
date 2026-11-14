"""Phase 7 report (edge): recorded setups -> contract selector V1 -> risk_check, as a candidate table.

  python3 -m engine.contract_report YYYY-MM-DD [--n 10] [--report PATH] [--json PATH]

Inputs, all recorded, all as of each setup's decision time (no look-ahead: rows with receive_ns <= as_of only):
- setups: Phase 6 `opportunity.sqlite` (config v8), each setup's FIRST TIMELY evaluation: entry = its price, stop = the
  structural stop, target 1 = its obstacle in the trade direction, ATR = its setup-timeframe ATR. Selection rule:
  NIFTY's earliest, the earliest of each family other than SWEEP, then the earliest of other underlyings (one each).
- registry rows and is_tradable: Phase 2 `universe.sqlite`.
- quotes: the latest depth row + latest tick row per token in `buffer.sqlite` (read-only). Spot: latest spot tick.
- option 1m bars: from the same ticks table; none exist when no option was recorded.
- margins: none (no Kite margin call is wired, Q-RISK-1) => futures capital is MARGIN_ESTIMATED.
- portfolio: flat (no positions, no P&L) at each decision time: the report shows per-setup decisions, not a day.
"""

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

from .candles import IST, S
from .contracts import Quote, TradeSetup, load, select_contracts
from .risk import PortfolioState, risk_check
from .snapshots import jsonable
from .universe import Registry

LEVELS = range(5)


def pick_setups(day_dir: Path, n: int) -> list[dict]:
    db = sqlite3.connect(f"file:{day_dir / 'opportunity.sqlite'}?mode=ro", uri=True)
    rows = db.execute("""
        WITH f AS (SELECT setup_id, MIN(as_of) t FROM evaluations
                   WHERE config_version='v8' AND classification='TIMELY' GROUP BY setup_id)
        SELECT s.payload, e.payload FROM f JOIN evaluations e ON e.setup_id=f.setup_id AND e.as_of=f.t AND e.config_version='v8'
        JOIN setups s ON s.id=f.setup_id AND s.config_version='v8' ORDER BY f.t, f.setup_id""").fetchall()
    db.close()
    pairs = [(json.loads(a), json.loads(b)) for a, b in rows]
    chosen, seen = [], set()
    firsts = [next((p for p in pairs if p[0]["underlying"] == "NIFTY"), None)]
    firsts += [next(p for p in pairs if p[0]["family"] == fam) for fam in sorted({p[0]["family"] for p in pairs} - {"SWEEP"})]
    for p in [x for x in firsts if x] + pairs:
        if p[0]["underlying"] not in seen and len(chosen) < n:
            chosen.append(p)
            seen.add(p[0]["underlying"])
    return sorted(chosen, key=lambda p: (p[1]["as_of"], p[0]["id"]))


def _latest(db, table: str, tokens: list[int], as_of: int) -> dict[int, sqlite3.Row]:
    if not tokens:
        return {}
    marks = ",".join("?" * len(tokens))
    rows = db.execute(f"""SELECT t.* FROM {table} t JOIN (SELECT token, MAX(receive_ns) m FROM {table}
                          WHERE token IN ({marks}) AND receive_ns <= ? GROUP BY token) x
                          ON t.token = x.token AND t.receive_ns = x.m ORDER BY t.seq""", (*tokens, as_of)).fetchall()
    return {r["token"]: r for r in rows}


def quote_from_rows(tok: int, d, t) -> Quote:
    """A recorded depth row + the latest tick row (or None) at or before the same time -> Quote."""
    side = lambda p: tuple((d[f"{p}{i}_price"], d[f"{p}{i}_qty"], d[f"{p}{i}_orders"])  # noqa: E731
                           for i in LEVELS if d[f"{p}{i}_price"] and d[f"{p}{i}_qty"])
    return Quote(tok, side("b"), side("s"), True, t["ltp"] if t else None, t["volume"] if t else None,
                 t["oi"] if t else None, d["exchange_ts"] * S if d["exchange_ts"] else None, d["receive_ns"],
                 "kite.ws.full (recorded buffer.sqlite: depth + ticks)")


def quotes_at(db, tokens: list[int], as_of: int) -> dict[int, Quote]:
    depth, ticks = _latest(db, "depth", tokens, as_of), _latest(db, "ticks", tokens, as_of)
    return {tok: quote_from_rows(tok, d, ticks.get(tok)) for tok, d in depth.items()}


def spot_at(db, token: int, as_of: int) -> Quote | None:
    t = _latest(db, "ticks", [token], as_of).get(token)
    return None if t is None else Quote(token, (), (), False, t["ltp"], t["volume"], None,
                                        t["exchange_ts"] * S if t["exchange_ts"] else None, t["receive_ns"],
                                        "kite.ws.quote (recorded buffer.sqlite: ticks)")


def run(cfg, day: date, n: int) -> list[dict]:
    day_dir = cfg.root / day.isoformat()
    reg = Registry(cfg)
    buf = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
    buf.row_factory = sqlite3.Row
    spots = {m.underlying: m.spot_token for m in reg.get_universe(day).members}
    out = []
    for s, ev in pick_setups(day_dir, n):
        setup = TradeSetup(s["id"], s["underlying"], s["direction"], day, ev["as_of"], s["token"], ev["price"],
                           ev["structural_stop"], (ev["obstacle"][2],), ev["atr"])
        contracts = reg.get_contracts(s["underlying"], day)
        tradable = {c.token: reg.is_tradable(c.token, day) for c in contracts}
        tokens = [c.token for c in contracts]
        quotes = quotes_at(buf, tokens, setup.as_of)
        opt_tokens = [c.token for c in contracts if c.instrument_type in ("CE", "PE")]
        n_opt_ticks = buf.execute(f"SELECT COUNT(*) FROM ticks WHERE token IN ({','.join('?' * len(opt_tokens))})",
                                  opt_tokens).fetchone()[0] if opt_tokens else 0
        spot = spot_at(buf, spots[s["underlying"]], setup.as_of) if s["underlying"] in spots else None
        sel = select_contracts(setup, contracts, tradable, quotes, spot, {}, {}, cfg)
        state = PortfolioState(setup.as_of, day, 0.0, 0.0, 0.0, (), 0.0, 0, 0, None)
        decisions = [risk_check(c, state, cfg) for c in sel.candidates]
        out.append(dict(setup=s, evaluation_reason=ev["reason"], family=s["family"], selection=sel, decisions=decisions,
                        option_tick_rows=n_opt_ticks, spot=spot))
    buf.close()
    reg.close()
    return out


def _r(paise) -> str:
    return "—" if paise is None else f"{paise / 100:,.2f}"


def _n(x, fmt="{:,.2f}") -> str:
    return "—" if x is None else fmt.format(x)


def report(cfg, day: date, results: list[dict]) -> str:
    L = [f"# Phase 7 candidate tables, {day} (config {cfg.version}, sha256 {cfg.sha256[:8]})", "",
         "Prices in INR. Quantities in units. Every row is a recorded input at the setup's decision time (no look-ahead).",
         "Portfolio state: flat. Margins: none fetched => futures capital is MARGIN_ESTIMATED (full notional, config).", ""]
    for r in results:
        s, sel = r["setup"], r["selection"]
        t = datetime.fromtimestamp(sel.setup.as_of / S, IST)
        L += [f"## {s['underlying']} · {s['family']} {s['source_type']} · {'LONG' if s['direction'] > 0 else 'SHORT'} · "
              f"decision {t:%H:%M} IST", "",
              f"Setup `{s['id']}` (Phase 6 first TIMELY, {r['evaluation_reason']}): entry {_r(sel.setup.entry)}, structural stop "
              f"{_r(sel.setup.stop)}, target 1 {_r(sel.setup.targets[0])} (on the near-month future), ATR {_r(sel.setup.atr)}. "
              f"Spot: {_r(r['spot'].last_price) if r['spot'] else 'none'}. Option tick rows recorded for this underlying: "
              f"{r['option_tick_rows']}.", "", f"**Selector decision: {sel.decision}**", ""]
        L += [f"- note: {x}" for x in sel.notes] + ([""] if sel.notes else [])
        L += ["| # | contract | expiry | dte | lot | lots / qty | bid / ask | entry | spread % | spread / move % | top qty b/a "
              "| 5-lvl depth b/a | vol (lots) | OI (lots) | stop → contract | T1 → contract | capital (method) | planned risk "
              "| full premium / gap risk | costs stop / T1 | net R:R | liquidity | status | exclusions | risk | risk reasons |",
              "|" + "---|" * 26]
        for i, (c, d) in enumerate(zip(sel.candidates, r["decisions"]), 1):
            vol = None if c.volume_day is None else c.volume_day / c.lot_size
            oi = None if c.oi is None else c.oi / c.lot_size
            L.append("| " + " | ".join([
                str(i), f"{c.tradingsymbol} ({c.kind} {c.side})", str(c.expiry), str(c.dte), str(c.lot_size),
                "—" if c.lots is None else f"{c.lots} / {c.quantity}", f"{_r(c.bid)} / {_r(c.ask)}", _r(c.entry),
                _n(c.spread_pct, "{:.3f}"), _n(c.spread_vs_move_pct, "{:.1f}"),
                "—" if c.top_bid_qty is None else f"{c.top_bid_qty} / {c.top_ask_qty}",
                "—" if c.depth_bid_qty is None else f"{c.depth_bid_qty} / {c.depth_ask_qty}",
                _n(vol, "{:,.0f}"), _n(oi, "{:,.0f}"), _r(c.stop), _r(c.targets[0]) if c.targets else "—",
                "—" if c.required_capital_inr is None else f"{c.required_capital_inr:,.0f} ({c.capital_method})",
                _n(c.planned_risk_inr, "{:,.0f}"),
                _n(c.full_premium_at_risk_inr if c.kind != "FUT" else c.gap_risk_inr, "{:,.0f}"),
                "—" if c.costs_at_stop is None else f"{c.costs_at_stop.total_inr:,.2f} / {c.costs_at_target.total_inr:,.2f} "
                                                    f"({c.costs_at_stop.status})",
                _n(c.rr_net), _n(c.liquidity_score), c.status, "; ".join(c.reasons) or "—", d.status,
                "<br>".join(d.reasons) or "—"]).replace("\n", " ") + " |")
        L.append("")
    counts = {}
    for r in results:
        for c, d in zip(r["selection"].candidates, r["decisions"]):
            counts[(c.kind if c.kind == "FUT" else "OPT", c.status, d.status)] = counts.get(
                (c.kind if c.kind == "FUT" else "OPT", c.status, d.status), 0) + 1
    L += ["## Totals", "", "| product | selector status | risk | candidates |", "|---|---|---|---|"]
    L += [f"| {k[0]} | {k[1]} | {k[2]} | {v} |" for k, v in sorted(counts.items())]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("date")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    cfg, day = load(), date.fromisoformat(a.date)
    results = run(cfg, day, a.n)
    text = report(cfg, day, results)
    if a.report:
        a.report.write_text(text)
    if a.json:
        a.json.write_text(json.dumps([{k: jsonable(v) for k, v in r.items()} for r in results], indent=1, default=str))
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
