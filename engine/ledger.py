"""Phase 9 ledgers (edge): SIMULATED and ACTUAL trades, fills, monitor decisions, in-app alerts, lifecycle, feedback.

  python3 -m engine.ledger run [DATE ...] [--report PATH]           paper trading over recorded sessions (all if none given)
  python3 -m engine.ledger take DATE RECOMMENDATION_ID --price P --qty Q --time ISO   an actual trade you took
  python3 -m engine.ledger skip RECOMMENDATION_ID --reason TEXT
  python3 -m engine.ledger exit TRADE_ID --price P --qty Q --time ISO
  python3 -m engine.ledger feedback --ledger ACTUAL --rec ID [--trade ID] --taken yes|no ... --behaved yes|no|partly
  python3 -m engine.ledger show SIMULATED|ACTUAL

Store: `<storage.root>/<paper.ledger_file>` (SQLite, WAL), a new file; never journal.db. Append-only: INSERT (OR IGNORE
on natural keys); no UPDATE or DELETE. The two ledgers are separate tables (`sim_*`, `actual_*`); shared tables
(`monitor_decisions`, `alerts`, `lifecycle`, `feedback`) carry a `ledger` column and every read filters on it. No query
reads both ledgers (tests/engine_tests/test_paper.py scans every SQL string here). Prices are paise; P&L is INR.
Feedback is stored only: nothing here changes a weight, threshold or config file.
"""

import argparse
import json
import pickle
import sqlite3
import sys
import time
import zlib
from bisect import bisect_right
from datetime import date, datetime
from pathlib import Path

from . import paper as P
from . import signals as G
from .candles import IST, S, Unavailable
from .contracts import OPTION_KINDS
from .costs import round_trip
from .risk import PortfolioState
from .snapshots import jsonable

TRADE_COLS = ("id", "recommendation_id", "signal_id", "day", "underlying", "family", "direction", "price_token",
              "contract_token", "kind", "side", "qty", "lot_size", "entry_price", "entry_ns", "underlying_entry",
              "underlying_stop", "contract_stop", "t1", "t1_contract", "config_version")
