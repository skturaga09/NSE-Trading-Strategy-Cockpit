"""Phase 11 edge: option-chain snapshots from a recorded day, the IV history store, and the OptionContext builder.

  python3 -m engine.chain_report YYYY-MM-DD [--config config/engine/v14.yaml] [--dry-run]

Reads `<date>/buffer.sqlite` (recorded depth + ticks, read-only) with receive_ns <= each snapshot time (no look-ahead) and
the Phase 2 registry. Every `options.snapshot_interval_min` from the F&O open to the close, per underlying with recorded
options and per expiry: engine.options analytics at t and at t - change_window_min -> ChainSnapshot.

Underlying reference = the near-month future's mid (a two-sided recorded book), for ATM and for the underlying move.
OI comes from tick rows with their own receive time (OI age), never from a later row.

Store `<date>/options.sqlite` (INSERT OR IGNORE per config version, rule Q-8-20): `chain_snapshots`, `iv_history`
(one ATM IV per underlying per session: the last snapshot of the day that has one; Q-11-13), `runs`.
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from . import options as O
from .candles import MIN, _ns
from .contracts import OPTION_KINDS, quote_problem
from .snapshots import jsonable
from .universe import Registry


def _mid(q, as_of, cfg):
    return None if q is None or quote_problem(q, as_of, cfg.get("quality.stale_depth_s")) else (q.bids[0][0] + q.asks[0][0]) / 2


def oi_at(book, tokens, as_of: int) -> dict:
    """{token: (oi, receive_ns)} from the latest recorded tick row at or before as_of (QuoteBook rows)."""
    out = {}
    for t in tokens:
        v = book.rows.get(t)
        r = None if v is None else book._at(v["ticks"], v["ticks_ns"], as_of)
        if r is not None and r["oi"] is not None:
            out[t] = (r["oi"], r["receive_ns"])
    return out


def analytics_at(contracts, futs_by_expiry: dict, book, as_of: int, cfg) -> dict:
    opts = [c for c in contracts if c.instrument_type in OPTION_KINDS]
    q = book.quotes([c.token for c in opts] + [f.token for f in futs_by_expiry.values()], as_of)
    return {c.token: O.analyze(c, q.get(c.token), q.get(futs_by_expiry[c.expiry].token) if c.expiry in futs_by_expiry else None,
                               c.expiry in futs_by_expiry, as_of, cfg) for c in opts}


def snapshots_at(und: str, contracts, near_fut, book, as_of: int, cfg) -> tuple:
    """ChainSnapshot per expiry that has recorded options (nearest first)."""
    ref_t = as_of - cfg.get("options.change_window_min") * MIN
    futs = {c.expiry: c for c in contracts if c.instrument_type == "FUT"}
    opts = [c for c in contracts if c.instrument_type in OPTION_KINDS and c.token in book.rows and book.rows[c.token]["depth"]]
    if not opts:
        return (), {}
    now, ref = analytics_at(opts, futs, book, as_of, cfg), analytics_at(opts, futs, book, ref_t, cfg)
    toks = [c.token for c in opts]
    qn = book.quotes(toks, as_of)
    fq = book.quotes([near_fut.token], as_of).get(near_fut.token), book.quotes([near_fut.token], ref_t).get(near_fut.token)
    un, ur = _mid(fq[0], as_of, cfg), _mid(fq[1], ref_t, cfg)
    un = O.Unavailable("NEAR_FUTURE_NO_VALID_BOOK") if un is None else un
    ur = O.Unavailable("NEAR_FUTURE_NO_VALID_BOOK at the reference time") if ur is None else ur
    oin, oir = oi_at(book, toks, as_of), oi_at(book, toks, ref_t)
    vol = {t: q.volume_day for t, q in qn.items() if q.volume_day is not None}
    dep = {t: (sum(lv[1] for lv in q.bids), sum(lv[1] for lv in q.asks)) for t, q in qn.items()}
    snaps = []
    for e in sorted({c.expiry for c in opts}):
        cs = [c for c in opts if c.expiry == e]
        snaps.append(O.chain_snapshot(und, e, cs, now, ref, oin, oir, vol, dep, un, ur, as_of, cfg))
    return tuple(snaps), now


def iv_history(root: Path, und: str, before: date, version: str) -> list:
    out = []
    for d in sorted(p for p in Path(root).iterdir() if p.is_dir() and len(p.name) == 10 and p.name < before.isoformat()):
        f = d / "options.sqlite"
        if f.exists():
            with sqlite3.connect(f"file:{f}?mode=ro", uri=True) as db:
                r = db.execute("SELECT atm_iv FROM iv_history WHERE underlying=? AND config_version=?", (und, version)).fetchone()
            if r:
                out.append((date.fromisoformat(d.name), r[0]))
    return out


def context_at(und: str, contracts, near_fut, book, as_of: int, ref_ns: int | None, hist: list, day: date, cfg) -> O.OptionContext:
    """Selector V2 / options-factor input at a decision time; ref_ns = the setup's confirmation (Opportunity Age)."""
    snaps, now = snapshots_at(und, contracts, near_fut, book, as_of, cfg)
    futs = {c.expiry: c for c in contracts if c.instrument_type == "FUT"}
    ref = {} if ref_ns is None or not now else analytics_at([c for c in contracts if c.token in now], futs, book, ref_ns, cfg)
    iv = O.atm_iv(snaps[0] if snaps else None)
    return O.OptionContext(und, as_of, now, snaps, iv, O.iv_percentile(iv, hist, day, cfg), ref)


