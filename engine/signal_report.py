"""Phase 8 edge: run the signal engine on a recorded day, store recommendations / lifecycle / observations, replay-check.

  python3 -m engine.signal_report YYYY-MM-DD [...] [--report PATH] [--dry-run] [--config config/engine/v10.yaml]

Inputs, all recorded and as of each decision time (no look-ahead):
- Phase 4 states/events, Phase 5 detections, Phase 6 setups/evaluations: recomputed for the date (pure, as engine.opportunity).
- quotes: recorded depth + tick rows in `buffer.sqlite` (read-only) with receive_ns <= as_of; one scan per underlying.
- registry rows and is_tradable: Phase 2 `universe.sqlite`. Option 1m bars: none (the V1 empirical model is unused).
- Phase 11 (v14): option context (Black-76 analytics, chain snapshots, ATM IV percentile vs earlier `options.sqlite` days)
  from recorded option quotes at each decision time (engine.chain_report.context_at), and the event calendar stored
  at or before the decision time (engine.events.status_at). No recorded option => options factor UNAVAILABLE.
- margins: none (Q-RISK-1). Portfolio: flat at every decision (no paper ledger before Phase 11, Q-RISK-4).

Store `<date>/signals.sqlite`: append-only (INSERT OR IGNORE on natural keys + config version). Each recommendation keeps
its `SignalInputs` (zlib + pickle, written and read only by this engine) so that `replay_check` regenerates it.
"""

import argparse
import json
import pickle
import sqlite3
import sys
import zlib
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from . import signals as G
from .candles import IST, MIN, S, _ns
from .contract_report import quote_from_rows
from .contracts import Quote
from .opportunity import CADENCE_PATH, Context, load_cadence, run_setups, setups_from_positioning, setups_from_structure
from .positioning import history_reader, run_day
from .profile import add_profile
from .risk import PortfolioState
from .snapshots import jsonable
from .structure import bar_of, evaluate_day as structure_day, load_day, near_candles
from .universe import Registry


def _dump(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)


# ---------------------------------------------------------------- store
def write(day_dir: Path, results: dict, observations: list, cfg, horizon_ns: int | None = None) -> int:
    """results: {setup_id: (Lifecycle | None, [(SignalRecommendation, SignalInputs)])}.
    horizon_ns (live runs on a growing day): rows timed after the last received packet are not stored. With data ending
    mid-session, Phase 6 still expires retest plans at their deadline, which a later full-day run may contradict; append-only
    storage would keep the wrong row (Phase 15 prefix check)."""
    ok = lambda ns: horizon_ns is None or ns <= horizon_ns  # noqa: E731
    db = sqlite3.connect(Path(day_dir) / "signals.sqlite")
    try:
        db.executescript(
            "CREATE TABLE IF NOT EXISTS recommendations (recommendation_id TEXT, config_version TEXT, signal_id TEXT, "
            "as_of INTEGER, underlying TEXT, family TEXT, classification TEXT, status TEXT, score REAL, payload TEXT, "
            "inputs BLOB, PRIMARY KEY (recommendation_id, config_version));"
            "CREATE TABLE IF NOT EXISTS lifecycle (signal_id TEXT, seq INTEGER, config_version TEXT, ts INTEGER, "
            "from_state TEXT, to_state TEXT, cause TEXT, PRIMARY KEY (signal_id, seq, config_version));"
            "CREATE TABLE IF NOT EXISTS observations (underlying TEXT, ts INTEGER, label TEXT, setup_id TEXT, "
            "config_version TEXT, payload TEXT, PRIMARY KEY (underlying, ts, label, setup_id, config_version));"
            "CREATE TABLE IF NOT EXISTS runs (config_version TEXT PRIMARY KEY, signals INTEGER, recommendations INTEGER, "
            "observations INTEGER);")
        n, v = db.total_changes, cfg.version
        db.executemany("INSERT OR IGNORE INTO recommendations VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
            (r.recommendation_id, v, r.signal_id, r.as_of, r.underlying, r.setup_family, r.classification, r.status,
             r.score.headline.points, _dump(G.payload(r)), zlib.compress(pickle.dumps(inp)))
            for _, recs in results.values() for r, inp in recs if ok(r.as_of)])
        db.executemany("INSERT OR IGNORE INTO lifecycle VALUES (?,?,?,?,?,?,?)", [
            (t.signal_id, t.seq, v, t.ts, t.from_state, t.to_state, t.cause)
            for lc, _ in results.values() if lc for t in lc.rows if ok(t.ts)])
        db.executemany("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)", [
            (o.underlying, o.ts, o.label, o.setup_id or "", v, _dump(jsonable(o))) for o in observations if ok(o.ts)])
        # same transaction: the day counts as done for this config version only when everything above is stored
        db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?)", (v, sum(lc is not None for lc, _ in results.values()),
                                                                   sum(len(r) for _, r in results.values()), len(observations)))
        db.commit()
        return db.total_changes - n
    finally:
        db.close()