_T = ", ".join(TRADE_COLS)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sim_trades ({_T}, label TEXT, PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS actual_trades ({_T}, label TEXT, recorded_ns INTEGER, PRIMARY KEY (id));
CREATE TABLE IF NOT EXISTS sim_fills (trade_id TEXT, ns INTEGER, role TEXT, side TEXT, qty_requested INTEGER,
  qty_filled INTEGER, avg_price REAL, mid REAL, slippage_per_unit REAL, method TEXT, partial INTEGER, quote TEXT,
  label TEXT, PRIMARY KEY (trade_id, ns, role));
CREATE TABLE IF NOT EXISTS sim_no_fills (ref TEXT, ns INTEGER, role TEXT, side TEXT, qty INTEGER, reason TEXT,
  label TEXT, PRIMARY KEY (ref, ns, role));
CREATE TABLE IF NOT EXISTS actual_fills (trade_id TEXT, ns INTEGER, role TEXT, side TEXT, qty INTEGER, price REAL,
  recorded_ns INTEGER, label TEXT, PRIMARY KEY (trade_id, ns, role));
CREATE TABLE IF NOT EXISTS actual_skips (recommendation_id TEXT, reason TEXT, recorded_ns INTEGER, label TEXT,
  PRIMARY KEY (recommendation_id, recorded_ns));
CREATE TABLE IF NOT EXISTS monitor_decisions (ledger TEXT, trade_id TEXT, as_of INTEGER, seq INTEGER, decision TEXT,
  rule_id TEXT, stop INTEGER, pnl_gross_inr REAL, pnl_net_inr REAL, pnl_unavailable TEXT, observations TEXT,
  warnings TEXT, config_version TEXT, PRIMARY KEY (ledger, trade_id, as_of, seq));
CREATE TABLE IF NOT EXISTS alerts (ledger TEXT, trade_id TEXT, as_of INTEGER, seq INTEGER, decision TEXT,
  previous TEXT, rule_id TEXT, observations TEXT, message TEXT, channel TEXT, config_version TEXT,
  PRIMARY KEY (ledger, trade_id, as_of, seq));
CREATE TABLE IF NOT EXISTS lifecycle (ledger TEXT, trade_id TEXT, signal_id TEXT, ts INTEGER, from_state TEXT,
  to_state TEXT, cause TEXT, PRIMARY KEY (ledger, trade_id, ts, to_state));
CREATE TABLE IF NOT EXISTS feedback (ledger TEXT, trade_id TEXT, recommendation_id TEXT, taken INTEGER,
  skip_reason TEXT, actual_entry REAL, actual_exit REAL, slippage REAL, execution_quality TEXT,
  behaved_as_expected TEXT, notes TEXT, recorded_ns INTEGER, PRIMARY KEY (ledger, recommendation_id, recorded_ns));
CREATE TABLE IF NOT EXISTS runs (day TEXT, config_version TEXT, sim_opened INTEGER, sim_not_opened INTEGER,
  actual_monitored INTEGER, PRIMARY KEY (day, config_version));
"""

# one query per ledger: never a statement over both (no f-strings, so the test can read every one)
Q_TRADES = {P.SIMULATED: "SELECT * FROM sim_trades ORDER BY entry_ns, id",
            P.ACTUAL: "SELECT * FROM actual_trades ORDER BY entry_ns, id"}
Q_EXITS = {P.SIMULATED: "SELECT trade_id, ns, qty_filled AS qty, avg_price AS price FROM sim_fills WHERE role='EXIT' ORDER BY ns",
           P.ACTUAL: "SELECT trade_id, ns, qty, price FROM actual_fills WHERE role='EXIT' ORDER BY ns"}
Q_DECISIONS = "SELECT * FROM monitor_decisions WHERE ledger=? ORDER BY as_of, trade_id, seq"
Q_ALERTS = "SELECT * FROM alerts WHERE ledger=? ORDER BY as_of, trade_id, seq"
Q_FEEDBACK = "SELECT * FROM feedback WHERE ledger=? ORDER BY recorded_ns"
Q_LIFECYCLE = "SELECT * FROM lifecycle WHERE ledger=? ORDER BY trade_id, ts"


def _ledger(x) -> str:
    if x not in P.LEDGERS:
        raise ValueError(f"ledger must be one of {P.LEDGERS}, not {x!r}")
    return x


def _j(x) -> str:
    return json.dumps(jsonable(x), sort_keys=True, separators=(",", ":"), default=str)


def path_of(cfg) -> Path:
    return cfg.root / cfg.get("paper.ledger_file")


def open_ledger(path: Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def _trade_row(t: P.Trade) -> tuple:
    return tuple(str(t.day) if c == "day" else getattr(t, c) for c in TRADE_COLS)


# ---------------------------------------------------------------- writes
def add_sim_trade(db, t: P.Trade, entry: P.PaperFill) -> None:
    if t.ledger != P.SIMULATED:
        raise ValueError("add_sim_trade takes SIMULATED trades only")
    db.execute("INSERT OR IGNORE INTO sim_trades VALUES (" + ",".join("?" * (len(TRADE_COLS) + 1)) + ")",
               _trade_row(t) + (P.SIMULATED,))
    _sim_fill(db, t.id, "ENTRY", entry)
    db.commit()


def _sim_fill(db, trade_id: str, role: str, f: P.PaperFill) -> None:
    db.execute("INSERT OR IGNORE INTO sim_fills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (trade_id, f.as_of, role, f.side, f.qty_requested, f.qty_filled, f.avg_price, f.mid,
                f.slippage_per_unit, f.method, int(f.partial), _j(f.quote), P.SIMULATED))


def sim_not_opened(db, recommendation_id: str, ns: int, side: str, qty: int, reason: str) -> None:
    db.execute("INSERT OR IGNORE INTO sim_no_fills VALUES (?,?,?,?,?,?,?)",
               (recommendation_id, ns, "ENTRY", side, qty, reason, P.SIMULATED))
    db.commit()


def record_taken(db, t: P.Trade, fill_price: float, qty: int, filled_ns: int, recorded_ns: int) -> None:
    """The user took a recommendation: their own fill price (paise), quantity (units) and time."""
    if t.ledger != P.ACTUAL:
        raise ValueError("record_taken takes ACTUAL trades only")
    t = P.Trade(**{**t.__dict__, "entry_price": float(fill_price), "qty": int(qty), "entry_ns": int(filled_ns)})
    db.execute("INSERT INTO actual_trades VALUES (" + ",".join("?" * (len(TRADE_COLS) + 2)) + ")",
               _trade_row(t) + (P.ACTUAL, recorded_ns))
    db.execute("INSERT INTO actual_fills VALUES (?,?,?,?,?,?,?,?)",
               (t.id, filled_ns, "ENTRY", t.side, qty, fill_price, recorded_ns, P.ACTUAL))
    db.commit()


def record_skipped(db, recommendation_id: str, reason: str, recorded_ns: int) -> None:
    db.execute("INSERT INTO actual_skips VALUES (?,?,?,?)", (recommendation_id, reason, recorded_ns, P.ACTUAL))
    db.commit()


def record_exit(db, trade_id: str, price: float, qty: int, filled_ns: int, recorded_ns: int) -> None:
    row = db.execute("SELECT side FROM actual_trades WHERE id=?", (trade_id,)).fetchone()
    if row is None:
        raise ValueError(f"no ACTUAL trade {trade_id}")
    db.execute("INSERT INTO actual_fills VALUES (?,?,?,?,?,?,?,?)",
               (trade_id, filled_ns, "EXIT", "SELL" if row["side"] == "BUY" else "BUY", qty, price, recorded_ns, P.ACTUAL))
    db.commit()


def record_feedback(db, fb: P.Feedback, recorded_ns: int) -> None:
    db.execute("INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (fb.ledger, fb.trade_id, fb.recommendation_id, int(fb.taken), fb.skip_reason, fb.actual_entry,
                fb.actual_exit, fb.slippage, fb.execution_quality, fb.behaved_as_expected, fb.notes, recorded_ns))
    db.commit()


class InAppSink:
    """The in-app channel (phase text: 'in-app for now'): alerts are rows the dashboard reads."""
    def __init__(self, db):
        self.db, self.seq = db, {}

    def send(self, a: P.Alert) -> None:
        k = (a.ledger, a.trade_id, a.as_of)
        self.seq[k] = self.seq.get(k, -1) + 1
        self.db.execute("INSERT OR IGNORE INTO alerts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (a.ledger, a.trade_id, a.as_of, self.seq[k], a.decision, a.previous, a.rule_id,
                         _j(a.observations), a.message, "in_app", a.config_version))


def store_result(db, res: P.Result) -> None:
    seq = {}
    for d in res.decisions:
        k = (d.ledger, d.trade_id, d.as_of)
        seq[k] = seq.get(k, -1) + 1
        un = "; ".join(x.reason for x in (d.pnl_gross_inr, d.pnl_net_inr) if isinstance(x, Unavailable)) or None
        num = lambda x: None if isinstance(x, Unavailable) else x  # noqa: E731
        db.execute("INSERT OR IGNORE INTO monitor_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (d.ledger, d.trade_id, d.as_of, seq[k], d.decision, d.rule_id, d.stop, num(d.pnl_gross_inr),
                    num(d.pnl_net_inr), un, _j(d.observations), _j(d.warnings), d.config_version))
    P.deliver(res.alerts, InAppSink(db))
    for f in res.fills:
        _sim_fill(db, f.trade_id, "EXIT", f)
    for n in res.no_fills:
        db.execute("INSERT OR IGNORE INTO sim_no_fills VALUES (?,?,?,?,?,?,?)",
                   (n.trade_id, n.as_of, "EXIT", n.side, n.qty, n.reason, P.SIMULATED))
    for r in res.lifecycle:
        db.execute("INSERT OR IGNORE INTO lifecycle VALUES (?,?,?,?,?,?,?)",
                   (r.ledger, r.trade_id, r.signal_id, r.ts, r.from_state, r.to_state, r.cause))
    db.commit()


# ---------------------------------------------------------------- reads (one ledger at a time)
def _rows(db, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in db.execute(sql, args)]


def trades(db, ledger) -> list[dict]:
    return _rows(db, Q_TRADES[_ledger(ledger)])


def decisions(db, ledger) -> list[dict]:
    return _rows(db, Q_DECISIONS, (_ledger(ledger),))


def alerts(db, ledger) -> list[dict]:
    return _rows(db, Q_ALERTS, (_ledger(ledger),))


def feedback(db, ledger) -> list[dict]:
    return _rows(db, Q_FEEDBACK, (_ledger(ledger),))


def lifecycle(db, ledger) -> list[dict]:
    return _rows(db, Q_LIFECYCLE, (_ledger(ledger),))


def _closed(db, ledger) -> dict:
    """{trade_id: (exit qty, last exit ns, realized gross INR)} from the ledger's own exit fills."""
    ts = {t["id"]: t for t in trades(db, ledger)}
    out = {}
    for f in _rows(db, Q_EXITS[ledger]):
        t = ts[f["trade_id"]]
        q, _, g = out.get(f["trade_id"], (0, 0, 0.0))
        sgn = 1 if t["side"] == "BUY" else -1
        out[f["trade_id"]] = (q + f["qty"], f["ns"], g + sgn * (f["price"] - t["entry_price"]) * f["qty"] / 100)
    return out


def summary(db, ledger) -> dict:
    """Counts and realized gross for ONE ledger. There is no combined summary (phase text)."""
    _ledger(ledger)
    ts, cl = trades(db, ledger), _closed(db, ledger)
    closed = [t for t in ts if cl.get(t["id"], (0,))[0] >= t["qty"]]
    return {"ledger": ledger, "label": ledger, "trades": len(ts), "closed": len(closed), "open": len(ts) - len(closed),
            "realized_gross_inr": round(sum(cl.get(t["id"], (0, 0, 0.0))[2] for t in closed), 2)}


def portfolio_state(db, ledger, day: date, as_of: int, cfg) -> PortfolioState | Unavailable:
    """One ledger's PortfolioState at as_of, from its own rows only (Q-9-2: each ledger is checked on its own)."""
    _ledger(ledger)
    ts = [t for t in trades(db, ledger) if t["day"] == str(day) and t["entry_ns"] <= as_of]
    exits = [f for f in _rows(db, Q_EXITS[ledger]) if f["ns"] <= as_of]
    last = {}
    for d in decisions(db, ledger):
        if d["as_of"] <= as_of:
            last[d["trade_id"]] = d
    realized, unreal, results, open_, cap = 0.0, 0.0, [], [], 0.0
    for t in ts:
        mine = [f for f in exits if f["trade_id"] == t["id"]]
        q = sum(f["qty"] for f in mine)
        sgn, prod = (1 if t["side"] == "BUY" else -1), ("OPT" if t["kind"] in OPTION_KINDS else "FUT")
        r = sum(sgn * (f["price"] - t["entry_price"]) * f["qty"] / 100 - round_trip(
            cfg, prod, t["side"], t["entry_price"] / 100, f["price"] / 100, f["qty"], day).total_inr for f in mine)
        realized += r
        if q >= t["qty"]:
            results.append((max(f["ns"] for f in mine), r))
            continue
        d = last.get(t["id"])
        if d is None or d["pnl_net_inr"] is None:
            return Unavailable(f"open {ledger} trade {t['id']} has no net P&L at {as_of}")
        unreal += d["pnl_net_inr"]
        open_.append(t["underlying"])
        notional = t["entry_price"] * t["qty"] / 100
        cap += notional if t["kind"] in OPTION_KINDS else notional * cfg.get("contracts.futures_margin.fraction")
    losses, last_loss = 0, None
    for ns, r in sorted(results):
        losses, last_loss = (losses + 1, ns) if r < 0 else (0, last_loss)
    # shortcut: worst_day_pnl = the current day P&L, not an intraday latch; replay the decisions if the latch must bind
    return PortfolioState(as_of, day, realized, unreal, realized + unreal, tuple(open_), cap, len(ts), losses, last_loss)


# ---------------------------------------------------------------- recommendation → trade
def _v(x):
    return None if isinstance(x, dict) and "UNAVAILABLE" in x else x


def trade_from_payload(p: dict, ledger: str, tid: str, entry_price: float, qty: int, entry_ns: int, version: str) -> P.Trade:
    return P.Trade(tid, ledger, p["recommendation_id"], p["signal_id"], p["underlying"], p["setup_family"],
                   1 if p["direction"] == "LONG" else -1, datetime.fromtimestamp(p["as_of"] / S, IST).date(),
                   p["price_token"], _v(p["token"]), _v(p["instrument_type"]), _v(p["side"]), int(qty),
                   _v(p["lot_size"]), float(entry_price), int(entry_ns), _v(p["entry_trigger"]),
                   _v(p["underlying_invalidation"]), _v(p["contract_stop_estimate"]), _v(p["t1"]), _v(p["t1_contract"]),
                   version)


# ---------------------------------------------------------------- replay over recorded sessions (edge)
class _Inputs:
    """inputs_at(trade_id, ns) from the day's stored Phase 6 evaluations, Phase 5 swings / VWAP and Phase 8 recommendations."""
    NO_POSITIONING = Unavailable("POSITIONING_UNAVAILABLE: Phase 4 states are not persisted (Q-4-6); OI windows disabled (Q-6-5)")

    def __init__(self, day_dir: Path, trades_: list, recs: list, opp_version: str, str_version: str):
        self.by_trade = {}
        o = sqlite3.connect(f"file:{day_dir / 'opportunity.sqlite'}?mode=ro", uri=True)
        s = sqlite3.connect(f"file:{day_dir / 'structure.sqlite'}?mode=ro", uri=True)
        try:
            for t in trades_:
                ev = [json.loads(r[0]) for r in o.execute(
                    "SELECT payload FROM evaluations WHERE setup_id=? AND config_version=? ORDER BY as_of",
                    (t.signal_id, opp_version))]
                dets = [json.loads(r[0]) for r in s.execute(
                    "SELECT payload FROM structure_detections WHERE underlying=? AND config_version=? AND "
                    "type IN ('SWING_LOW','SWING_HIGH','VWAP') ORDER BY confirmed_ts", (t.underlying, str_version))]
                tf = json.loads(o.execute("SELECT payload FROM setups WHERE id=? AND config_version=?",
                                          (t.signal_id, opp_version)).fetchone()[0])["timeframe"]
                opp = [(r["as_of"], r["recommendation_id"]) for r in recs if r["underlying"] == t.underlying
                       and json.loads(r["payload"])["direction"] != ("LONG" if t.direction > 0 else "SHORT")
                       and r["status"] == G.ENTRY_ELIGIBLE]
                self.by_trade[t.id] = (t, ev, [e["as_of"] for e in ev], dets, tf, opp)
        finally:
            o.close()
            s.close()

    def __call__(self, tid: str, ns: int) -> P.ReviewInputs:
        t, ev, keys, dets, tf, opp = self.by_trade[tid]
        i = bisect_right(keys, ns)
        if not i:
            u = Unavailable("NO_EVALUATION: no Phase 6 evaluation at or before the review")
            return P.ReviewInputs(ns, u, u, u, (), self.NO_POSITIONING, u, (), ())
        e = ev[i - 1]
        price = _v(e["price"])
        close = Unavailable("Phase 6 price UNAVAILABLE") if price is None else P.Obs(
            "close_1m", t.price_token, price, e["price_ts"], e["price_receive_ns"], "Phase 6 evaluation (opportunity.sqlite)")
        vw = [d for d in dets if d["type"] == "VWAP" and d["timeframe"] == f"{tf}m" and d["confirmed_ts"] <= ns]
        swings = tuple((d["type"], d["timeframe"], d["level"], d["confirmed_ts"], d["id"]) for d in dets
                       if d["type"] != "VWAP" and d["confirmed_ts"] <= ns)
        return P.ReviewInputs(ns, e["state"], close, e["classification"], tuple(e["exhaustion_flags"]), self.NO_POSITIONING,
                              vw[-1]["level"] if vw else Unavailable(f"INSUFFICIENT_DATA: no {tf}m VWAP"), swings,
                              tuple(rid for a, rid in opp if a <= ns))


def run_day(cfg, sig_cfg, day_dir: Path, db) -> dict:
    """Open SIMULATED trades for the day's ENTRY_ELIGIBLE recommendations (risk_check on both ledgers, fill on the recorded
    quote at decision time), then monitor them and the day's ACTUAL trades over the recorded stream."""
    from .signal_report import QuoteBook, read
    d = day_dir.name
    out = {"day": d, "eligible": 0, "opened": [], "not_opened": [], "actual": []}
    if not (day_dir / "signals.sqlite").exists():
        out["skipped"] = "no signals.sqlite (Phase 8 not run for this date)"
        return out
    recs = read(day_dir, sig_cfg.version)["recommendations"]
    eligible = [r for r in recs if r["status"] == G.ENTRY_ELIGIBLE]
    out["eligible"] = len(eligible)
    day = date.fromisoformat(d)
    opened = []
    buf = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True) if eligible else None
    if buf:
        buf.row_factory = sqlite3.Row
    qb = QuoteBook(buf) if buf else None
    for r in eligible:
        rec = G.recommend(pickle.loads(zlib.decompress(r["inputs"])), sig_cfg)
        c, p = rec.approval.candidate, json.loads(r["payload"])
        pair = P.risk_both(c, portfolio_state(db, P.SIMULATED, day, rec.as_of, cfg),
                           portfolio_state(db, P.ACTUAL, day, rec.as_of, cfg), sig_cfg)
        if not pair.approved:
            why = "; ".join(pair.simulated.reasons + pair.actual.reasons)
            sim_not_opened(db, rec.recommendation_id, rec.as_of, c.side, c.quantity, f"RISK_REJECTED: {why}")
            out["not_opened"].append((rec.recommendation_id, why))
            continue
        qb.load([c.token])
        f = P.paper_fill(c.side, c.quantity, c.lot_size, qb.quotes([c.token], rec.as_of).get(c.token), rec.as_of, cfg)
        if isinstance(f, Unavailable):
            sim_not_opened(db, rec.recommendation_id, rec.as_of, c.side, c.quantity, f.reason)
            out["not_opened"].append((rec.recommendation_id, f.reason))
            continue
        t = trade_from_payload(p, P.SIMULATED, f"SIM:{rec.recommendation_id}:{cfg.version}", f.avg_price, f.qty_filled,
                               rec.as_of, cfg.version)
        add_sim_trade(db, t, f)
        opened.append(t)
        out["opened"].append(t.id)
    actual = [trade_from_row(x) for x in trades(db, P.ACTUAL) if x["day"] == d]
    out["actual"] = [t.id for t in actual]
    if buf:
        buf.close()
    for group in (opened, actual):                  # one ledger per run: their day P&L never mixes
        if not group:
            continue
        toks = {t.price_token for t in group} | {t.contract_token for t in group}
        ev = day_events(day_dir, toks, min(t.entry_ns for t in group))
        inp = _Inputs(day_dir, group, recs, cfg_opp_version(day_dir), cfg_str_version(day_dir))
        res = P.run_trades(group, ev, inp, cfg, {group[0].ledger: 0.0})
        store_result(db, res)
    db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?)", (d, cfg.version, len(opened), len(out["not_opened"]),
                                                                 len(actual)))
    db.commit()
    return out