def run_date(cfg, d: str) -> tuple[list, list, dict]:
    from .signal_report import QuoteBook
    day, day_dir = date.fromisoformat(d), cfg.root / d
    reg = Registry(cfg)
    buf = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
    buf.row_factory = sqlite3.Row
    recorded = {r[0] for r in buf.execute("SELECT DISTINCT token FROM depth")}
    book, rows, hist_rows = QuoteBook(buf), [], []
    o, c = _ns(day, cfg.get("sessions.fno.open")), _ns(day, cfg.get("sessions.fno.close"))
    step = cfg.get("options.snapshot_interval_min") * MIN
    info = defaultdict(int)
    try:
        for m in sorted(reg.get_universe(day).members, key=lambda m: m.underlying):
            cs = reg.get_contracts(m.underlying, day)
            opts = [x for x in cs if x.instrument_type in OPTION_KINDS and x.token in recorded]
            futs = sorted((x for x in cs if x.instrument_type == "FUT" and x.expiry >= day), key=lambda x: x.expiry)
            if not opts or not futs:
                continue
            info["option_tokens_recorded"] += len(opts)
            use = futs + opts
            book.load([x.token for x in use])
            last_iv = None
            for t in range(o + step, c + 1, step):
                snaps, _ = snapshots_at(m.underlying, use, futs[0], book, t, cfg)
                for s in snaps:
                    rows.append((m.underlying, s.expiry.isoformat(), t, cfg.version, json.dumps(jsonable(s), default=str)))
                    info["snapshots"] += 1
                    info["rows"] += len(s.rows)
                    info["rows_with_iv"] += s.iv_coverage[0]
                iv = O.atm_iv(snaps[0] if snaps else None)
                if not O._u(iv):
                    last_iv = (t, snaps[0].expiry.isoformat(), iv)
            info["underlyings"] += 1
            if last_iv:
                hist_rows.append((m.underlying, d, last_iv[0], last_iv[1], last_iv[2], cfg.version))
    finally:
        buf.close()
        reg.close()
    return rows, hist_rows, dict(info)


def write(day_dir: Path, rows, hist_rows, info, version: str) -> None:
    db = sqlite3.connect(Path(day_dir) / "options.sqlite")
    try:
        db.executescript(
            "CREATE TABLE IF NOT EXISTS chain_snapshots (underlying TEXT, expiry TEXT, as_of INTEGER, config_version TEXT, "
            "payload TEXT, PRIMARY KEY (underlying, expiry, as_of, config_version));"
            "CREATE TABLE IF NOT EXISTS iv_history (underlying TEXT, day TEXT, as_of INTEGER, expiry TEXT, atm_iv REAL, "
            "config_version TEXT, PRIMARY KEY (underlying, day, config_version));"
            "CREATE TABLE IF NOT EXISTS runs (config_version TEXT PRIMARY KEY, info TEXT);")
        db.executemany("INSERT OR IGNORE INTO chain_snapshots VALUES (?,?,?,?,?)", rows)
        db.executemany("INSERT OR IGNORE INTO iv_history VALUES (?,?,?,?,?,?)", hist_rows)
        db.execute("INSERT OR IGNORE INTO runs VALUES (?,?)", (version, json.dumps(info)))
        db.commit()
    finally:
        db.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.chain_report")
    ap.add_argument("date")
    ap.add_argument("--config", default=str(O.DEFAULT_CONFIG))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    cfg = O.load(a.config)
    rows, hist_rows, info = run_date(cfg, a.date)
    if not a.dry_run:
        write(cfg.root / a.date, rows, hist_rows, info, cfg.version)
    print(json.dumps({"date": a.date, "config_version": cfg.version, **info, "iv_history_rows": len(hist_rows)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