def read(day_dir: Path, version: str) -> dict:
    db = sqlite3.connect(f"file:{Path(day_dir) / 'signals.sqlite'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        q = lambda sql: [dict(r) for r in db.execute(sql, (version,))]  # noqa: E731
        return {"recommendations": q("SELECT * FROM recommendations WHERE config_version=? ORDER BY as_of, recommendation_id"),
                "lifecycle": q("SELECT * FROM lifecycle WHERE config_version=? ORDER BY signal_id, seq"),
                "observations": q("SELECT * FROM observations WHERE config_version=? ORDER BY ts, underlying")}
    finally:
        db.close()


def replay_check(day_dir: Path, cfg) -> dict:
    """Regenerate every stored recommendation from its stored inputs and compare with the stored object."""
    diff, n = [], 0
    for row in read(day_dir, cfg.version)["recommendations"]:
        n += 1
        again = _dump(G.payload(G.recommend(pickle.loads(zlib.decompress(row["inputs"])), cfg)))
        if again != row["payload"]:
            diff.append(row["recommendation_id"])
    return {"checked": n, "identical": n - len(diff), "different": diff}


# ---------------------------------------------------------------- recorded quotes (read-only, one scan per underlying)
class QuoteBook:
    def __init__(self, buf: sqlite3.Connection):
        self.buf, self.rows = buf, {}

    def load(self, tokens) -> None:
        need = [t for t in tokens if t not in self.rows]
        for t in need:
            self.rows[t] = {"depth": [], "ticks": []}
        if not need:
            return
        marks = ",".join("?" * len(need))
        for table in ("depth", "ticks"):
            for r in self.buf.execute(f"SELECT * FROM {table} WHERE token IN ({marks}) ORDER BY receive_ns, seq", need):
                self.rows[r["token"]][table].append(r)
        for t in need:
            for table in ("depth", "ticks"):
                self.rows[t][f"{table}_ns"] = [r["receive_ns"] for r in self.rows[t][table]]

    @staticmethod
    def _at(rows, keys, as_of):
        i = bisect_right(keys, as_of)
        return rows[i - 1] if i else None

    def quotes(self, tokens, as_of: int) -> dict:
        out = {}
        for t in tokens:
            v = self.rows[t]
            d = self._at(v["depth"], v["depth_ns"], as_of)
            if d is not None:
                out[t] = quote_from_rows(t, d, self._at(v["ticks"], v["ticks_ns"], as_of))
        return out

    def spot(self, token: int, as_of: int):
        v = self.rows[token]
        t = self._at(v["ticks"], v["ticks_ns"], as_of)
        return None if t is None else Quote(
            token, (), (), False, t["ltp"], t["volume"], None, t["exchange_ts"] * S if t["exchange_ts"] else None,
            t["receive_ns"], "kite.ws.quote (recorded buffer.sqlite: ticks)")


# ---------------------------------------------------------------- one recorded day
def run_date(cfg, d: str, hist, cadence) -> tuple[dict, list, dict]:
    day_dir = cfg.root / d
    day, master, rows = load_day(cfg, day_dir)
    near = near_candles(rows, master, day, cfg)
    dets = add_profile(structure_day(near, hist(day), cfg, day), near, master, rows, day_dir, cfg, day)
    states, events = run_day(cfg, day_dir, hist(day), cadence)
    pst = defaultdict(dict)
    for st in states:
        pst[st.underlying][st.ts_ns] = st
    ctx = {u: Context(u, tok, dets.get(u, []), cs["1m"], pst.get(u)) for u, (tok, cs) in near.items()}
    setups = [x for u, (tok, cs) in sorted(near.items()) for x in setups_from_structure(dets.get(u, []), cs, ctx[u].atr_at, cfg)]
    setups += setups_from_positioning(events, {u: cs["1m"] for u, (_, cs) in near.items()},
                                      lambda u, m, t: ctx[u].atr_at(m, t), cfg)
    evals, _ = run_setups(setups, ctx, day, cfg)

    fw, n_hist = cfg.get("positioning.feature_window_min"), cfg.get("signals.families.persistence_windows")
    idx = cfg.get("positioning.beta.index_underlying")
    usable = {u: {b.end: (b.c, b.vwap) for b in map(bar_of, cs["1m"]) if b.ok and b.vwap is not None}
              for u, (_, cs) in near.items()}
    markets = {}

    def market(t):
        if t not in markets:
            pts = tuple(m[t] for m in usable.values() if t in m)
            markets[t] = G.market_context(t, tuple(dets.get(idx, [])), pst.get(idx, {}).get(t), pts, cfg)
        return markets[t]

    def evidence_at(s, t):
        p = pst.get(s.underlying, {})
        hist_ = tuple((t - (n_hist - 1 - k) * fw * MIN, p.get(t - (n_hist - 1 - k) * fw * MIN)) for k in range(n_hist))
        return G.Evidence(t, p.get(t), hist_, tuple(x for x in dets.get(s.underlying, []) if x.confirmed_ts <= t), market(t))

    reg = Registry(cfg)
    buf = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
    buf.row_factory = sqlite3.Row
    book, spots, per_und = QuoteBook(buf), {m.underlying: m.spot_token for m in reg.get_universe(day).members}, {}

    recorded = {r[0] for r in buf.execute("SELECT DISTINCT token FROM depth")}
    phase11 = "options" in cfg.values
    ev_status, hists, chains = {}, {}, {}

    def option_inputs(s, as_of):
        if not phase11:
            return None, None
        from .chain_report import context_at, iv_history
        from .events import status_at
        if s.underlying not in chains:
            all_cs = reg.get_contracts(s.underlying, day)
            futs = sorted((c for c in all_cs if c.instrument_type == "FUT" and c.expiry >= day), key=lambda c: c.expiry)
            use = futs + [c for c in all_cs if c.instrument_type in ("CE", "PE") and c.token in recorded]
            book.load([c.token for c in use])
            chains[s.underlying] = (use, futs[0] if futs else None)
            hists[s.underlying] = iv_history(cfg.root, s.underlying, day, cfg.version)
        use, near = chains[s.underlying]
        if as_of not in ev_status:
            ev_status[as_of] = status_at(cfg.root, as_of, cfg)
        if near is None or len(use) == 1:
            return None, ev_status[as_of]
        return context_at(s.underlying, use, near, book, as_of, s.confirmed_ts, hists[s.underlying], day, cfg), ev_status[as_of]

    def inputs_at(s, ev, x):
        kind = "CE" if s.direction > 0 else "PE"
        if (s.underlying, kind) not in per_und:
            cs = tuple(c for c in reg.get_contracts(s.underlying, day) if c.instrument_type in ("FUT", kind))
            per_und[(s.underlying, kind)] = (cs, {c.token: reg.is_tradable(c.token, day) for c in cs})
        cs, trad = per_und[(s.underlying, kind)]
        trad = {**trad, s.token: trad.get(s.token) or reg.is_tradable(s.token, day)}
        sp = spots.get(s.underlying)
        book.load([c.token for c in cs] + ([sp] if sp else []))
        flat = PortfolioState(ev.as_of, day, 0.0, 0.0, 0.0, (), 0.0, 0, 0, None)
        opt, evs = option_inputs(s, ev.as_of)
        return G.SignalInputs(s, ev, x, cs, trad, book.quotes([c.token for c in cs], ev.as_of),
                              book.spot(sp, ev.as_of) if sp else None, {}, {}, flat, opt, evs)

    close = _ns(day, cfg.get("sessions.fno.close"))
    results, obs = {}, []
    try:
        for s in setups:
            results[s.id] = G.drive(s, evals[s.id], evidence_at, inputs_at, close, cfg)
            ob = next((o for o in (G.exhaustion_observation(s, e, cfg) for e in evals[s.id] if e.state == "ACTIVE") if o), None)
            if ob:
                obs.append(ob)
    finally:
        buf.close()
        reg.close()
    w, n_acc = cfg.get("signals.accumulation.window_min"), cfg.get("signals.accumulation.windows")
    open_ = _ns(day, cfg.get("sessions.fno.open"))
    for u, p in sorted(pst.items()):
        for t in sorted(p):
            if (t - open_) % (w * MIN) == 0:
                h = tuple((t - (n_acc - 1 - k) * w * MIN, p.get(t - (n_acc - 1 - k) * w * MIN)) for k in range(n_acc))
                ob = G.accumulation(u, h, dets.get(u, []), t, cfg)
                if ob:
                    obs.append(ob)
    info = {"setups": len(setups), "phase4_events": len(events), "positioning_states": len(states),
            "option_bars": "none (V1 empirical premium model unused)",
            "option_tokens_recorded": sum(1 for u, (use, _) in chains.items() for c in use if c.instrument_type in ("CE", "PE"))}
    return results, obs, info


# ---------------------------------------------------------------- report
def _t(ns) -> str:
    return datetime.fromtimestamp(ns / S, IST).strftime("%H:%M")


def summarize(results: dict, obs: list) -> dict:
    recs = [r for _, rr in results.values() for r, _ in rr]
    lcs = [lc for lc, _ in results.values() if lc]
    fail = Counter(g for r in recs if r.status == G.REJECTED for g in r.reasons)
    top = sorted((r for r in recs if r.status == G.REJECTED), key=lambda r: (-r.score.headline.points, r.as_of))[:10]
    return {
        "lifecycles": len(lcs), "recommendations": len(recs),
        "recommendations_by_family_status": {f"{f} {s}": n for (f, s), n in sorted(Counter((r.setup_family, r.status) for r in recs).items())},
        "classification": dict(sorted(Counter(r.classification for r in recs).items())),
        "lifecycle_final_state": dict(sorted(Counter(lc.state for lc in lcs).items())),
        "lifecycle_transitions": dict(sorted(Counter(f"{t.from_state}->{t.to_state}" for lc in lcs for t in lc.rows).items())),
        "observations": dict(sorted(Counter(o.label for o in obs).items())),
        "failed_gates_on_rejected": dict(fail.most_common()),
        "bands": dict(sorted(Counter(r.score.headline.band for r in recs).items())),
        "top_rejected": [{"recommendation_id": r.recommendation_id, "underlying": r.underlying, "time": _t(r.as_of),
                          "family": f"{r.setup_family} {r.classification}", "direction": r.direction,
                          "score": r.score.headline.summary, "contract": r.contract if isinstance(r.contract, str) else
                          r.contract.reason, "failed": [f"{g.name}: {g.detail}" for g in r.gates if not g.passed]} for r in top],
    }


def report(cfg, out: dict) -> str:
    L = ["# Phase 8 signal report", "",
         f"Generated by `python3 -m engine.signal_report` (config {cfg.version}, sha256 {cfg.sha256[:8]}). Scores are research "
         "priorities out of 100, **not probabilities**. Portfolio flat, no margin quotes, no option data (see the module docstring).", ""]
    for d, r in sorted(out.items()):
        L += [f"## {d}", "", "```json", json.dumps(r, indent=1, default=str), "```", ""]
    return "\n".join(L) + "\n"


def data_horizon(day_dir: Path) -> int | None:
    """Receive time of the last recorded tick or depth packet of the day (live runs cut their output here)."""
    db = sqlite3.connect(f"file:{Path(day_dir) / 'buffer.sqlite'}?mode=ro", uri=True)
    try:
        return max((db.execute(f"SELECT max(receive_ns) FROM {t}").fetchone()[0] or 0 for t in ("ticks", "depth")),
                   default=0) or None
    finally:
        db.close()


def process(cfg, d: str, hist, cadence, dry_run=False, live=False) -> dict:
    horizon = data_horizon(cfg.root / d) if live else None   # read before the run: rows arriving during it are not used
    results, obs, info = run_date(cfg, d, hist, cadence)
    written = 0 if dry_run else write(cfg.root / d, results, obs, cfg, horizon)
    rc = None if dry_run else replay_check(cfg.root / d, cfg)
    return {"date": d, **info, "rows_written": written, "replay_check": rc, **summarize(results, obs)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.signal_report")
    ap.add_argument("dates", nargs="+")
    ap.add_argument("--config", default=str(G.DEFAULT_CONFIG))
    ap.add_argument("--cadence", default=str(CADENCE_PATH))
    ap.add_argument("--report", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="do not write <date>/signals.sqlite")
    ap.add_argument("--live", action="store_true", help="growing day (intraday job): store nothing after the last packet")
    a = ap.parse_args(argv)
    cfg = G.load(a.config)
    cadence, hist, out = load_cadence(cfg, a.cadence), history_reader(cfg), {}
    for d in a.dates:
        out[d] = process(cfg, d, hist, cadence, a.dry_run, a.live)
        print(json.dumps({k: out[d][k] for k in ("date", "setups", "lifecycles", "recommendations", "rows_written",
                                                  "replay_check")}, default=str))
    if a.report:
        a.report.write_text(report(cfg, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