def day_events(day_dir: Path, tokens, start_ns: int) -> list:
    """The recorded stream for `tokens` (+ gaps and connection events) from start_ns, in arrival order. Reads only the
    matching rows: the whole buffer does not fit in memory on the 8 GB host (Q-6-5)."""
    from .store import DEPTH_COLS, EVENT_COLS, GAP_COLS, TICK_COLS, arrival_key, conn_event, depth_event, gap_event, tick_event
    db = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
    toks, marks = sorted(tokens), ",".join("?" * len(tokens))
    try:
        ev = [tick_event(r) for r in db.execute(
            f"SELECT {','.join(TICK_COLS)} FROM ticks WHERE token IN ({marks}) AND receive_ns >= ?", (*toks, start_ns))]
        ev += [depth_event(r) for r in db.execute(
            f"SELECT {','.join(DEPTH_COLS)} FROM depth WHERE token IN ({marks}) AND receive_ns >= ?", (*toks, start_ns))]
        ev += [conn_event(r) for r in db.execute(f"SELECT {','.join(EVENT_COLS)} FROM events WHERE receive_ns >= ?", (start_ns,))]
        ev += [gap_event(r) for r in db.execute(f"SELECT {','.join(GAP_COLS)} FROM gaps WHERE end_ns >= ?", (start_ns,))]
    finally:
        db.close()
    return sorted(ev, key=arrival_key)


def trade_from_row(x: dict) -> P.Trade:
    return P.Trade(**{c: (date.fromisoformat(x[c]) if c == "day" else x[c]) for c in TRADE_COLS}, ledger=P.ACTUAL)


def _latest_version(path: Path, table: str) -> str:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return max((r[0] for r in db.execute(f"SELECT DISTINCT config_version FROM {table}")), key=lambda v: int(v.lstrip("v")))
    finally:
        db.close()


def cfg_opp_version(day_dir: Path) -> str:
    return _latest_version(day_dir / "opportunity.sqlite", "runs")


def cfg_str_version(day_dir: Path) -> str:
    return _latest_version(day_dir / "structure.sqlite", "structure_detections")


# ---------------------------------------------------------------- CLI
def _ns_of(iso: str) -> int:
    t = datetime.fromisoformat(iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=IST)
    return int(t.timestamp() * S)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m engine.ledger", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("dates", nargs="*")
    r.add_argument("--report")
    tk = sub.add_parser("take")
    tk.add_argument("date"), tk.add_argument("rec"), tk.add_argument("--price", type=float, required=True)
    tk.add_argument("--qty", type=int, required=True), tk.add_argument("--time", required=True)
    sk = sub.add_parser("skip")
    sk.add_argument("rec"), sk.add_argument("--reason", required=True)
    ex = sub.add_parser("exit")
    ex.add_argument("trade"), ex.add_argument("--price", type=float, required=True)
    ex.add_argument("--qty", type=int, required=True), ex.add_argument("--time", required=True)
    fb = sub.add_parser("feedback")
    fb.add_argument("--ledger", required=True, choices=P.LEDGERS), fb.add_argument("--rec", required=True)
    fb.add_argument("--trade"), fb.add_argument("--taken", required=True, choices=("yes", "no"))
    fb.add_argument("--skip-reason"), fb.add_argument("--entry", type=float), fb.add_argument("--exit", type=float)
    fb.add_argument("--slippage", type=float), fb.add_argument("--quality"), fb.add_argument("--behaved", choices=P.BEHAVED)
    fb.add_argument("--notes", default="")
    sh = sub.add_parser("show")
    sh.add_argument("ledger", choices=P.LEDGERS)
    a = ap.parse_args(argv)
    cfg, now = P.load(), time.time_ns()       # edge: the wall clock stamps when the user recorded something
    db = open_ledger(path_of(cfg))
    try:
        if a.cmd == "run":
            sig_cfg = G.load()
            days = a.dates or sorted(p.name for p in cfg.root.iterdir() if p.is_dir() and p.name[:4].isdigit())
            out = [run_day(cfg, sig_cfg, cfg.root / d, db) for d in days]
            text = json.dumps({"config_version": cfg.version, "days": out,
                               "summary": {k: summary(db, k) for k in P.LEDGERS}}, indent=1, default=str)
            Path(a.report).write_text(text) if a.report else print(text)
        elif a.cmd == "take":
            row = sqlite3.connect(f"file:{cfg.root / a.date / 'signals.sqlite'}?mode=ro", uri=True).execute(
                "SELECT payload FROM recommendations WHERE recommendation_id=?", (a.rec,)).fetchone()
            if row is None:
                raise SystemExit(f"no recommendation {a.rec} on {a.date}")
            t = trade_from_payload(json.loads(row[0]), P.ACTUAL, f"ACT:{a.rec}:{now}", a.price, a.qty, _ns_of(a.time),
                                   cfg.version)
            record_taken(db, t, a.price, a.qty, _ns_of(a.time), now)
            print(f"ACTUAL trade {t.id} recorded")
        elif a.cmd == "skip":
            record_skipped(db, a.rec, a.reason, now)
        elif a.cmd == "exit":
            record_exit(db, a.trade, a.price, a.qty, _ns_of(a.time), now)
        elif a.cmd == "feedback":
            record_feedback(db, P.Feedback(a.ledger, a.trade, a.rec, a.taken == "yes", a.skip_reason, a.entry, a.exit,
                                           a.slippage, a.quality, a.behaved, a.notes), now)
        elif a.cmd == "show":
            print(json.dumps({"summary": summary(db, a.ledger), "trades": trades(db, a.ledger)}, indent=1, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
