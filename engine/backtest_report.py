"""Phase 12 edge: run the backtests and studies, write results, the half-life file and the report tables.

  python3 -m engine.backtest_report [all|historical|recorded] [--config config/engine/v16.yaml] [--no-walk-forward]
                                    [--pipeline-check DATE]

SIMULATED / HYPOTHETICAL. Advisory and paper-trading only: no order is placed, modified or cancelled anywhere.

RECORDED (recorded sessions, Phase 1+): GOOD sessions only (engine.backtest.session_quality). Trades come from the live
Phase 9 code path: `engine.ledger.run_day` (Phase 8 recommendations re-derived from their stored inputs, Phase 7
risk_check on the SIMULATED ledger, the Phase 9 paper broker on the recorded quote, the Phase 9 monitor over the recorded
stream) into a separate backtest ledger file, never `ledger.sqlite`. A day whose buffer was deleted after compaction is
rebuilt from its Parquet files (local, or the retention archive) with the Phase 1 replay readers. Costs: the Phase 7 model
with the rates in force on the trade date. The holdout is read only at FINAL, once, and every read is logged.

HISTORICAL_CANDLES (owner D-55): the NIFTY 50 index 5m / 15m lab files (no volume, no OI), Phase 5 Detector and Phase 6
setups / track unchanged, price-path event study only: no fills, no costs, no rupees.
"""

import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from . import backtest as B
from . import ledger as L
from . import paper as P
from . import profile as PR
from . import signals as G
from .candles import IST, MIN, S, Unavailable, _ns
from .config import REPO, load_config
from .contracts import OPTION_KINDS
from .costs import round_trip
from .opportunity import Setup
from .retention import DAY
from .store import DEPTH_COLS, EVENT_COLS, GAP_COLS, TICK_COLS, _ddl
from .structure import bar_of

DEFAULT_CONFIG = REPO / "config" / "engine" / "v16.yaml"
HIST, REC = "HISTORICAL_CANDLES", "RECORDED"
ANCHORS = ("FIRST_DETECTION", "CONFIRMATION", "FIRST_EXECUTABLE")


def overlay(cfg, patch: dict, tag: str):
    """A derived config (never written to disk) whose version names what changed, e.g. 'v16:HIST(...)'."""
    vals = copy.deepcopy(dict(cfg.values))
    for k, v in patch.items():
        cur = vals
        *ps, last = k.split(".")
        for p in ps:
            cur = cur[p]
        cur[last] = v
    return replace(cfg, version=f"{cfg.version}:{tag}", values=vals)


# ---------------------------------------------------------------- HISTORICAL_CANDLES
def load_lab(cfg) -> tuple[dict, list, list]:
    """{'5m'|'15m': {date: [payload]}}, usable days, excluded (day, reason). Files must match the configured sha256."""
    h = cfg.get("backtest.historical")
    base, data = Path(h["dataset_dir"]).expanduser(), {}
    for iv, fn in h["files"].items():
        raw = (base / fn).read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if sha != h["sha256"][iv]:
            raise SystemExit(f"{fn}: sha256 {sha} != config {h['sha256'][iv]}; dataset changed, not used")
        days = defaultdict(list)
        for line in raw.decode().splitlines()[1:]:
            ts, o, hi, lo, c = line.split(",")
            t = datetime.fromisoformat(ts)
            days[t.date()].append(B.index_payload(int(t.timestamp()) * S, int(iv[:-1]), float(o), float(hi), float(lo),
                                                  float(c), f"LAB_CSV:{fn}"))
        data[iv] = days
    ok, bad = [], []
    for d in sorted(set().union(*(set(v) for v in data.values()))):
        o, c = _ns(d, cfg.get("sessions.cash.open")), _ns(d, cfg.get("sessions.cash.close"))
        why = [f"{iv}: {len(data[iv].get(d, []))} bars != {n}" for iv, n in h["bars_per_day"].items()
               if len(data[iv].get(d, [])) != n]
        why += [f"{iv}: bar outside {cfg.get('sessions.cash.open')}-{cfg.get('sessions.cash.close')}"
                for iv in data if any(p["start_ns"] < o or p["end_ns"] > c for p in data[iv].get(d, []))]
        (bad.append((str(d), "; ".join(why))) if why else ok.append(d))
    return data, ok, bad


def hist_config(cfg, patch=None):
    p = {"sessions.fno": dict(cfg.get("sessions.cash")), "structure.timeframes_min": cfg.get("backtest.historical.timeframes_min")}
    tag = "HIST(cash session, index 5m/15m)" + "".join(f",{k.split('.')[-1]}={v}" for k, v in (patch or {}).items())
    return overlay(cfg, {**p, **(patch or {})}, tag)


def run_historical(cfg, data, days, progress=False) -> dict:
    """Event rows (3 anchors per setup), age entries, class entries over the usable days. cfg = hist_config(...)."""
    h, n_later = cfg.get("backtest.historical"), cfg.get("backtest.multi_session_days")
    und, src, vtf = h["underlying"], f"LAB_CSV:{h['files']['5m']}", cfg.get("signals.market.trend_timeframe_min")
    rows_of = {d: B.history_rows(data["5m"][d]) for d in days}
    bars5 = {d: [bar_of(p) for p in data["5m"][d]] for d in days}
    events, ages, classes, n_setups = [], [], [], Counter()
    for i, d in enumerate(days):
        prior = [r for pd in days[max(0, i - 30):i] for r in rows_of[pd]]
        hd = B.historical_day(und, d, {"5m": data["5m"][d], "15m": data["15m"][d]}, prior, cfg, src)
        close, cut = _ns(d, cfg.get("sessions.fno.close")), _ns(d, cfg.get("monitor.squareoff_cutoff"))
        nxt = days[i + 1:i + 1 + n_later]
        path = bars5[d] + [b for nd in nxt for b in bars5[nd]]
        later_end = _ns(nxt[-1], cfg.get("sessions.fno.close")) if nxt else close
        atr_at = lambda tf, t, a=hd.atr: B.atr_lookup(a, tf, t)  # noqa: E731
        for s in hd.setups:
            n_setups[s.source_type] += 1
            evs, tgt = hd.evals[s.id], hd.targets[s.id]
            lab = {"dataset": HIST, "family": s.source_type, "regime": B.regime(hd.dets, s.confirmed_ts, vtf),
                   "tod": B.tod_bucket(s.confirmed_ts, cfg), "expiry": "UNAVAILABLE: no expiry calendar for the index dataset",
                   "vix": "UNAVAILABLE: India VIX not in the dataset (Q-12-11)", "score_band": B.NOT_REPRESENTABLE,
                   "instrument": f"{und} index"}
            for name, a in B.first_executable(s, evs, close).items():
                events.append(B.outcome(s, name, a, tgt, path, 5, atr_at, cut, close, later_end, cfg, **lab))
            ages += B.age_entries(s, tgt, bars5[d], cut, cfg)
            classes += B.class_entries(s, evs, tgt, bars5[d], cut)
        if progress and i % 100 == 0:
            print(f"  {cfg.version} {d} ({i + 1}/{len(days)})", file=sys.stderr, flush=True)
    return {"events": events, "ages": ages, "classes": classes, "setups": dict(n_setups)}


# ---------------------------------------------------------------- RECORDED: sessions, rehydration, trades
def recorded_days(root: Path) -> list[Path]:
    return [p for p in sorted(Path(root).iterdir()) if DAY.match(p.name) and p.is_dir()
            and ((p / "buffer.sqlite").exists() or (p / "parquet" / "events").exists())] if Path(root).exists() else []


def control_rows(day_dir: Path) -> tuple[list, list]:
    """(events (receive_ns, conn, kind), gaps (start_ns, end_ns)) from the buffer, else from the derived Parquet."""
    if (day_dir / "buffer.sqlite").exists():
        db = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
        try:
            return (db.execute("SELECT receive_ns, conn, kind FROM events").fetchall(),
                    db.execute("SELECT start_ns, end_ns FROM gaps").fetchall())
        finally:
            db.close()
    import pyarrow.parquet as pq
    rd = lambda t, cols: [r for f in sorted((day_dir / "parquet" / t).rglob("*.parquet"))  # noqa: E731
                          for r in zip(*(pq.read_table(f, columns=cols).to_pydict()[c] for c in cols))]
    return rd("events", ["receive_ns", "conn", "kind"]), rd("gaps", ["start_ns", "end_ns"])


def raw_dir(day_dir: Path, cfg) -> Path:
    """Where the day's raw Parquet ticks are: locally, or in the retention archive (local / mounted path targets only)."""
    if any((day_dir / "parquet" / "ticks").rglob("*.parquet")):
        return day_dir
    return Path(cfg.get("retention.archive_target")).expanduser() / day_dir.name


def last_packet_ns(day_dir: Path, cfg) -> int | None:
    if (day_dir / "buffer.sqlite").exists():
        db = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
        try:
            return db.execute("SELECT max(receive_ns) FROM ticks").fetchone()[0]
        finally:
            db.close()
    import pyarrow.parquet as pq
    best = None
    for f in (raw_dir(day_dir, cfg) / "parquet" / "ticks").rglob("*.parquet"):
        md = pq.ParquetFile(f).metadata                    # footer statistics only
        i = md.schema.to_arrow_schema().get_field_index("receive_ns")
        for g in range(md.num_row_groups):
            st = md.row_group(g).column(i).statistics
            if st is not None and st.has_min_max:
                best = st.max if best is None else max(best, st.max)
    return best


def rehydrate(day_dir: Path, cfg, out_dir: Path) -> Path:
    """A buffer.sqlite (ticks, depth, events, gaps) rebuilt from the day's Parquet with the Phase 1 replay readers, plus
    links to the derived stores, in out_dir. Streams one record batch at a time (8 GB host)."""
    import pyarrow.parquet as pq
    from .replay import PARQUET_EVENT_TABLES, iter_parquet_file_events
    out_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out_dir / "buffer.sqlite")
    for name, cols in (("ticks", TICK_COLS), ("depth", DEPTH_COLS), ("events", EVENT_COLS), ("gaps", GAP_COLS)):
        db.execute(_ddl(name, cols))
    raw = raw_dir(day_dir, cfg)
    for table, fields, kind in PARQUET_EVENT_TABLES:
        batch = []
        for f in sorted((raw / "parquet" / table).rglob("*.parquet")):
            for e in iter_parquet_file_events(f, fields, kind):
                batch.append((e.receive_ns, e.conn, e.seq, e.token, e.exchange_ts) + tuple(v for _, v in e.data))
                if len(batch) >= 50_000:
                    db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(batch[0]))})", batch)
                    batch = []
        if batch:
            db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(batch[0]))})", batch)
    for table, cols in (("events", EVENT_COLS), ("gaps", GAP_COLS)):
        for f in sorted((day_dir / "parquet" / table).rglob("*.parquet")):
            t = pq.read_table(f).to_pydict()
            db.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(cols))})", list(zip(*(t[c] for c in cols))))
    db.commit()
    db.close()
    for name in ("signals.sqlite", "opportunity.sqlite", "structure.sqlite", "instruments.csv.gz"):
        if (day_dir / name).exists():
            (out_dir / name).symlink_to((day_dir / name).resolve())
    return out_dir


def trade_rows(db, cfg, recs: dict) -> list[dict]:
    """SIMULATED trades of a backtest ledger -> rows with gross / cost / net INR, slippage INR and net R (Phase 7 costs in
    force on the trade date). recs: recommendation_id -> {score, classification} for segmentation."""
    exits = defaultdict(list)
    for f in db.execute("SELECT trade_id, ns, qty_filled, avg_price, slippage_per_unit, partial FROM sim_fills "
                        "WHERE role='EXIT' ORDER BY ns"):
        exits[f[0]].append(f)
    entry = {r[0]: r for r in db.execute("SELECT trade_id, slippage_per_unit, partial FROM sim_fills WHERE role='ENTRY'")}
    rules = {r[0]: r[1] for r in db.execute("SELECT trade_id, rule_id FROM monitor_decisions WHERE ledger='SIMULATED' "
                                            "AND decision='EXIT_REQUIRED' ORDER BY as_of")}
    out = []
    for t in L.trades(db, P.SIMULATED):
        ex = exits.get(t["id"], [])
        q = sum(f[2] for f in ex)
        sgn, prod = (1 if t["side"] == "BUY" else -1), ("OPT" if t["kind"] in OPTION_KINDS else "FUT")
        day = date.fromisoformat(t["day"])
        row = {"dataset": REC, "trade_id": t["id"], "day": t["day"], "family": t["family"], "underlying": t["underlying"],
               "instrument": t["kind"], "entry_ns": t["entry_ns"], "qty": t["qty"], "exit_rule": rules.get(t["id"]),
               "partial_entry": bool(entry.get(t["id"], (0, 0, 0))[2]), "tod": B.tod_bucket(t["entry_ns"], cfg),
               **recs.get(t["recommendation_id"], {})}
        if q < t["qty"]:
            out.append({**row, "unavailable": f"OPEN_OR_UNFILLED: {q} of {t['qty']} exited"})
            continue
        gross = sum(sgn * (f[3] - t["entry_price"]) * f[2] / 100 for f in ex)
        cost = [round_trip(cfg, prod, t["side"], t["entry_price"] / 100, f[3] / 100, f[2], day) for f in ex]
        slip = (entry.get(t["id"], (0, 0))[1] or 0) * t["qty"] / 100 + sum((f[4] or 0) * f[2] / 100 for f in ex)
        risk = abs(t["entry_price"] - t["contract_stop"]) * t["qty"] / 100 if t["contract_stop"] is not None else None
        net = gross - sum(c.total_inr for c in cost)
        out.append({**row, "gross_inr": round(gross, 2), "cost_inr": round(sum(c.total_inr for c in cost), 2),
                    "cost_unverified": any(c.unverified for c in cost), "net_inr": round(net, 2),
                    "slippage_inr": round(slip, 2), "r": round(net / risk, 6) if risk else None})
    return out


def _payload_obj(d: dict):
    return {k: (Unavailable(v["UNAVAILABLE"]) if isinstance(v, dict) and set(v) == {"UNAVAILABLE"} else v)
            for k, v in d.items() if k != "type"}


def recorded_events(day_dir: Path, cfg) -> dict:
    """Phase 6 setups / evaluations stored for the day + its 1m bars -> event rows, age and class entries (same pure code
    as HISTORICAL_CANDLES, at 1m resolution)."""
    from .positioning import contracts
    from .structure import load_day, near_candles
    day = date.fromisoformat(day_dir.name)
    o = sqlite3.connect(f"file:{day_dir / 'opportunity.sqlite'}?mode=ro", uri=True)
    st = sqlite3.connect(f"file:{day_dir / 'structure.sqlite'}?mode=ro", uri=True)
    try:
        ov, sv = L.cfg_opp_version(day_dir), L.cfg_str_version(day_dir)
        setups = [Setup(**_payload_obj(json.loads(r[0]))) for r in o.execute(
            "SELECT payload FROM setups WHERE config_version=? ORDER BY id", (ov,))]
        evs = defaultdict(list)
        for sid, p in o.execute("SELECT setup_id, payload FROM evaluations WHERE config_version=? ORDER BY as_of", (ov,)):
            evs[sid].append(json.loads(p))
        vw = defaultdict(list)
        for u, p in st.execute("SELECT underlying, payload FROM structure_detections WHERE config_version=? AND type='VWAP' "
                               "ORDER BY confirmed_ts", (sv,)):
            x = json.loads(p)
            vw[(u, x["timeframe"])].append((x["confirmed_ts"], x["attrs"]["atr"]))
    finally:
        o.close()
        st.close()
    fam = {}
    if (day_dir / "signals.sqlite").exists():
        sg = sqlite3.connect(f"file:{day_dir / 'signals.sqlite'}?mode=ro", uri=True)
        fam = dict(sg.execute("SELECT signal_id, family FROM recommendations"))
        sg.close()
    _, master, rows = load_day(cfg, day_dir)
    near = {u: (c.near_expiry if c else None) for u in {s.underlying for s in setups} for c in [contracts(master, u, (), day)]}
    nc = near_candles(rows, master, day, cfg)
    bars = {u: sorted(map(bar_of, cs["1m"]), key=lambda b: b.start) for u, (tok, cs) in nc.items()}
    close, cut = _ns(day, cfg.get("sessions.fno.close")), _ns(day, cfg.get("monitor.squareoff_cutoff"))
    prof = PR.add_profile({}, nc, master, rows, day_dir, cfg, day)  # {} before v17

    def parts(s, a):                    # Phase 13 score-part values at the anchor (Q-13-8)
        if "profile" not in cfg.values:
            return {}
        if B._u(a):
            return {"volume_profile": "UNAVAILABLE", "depth_behaviour": "UNAVAILABLE"}
        dets = prof.get(s.underlying, [])
        v = (PR.profile_part(s.direction, a[1], dets, a[0])[0], PR.depth_part(s.direction, dets, a[0])[0])
        return {k: f"UNAVAILABLE {x.reason.split(':')[0]}" if B._u(x) else str(x)
                for k, x in zip(("volume_profile", "depth_behaviour"), v)}
    out = {"events": [], "ages": [], "classes": []}
    for s in setups:
        e = evs.get(s.id, [])
        conf = next((x for x in e if x["as_of"] == s.confirmed_ts and x["state"] == "ACTIVE" and x["obstacle"]), None)
        tgt = conf["obstacle"][2] if conf else Unavailable("NO_TARGET: no obstacle in the trade direction at confirmation")
        series = vw.get((s.underlying, f"{s.timeframe}m"), [])
        atr_at = lambda tf, t, sr=series: next((a for ts, a in reversed(sr) if ts <= t and a is not None),  # noqa: E731
                                               Unavailable("INSUFFICIENT_DATA: no ATR"))
        first = next((x for x in e if x["classification"] == B.TIMELY), None)
        anc = {"FIRST_DETECTION": (s.first_ts, s.first_price), "CONFIRMATION": (s.confirmed_ts, s.confirmed_price),
               "FIRST_EXECUTABLE": (first["as_of"], first["price"]) if first else Unavailable("NEVER_TIMELY")}
        lab = {"dataset": REC, "family": s.source_type, "family_letter": fam.get(s.id, "NONE"),
               "tod": B.tod_bucket(s.confirmed_ts, cfg), "instrument": s.underlying, "vix": "UNAVAILABLE (Q-12-11)",
               "token": s.token,
               "expiry": B.expiry_label(day, near.get(s.underlying), cfg)}
        b = bars.get(s.underlying, [])
        for name, a in anc.items():
            out["events"].append(B.outcome(s, name, a, tgt, b, 1, atr_at, cut, close, close, cfg, **lab, **parts(s, a)))
        out["ages"] += B.age_entries(s, tgt, b, cut, cfg)
        out["classes"] += B.class_entries(s, e, tgt, b, cut)
    return out


POSITIONING = ("LONG_BUILDUP", "SHORT_BUILDUP", "SHORT_COVERING", "LONG_UNWINDING")


def oi_delay_rows(day_dir: Path, events: list[dict]) -> list[dict]:
    """Study 4 (LOOK_AHEAD_DIAGNOSTIC, never a decision input): for each recorded positioning setup, the price token's OI
    known at confirmation (received by then) vs the OI eventually reported for that time (exchange time <= it)."""
    conf = {(r["setup_id"], r["t0"], r["token"]) for r in events if r["anchor"] == "CONFIRMATION" and r["family"] in POSITIONING
            and "t0" in r}
    if not conf:
        return []
    toks = sorted({c[2] for c in conf})
    if (day_dir / "buffer.sqlite").exists():
        db = sqlite3.connect(f"file:{day_dir / 'buffer.sqlite'}?mode=ro", uri=True)
        rows = db.execute(f"SELECT token, exchange_ts, receive_ns, oi FROM oi_changes WHERE token IN ({','.join('?' * len(toks))})",
                          toks).fetchall()
        db.close()
    else:
        import pyarrow.parquet as pq
        rows = [r for f in sorted((day_dir / "parquet" / "oi_changes").rglob("*.parquet"))
                for r in zip(*(pq.read_table(f, columns=["token", "exchange_ts", "receive_ns", "oi"]).to_pydict()[c]
                               for c in ("token", "exchange_ts", "receive_ns", "oi"))) if r[0] in toks]
    by = defaultdict(list)
    for tok, ex, rns, oi in rows:
        by[tok].append((ex * S, rns, oi))
    out = []
    for sid, t, tok in sorted(conf):
        now, later = B.oi_views(by[tok], t)
        out.append({"setup_id": sid, "token": tok, "t": t, "oi_at_decision": now, "oi_eventually_reported": later,
                    "differs": not isinstance(now, Unavailable) and not isinstance(later, Unavailable) and now != later,
                    "label": "LOOK_AHEAD_DIAGNOSTIC"})
    return out


def run_recorded_day(day_dir: Path, cfg, sig_cfg, bt_db, scratch: Path) -> dict:
    """One session through the live Phase 9 path into the backtest ledger (rebuilding the buffer if it was compacted)."""
    if not (day_dir / "signals.sqlite").exists():
        return {"day": day_dir.name, "skipped": "no signals.sqlite (Phase 8 not run for this date)"}
    d = day_dir if (day_dir / "buffer.sqlite").exists() else rehydrate(day_dir, cfg, scratch / day_dir.name)
    return L.run_day(cfg, sig_cfg, d, bt_db)


def holdout_log(cfg) -> Path:
    return cfg.root / cfg.get("backtest.results_dir") / "holdout_reads.log"


def read_holdout(cfg, st: str, days: list[str], now_iso: str) -> tuple[bool, str]:
    log = holdout_log(cfg)
    n = len(log.read_text().splitlines()) if log.exists() else 0
    ok, why = B.holdout_read_allowed(st, n)
    if ok:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as f:
            f.write(json.dumps({"read_at": now_iso, "stage": st, "sessions": days, "config_version": cfg.version}) + "\n")
    return ok, why


def run_recorded(cfg, sig_cfg, run_dir: Path, now_iso: str) -> dict:
    days = recorded_days(cfg.root)
    q = []
    for p in days:
        ev, gp = control_rows(p)
        q.append(B.session_quality(date.fromisoformat(p.name), ev, gp, last_packet_ns(p, cfg), cfg))
    good = [x.day for x in q if x.good]
    st = B.stage(len(good), cfg)
    sp = B.split(good, cfg)
    use = list(sp["development"])
    hold = read_holdout(cfg, st, sp["holdout"], now_iso) if sp["holdout"] else (False, "HOLDOUT_EMPTY: fewer good sessions")
    if hold[0]:
        use += sp["holdout"]
    out = {"stage": st, "good_sessions": len(good), "quality": [vars(x) | {"uncovered": len(x.uncovered)} for x in q],
           "split": {**{k: len(v) for k, v in sp.items()}, "development_days": sp["development"]}, "holdout": hold[1], "days": {}, "trades": [], "events": [],
           "ages": [], "classes": [], "oi_delay": []}
    if not use:
        return out
    bt = L.open_ledger(run_dir / "backtest_ledger.sqlite")
    with tempfile.TemporaryDirectory() as tmp:
        for d in use:
            p = cfg.root / d
            out["days"][d] = {k: (v if not isinstance(v, list) else len(v))
                              for k, v in run_recorded_day(p, cfg, sig_cfg, bt, Path(tmp)).items()}
            try:
                ev = recorded_events(p, cfg)
                for k in ("events", "ages", "classes"):
                    out[k] += ev[k]
                out["oi_delay"] += oi_delay_rows(p, ev["events"])
            except (sqlite3.Error, FileNotFoundError, KeyError) as e:
                out["days"][d]["events_unavailable"] = f"{type(e).__name__}: {e}"
    recs = {}
    for d in use:
        if (cfg.root / d / "signals.sqlite").exists():
            sg = sqlite3.connect(f"file:{cfg.root / d / 'signals.sqlite'}?mode=ro", uri=True)
            bands = sig_cfg.get("signals.bands")
            band = lambda x: "UNAVAILABLE" if x is None else "HIGH" if x >= bands["high"] else \
                "MEDIUM" if x >= bands["medium"] else "LOW"  # noqa: E731
            recs.update({r: {"score": s, "score_band": band(s), "classification": c} for r, s, c in sg.execute(
                "SELECT recommendation_id, score, classification FROM recommendations WHERE config_version=?", (sig_cfg.version,))})
            sg.close()
    out["trades"] = trade_rows(bt, cfg, recs)
    bt.close()
    return out


# ---------------------------------------------------------------- tables
def family_table(rows, cfg, key, by="family", inr=False, precision_from=None) -> dict:
    return {f: B.metrics(rs, cfg, key, None if precision_from is None else [r for r in precision_from if r.get(by) == f])
            for f, rs in B.group(rows, by).items()}


def event_study(events, cfg) -> dict:
    """Per family x anchor: n, segment counts, median MFE/MAE in R per horizon, pre-signal move share, median minutes."""
    out = {}
    for f, rs in B.group(events, "family").items():
        for a in ANCHORS:
            x = [r for r in rs if r["anchor"] == a and "unavailable" not in r]
            if not x and not any(r["anchor"] == a for r in rs):
                continue
            ps = [r["pre_signal_move_atr"] for r in x if r["pre_signal_move_atr"] is not None]
            mfe = {}
            for h in cfg.get("backtest.horizons_min"):
                v = [r["excursions"][h] for r in x if isinstance(r["excursions"].get(h), dict)]
                why = next((r["excursions"][h].reason for r in x if isinstance(r["excursions"].get(h), Unavailable)), None)
                mfe[h] = ({"n": len(v), "mfe_r": _med([y["mfe_r"] for y in v]), "mae_r": _med([y["mae_r"] for y in v]),
                           "mfe_atr": _med([y["mfe_atr"] for y in v]), "mae_atr": _med([y["mae_atr"] for y in v])}
                          if v else {"n": 0, "unavailable": why})
            out[f"{f} @ {a}"] = {
                "n": len(x), "n_unavailable": sum(1 for r in rs if r["anchor"] == a and "unavailable" in r),
                "segments": dict(Counter(r["segment"] for r in x)),
                "pre_signal_moved_share": round(sum(v > 0 for v in ps) / len(ps), 4) if ps else None,
                "pre_signal_move_atr_median": _med(ps),
                "minutes_to_target_median": _med([r["minutes_to_exit"] for r in x if r["exit_reason"] == B.TARGET]),
                "minutes_to_stop_median": _med([r["minutes_to_exit"] for r in x if r["exit_reason"] == B.STOP]),
                "excursions": mfe}
    return out


def profile_study(events, st, cfg):
    """Phase 13 (Q-13-8): FIRST_EXECUTABLE events split by the volume_profile / depth_behaviour part values (gross R)."""
    if "profile" not in cfg.values:
        return f"NOT_RUN: config {cfg.version} has no profile section (v17+)"
    return {p: B.factor_study(events, p, st, cfg) for p in ("volume_profile", "depth_behaviour")}


def _med(v):
    v = [x for x in v if x is not None]
    return round(statistics.median(v), 4) if v else None


def half_life_entries(ages, cfg) -> dict:
    return {f: B.half_life(rs, cfg) for f, rs in B.group(ages, "setup_type").items()}


def class_table(classes, cfg) -> dict:
    return {f"{f} / {c}": B.metrics(x, cfg) for f, rs in B.group(classes, "setup_type").items()
            for c, x in B.group(rs, "class").items()}


def _hl_versions(cfg) -> list:
    d = REPO / Path(cfg.get("opportunity.half_life_file")).parent
    return sorted((int(p.stem[1:]), p) for p in d.glob("v*.json") if p.stem[1:].isdigit()) if d.exists() else []


def latest_half_life(cfg) -> dict:
    v = _hl_versions(cfg)
    return {"RECORDED": {}, HIST: {}, **(json.loads(v[-1][1].read_text())["entries"] if v else {})}


def write_half_life(cfg, doc: dict) -> Path:
    """Write the half-life file as a new version only when its entries differ from the latest version."""
    d = REPO / Path(cfg.get("opportunity.half_life_file")).parent
    d.mkdir(parents=True, exist_ok=True)
    vers = _hl_versions(cfg)
    if vers and json.loads(vers[-1][1].read_text()).get("entries") == doc["entries"]:
        return vers[-1][1]
    p = d / f"v{(vers[-1][0] + 1) if vers else 1}.json"
    p.write_text(json.dumps({**doc, "version": p.stem}, indent=1, sort_keys=True) + "\n")
    return p


# ---------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", nargs="?", default="all", choices=("all", "historical", "recorded"))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--no-walk-forward", action="store_true")
    ap.add_argument("--pipeline-check", metavar="DATE", help="run one recorded day through the recorded path regardless of "
                    "quality, into the run dir only (PIPELINE_CHECK: never part of a result table)")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    sig_cfg = G.load()                                 # the live Phase 8 config (signals.sqlite rows are keyed by it)
    t0 = time.time()
    now = datetime.now(IST)
    run_dir = cfg.root / cfg.get("backtest.results_dir") / now.strftime("%Y%m%dT%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    res = {"title": B.TITLE, "config_version": cfg.version, "config_sha256": cfg.sha256, "run_at": now.isoformat()}
    if a.pipeline_check:
        bt = L.open_ledger(run_dir / "pipeline_check_ledger.sqlite")
        with tempfile.TemporaryDirectory() as tmp:
            res["pipeline_check"] = {"day": a.pipeline_check, "label": "PIPELINE_CHECK (excluded from every result)",
                                     "run_day": {k: (v if not isinstance(v, list) else len(v)) for k, v in run_recorded_day(
                                         cfg.root / a.pipeline_check, cfg, sig_cfg, bt, Path(tmp)).items()},
                                     "trades": trade_rows(bt, cfg, {})}
        ev = recorded_events(cfg.root / a.pipeline_check, cfg)
        res["pipeline_check"].update({"events": len(ev["events"]), "event_study": event_study(ev["events"], cfg),
                                      "profile_depth_study": profile_study(
                                          [e for e in ev["events"] if e["anchor"] == "FIRST_EXECUTABLE"], "PIPELINE_CHECK", cfg),
                                      "age_entries": len(ev["ages"]), "class_entries": len(ev["classes"]),
                                      "oi_delay_diagnostic": _oi_summary(oi_delay_rows(cfg.root / a.pipeline_check, ev["events"]))})
    hl = latest_half_life(cfg)          # datasets not re-run in this invocation keep their latest entries
    if a.what in ("all", "historical"):
        data, days, bad = load_lab(cfg)
        hc = hist_config(cfg)
        h = run_historical(hc, data, days, progress=True)
        fx = [r for r in h["events"] if r["anchor"] == "FIRST_EXECUTABLE"]
        conf = [r for r in h["events"] if r["anchor"] == "CONFIRMATION"]       # precision: every event once (Q-12-10)
        res["historical"] = {
            "dataset": f"{HIST}: NIFTY 50 index 5m/15m (lab CSV, sha256 verified), {len(days)} usable days "
                       f"{days[0]}..{days[-1]}, {len(bad)} excluded; price path only: no fills, no costs, gross R",
            "config_version": hc.version, "usable_days": len(days), "excluded_days": bad, "setups": h["setups"],
            "event_study": event_study(h["events"], cfg),
            "families_first_executable": family_table(fx, cfg, "r", precision_from=conf),
            "by_timeframe": family_table(fx, cfg, "r", by="timeframe"), "by_regime": family_table(fx, cfg, "r", by="regime"),
            "by_time_of_day": family_table(fx, cfg, "r", by="tod"),
            "age_classes": class_table(h["classes"], cfg), "half_life": half_life_entries(h["ages"], cfg),
            "not_representable": ["Phase 13 volume profile and depth behaviour (index: no volume, no depth, F-WS-7)",
                                  "VWAP families (no volume)", "Phase 8 families A-D (no futures OI)",
                                  "Phase 8 families E/F (rejection RVOL needs volume)", "stocks (survivorship: no "
                                  "historical constituent lists)", "rupee expectancy, slippage share (no fills)"]}
        hl[HIST] = {k: {**v, "dataset": HIST, "stage": "HISTORICAL_CANDLES"} for k, v in res["historical"]["half_life"].items()}
        if not a.no_walk_forward:
            wf = cfg.get("backtest.walk_forward.historical")
            keys = list(wf["grid"])
            combos = [dict(zip(keys, v)) for v in __import__("itertools").product(*(wf["grid"][k] for k in keys))]
            runs = {json.dumps(c, sort_keys=True): [r for r in run_historical(hist_config(cfg, c), data, days)["events"]
                                                    if r["anchor"] == "FIRST_EXECUTABLE"] for c in combos}
            wins = B.month_windows([str(d) for d in days], wf["train_months"], wf["test_months"], wf["step_months"])
            res["historical"]["walk_forward"] = {}
            for fam in sorted({r["family"] for rs in runs.values() for r in rs}):
                w = B.walk_forward(wins, list(runs), lambda p, ds, f=fam: [r for r in runs[p] if r["family"] == f
                                                                         and r.get("day") in ds], cfg)
                res["historical"]["walk_forward"][fam] = {"windows": w["windows"], "oos": B.metrics(w["oos_rows"], cfg)}
    if a.what in ("all", "recorded"):
        r = run_recorded(cfg, sig_cfg, run_dir, now.isoformat())
        st = r["stage"]
        res["recorded"] = {k: r[k] for k in ("stage", "good_sessions", "quality", "split", "holdout", "days")}
        prec = [{**e, "family": e["family_letter"]} for e in r["events"] if e["anchor"] == "CONFIRMATION"]
        res["recorded"].update({
            "families_trades_inr": family_table(r["trades"], cfg, "net_inr", precision_from=prec),
            "families_trades_r": family_table(r["trades"], cfg, "r", precision_from=prec),
            "event_study": event_study(r["events"], cfg), "age_classes": class_table(r["classes"], cfg),
            "half_life": half_life_entries(r["ages"], cfg),
            "slippage_share": _slip_share(r["trades"]),
            "segments": {k: family_table(r["trades"], cfg, "r", by=k) for k in ("underlying", "tod", "score_band", "instrument")}
            | {"expiry (events @ FIRST_EXECUTABLE, gross R)": family_table(
                [e for e in r["events"] if e["anchor"] == "FIRST_EXECUTABLE"], cfg, "r", by="expiry")},
            "oi_delay_diagnostic": _oi_summary(r["oi_delay"]),
            "profile_depth_study": profile_study([e for e in r["events"] if e["anchor"] == "FIRST_EXECUTABLE"], st, cfg)})
        hl["RECORDED"] = {k: {**v, "dataset": REC, "stage": st} for k, v in res["recorded"]["half_life"].items()}
        wf = cfg.get("backtest.walk_forward.recorded")      # score floor as a post-filter on the trades (Q-12-20)
        dev = res["recorded"]["split"]["development_days"]
        wins = [([dev[i] for i in tr], [dev[i] for i in te]) for tr, te in B.windows(len(dev), wf["train"], wf["test"], wf["step"])]
        res["recorded"]["walk_forward"] = {f: {"windows": w["windows"], "oos": B.metrics(w["oos_rows"], cfg)} for f, w in (
            (f, B.walk_forward(wins, wf["score_floor"], lambda floor, ds, f=f: [t for t in r["trades"] if t["family"] == f
                               and t["day"] in ds and (t.get("score") or 0) >= floor], cfg))
            for f in sorted({t["family"] for t in r["trades"]}))} if wins else \
            f"NOT_RUN: {len(dev)} development sessions < train {wf['train']} + test {wf['test']}"
        fams = sorted(set(res["recorded"]["families_trades_r"]) | set("ABCDEF"))
        res["verdicts"] = {f: B.verdict(res["recorded"]["families_trades_r"].get(f, {"n": 0}), st, cfg) for f in fams}
    res["half_life_file"] = str(write_half_life(cfg, {"generated_by": f"engine.backtest_report {run_dir.name}",
                                                      "config_version": cfg.version, "entries": hl}).relative_to(REPO))
    res["runtime_s"] = round(time.time() - t0, 1)
    (run_dir / "results.json").write_text(json.dumps(res, indent=1, default=_default, sort_keys=True))
    (run_dir / "report.md").write_text(render(res, cfg))
    print(json.dumps({"run_dir": str(run_dir), "runtime_s": res["runtime_s"], "half_life_file": res["half_life_file"],
                      "recorded_stage": res.get("recorded", {}).get("stage")}))
    return 0


def _f(x, n=3):
    return "—" if x is None else f"{x:.{n}f}" if isinstance(x, float) else str(x)


def _ci(m, k):
    c = (m.get("ci") or {}).get(k)
    return f" [{c[0]:.3f}, {c[1]:.3f}]" if c else ""


def _table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] +
                      ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]) + "\n"


def _metric_rows(t, unit):
    return [[f, m["n"], _f(m["precision"]), _f(m["win_rate"]), _f(m["avg_win"]), _f(m["avg_loss"]),
             _f(m["expectancy"]) + _ci(m, "expectancy"), _f(m["profit_factor"]) + _ci(m, "profit_factor"),
             _f(m["max_drawdown"]), "yes" if m["sample_ok"] else "**INSUFFICIENT_SAMPLE**"] for f, m in t.items()]


def render(res: dict, cfg) -> str:
    """Markdown tables of one run. Every table: SIMULATED / HYPOTHETICAL, its dataset, its stage and good-session count."""
    out, mh = [f"# Phase 12 backtest run {res['run_at']} (config {res['config_version']})\n"], \
        ["family", "n", "precision", "win rate", "avg win", "avg loss", "expectancy [95% CI]", "profit factor [95% CI]",
         "max DD", f"n >= {cfg.get('backtest.min_trades')}"]
    if "historical" in res:
        h = res["historical"]
        hdr = (f"**{B.TITLE} · {HIST} (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good "
               f"sessions · {h['usable_days']} usable index days · price path, no fills, no costs, gross R**\n\n")
        out.append("## HISTORICAL_CANDLES\n\n" + h["dataset"] + "\n\nNot representable: " + "; ".join(h["not_representable"]) +
                   f"\n\nSetups by type: {h['setups']}. Excluded days: {len(h['excluded_days'])}.\n")
        out.append("### H1. Families, entry at FIRST_EXECUTABLE (first TIMELY evaluation), unit R\n\n" + hdr +
                   _table(mh, _metric_rows(h["families_first_executable"], "R")))
        seg = list(B.SEGMENTS)
        out.append("### H2. Event study: segments, pre-signal move, time to exit\n\n" + hdr + _table(
            ["family @ anchor", "n", "n anchor unavailable"] + seg + ["moved before signal", "median pre-signal ATR",
                                                                     "median min to target", "median min to stop"],
            [[k, v["n"], v["n_unavailable"]] + [v["segments"].get(x, 0) for x in seg] +
             [_f(v["pre_signal_moved_share"]), _f(v["pre_signal_move_atr_median"]), _f(v["minutes_to_target_median"], 1),
              _f(v["minutes_to_stop_median"], 1)] for k, v in h["event_study"].items()]))
        hz = cfg.get("backtest.horizons_min")
        out.append("### H3. Event study: median MFE / MAE in R (and ATR) per horizon after the anchor\n\n" + hdr + _table(
            ["family @ anchor"] + [f"{x} min" for x in hz],
            [[k] + [("n/a: " + v["excursions"][x]["unavailable"].split(":")[0]) if not v["excursions"][x]["n"] else
                    f"{_f(v['excursions'][x]['mfe_r'], 2)} / {_f(v['excursions'][x]['mae_r'], 2)} R "
                    f"({_f(v['excursions'][x]['mfe_atr'], 2)} / {_f(v['excursions'][x]['mae_atr'], 2)} ATR)"
                    for x in hz] for k, v in h["event_study"].items() if v["n"]]))
        out.append("### H4. Edge half-life (fresh entry expectancy by age since confirmation)\n\n" + hdr + _table(
            ["setup type", "status", "half-life"] + [f"age {b} min: n / E[R]" for b in cfg.get("backtest.age_buckets_min")],
            [[k, v["status"], _f(v["half_life_s"])] + [f"{b['n']} / {_f(b['expectancy_r'])}" for b in v["buckets"]]
             for k, v in h["half_life"].items()]))
        out.append("### H5. Opportunity Age validation: TIMELY vs VALID_BUT_LATE vs RETEST entries\n\n" + hdr +
                   _table(mh, _metric_rows(h["age_classes"], "R")))
        for key, name in (("by_timeframe", "timeframe (min)"), ("by_regime", "NIFTY 15m TREND regime"),
                          ("by_time_of_day", "time of day (confirmation)")):
            out.append(f"### H6. Segment: {name}, entry at FIRST_EXECUTABLE, all setup types\n\n" + hdr +
                       _table([name] + mh[1:], _metric_rows(h[key], "R")))
        if "walk_forward" in h:
            wf = h["walk_forward"]
            out.append("### H7. Walk-forward (train 12 m / test 3 m / step 3 m), out-of-sample test windows only\n\n" + hdr +
                       _table(mh[:1] + ["windows", "windows with a choice", "choices"] + mh[1:],
                              [[f, len(w["windows"]), sum(1 for x in w["windows"] if x["chosen"]),
                                dict(Counter(x["chosen"] for x in w["windows"] if x["chosen"]))] + r[1:]
                               for (f, w), r in zip(wf.items(), _metric_rows({f: w["oos"] for f, w in wf.items()}, "R"))]))
    if "recorded" in res:
        r = res["recorded"]
        hdr = f"**{B.TITLE} · {REC} sessions · stage {r['stage']} · {r['good_sessions']} good sessions**\n\n"
        out.append("## RECORDED\n\n" + f"Split: {r['split']}. Holdout: {r['holdout']}.\n")
        out.append("### R1. Session quality\n\n" + hdr + _table(
            ["session", "GOOD", "coverage", "max edge gap s", "reasons"],
            [[q["day"], q["good"], f"{q['coverage']:.1%}", q["max_edge_gap_s"], "; ".join(q["reasons"]) or "—"] for q in r["quality"]]))
        out.append("### R2. Families (paper-broker trades, net of Phase 7 costs), unit INR\n\n" + hdr +
                   (_table(mh, _metric_rows(r["families_trades_inr"], "INR")) if r["families_trades_inr"] else "No trades.\n"))
        out.append("### R3. Families, unit net R\n\n" + hdr +
                   (_table(mh, _metric_rows(r["families_trades_r"], "R")) if r["families_trades_r"] else "No trades.\n"))
        out.append("### R4. Slippage share of gross P&L, OI publication delay\n\n" + hdr +
                   f"Slippage: {r['slippage_share']}\n\nOI delay: {r['oi_delay_diagnostic']}\n")
        for k, t in (r.get("segments") or {}).items():
            out.append(f"### R7. Segment: {k}, unit R\n\n" + hdr + (_table([k] + mh[1:], _metric_rows(t, "R")) if t else "No rows.\n"))
        out.append("### R6. Walk-forward (train 40 / test 10 / step 10 good sessions), out-of-sample only\n\n" + hdr +
                   f"{r.get('walk_forward')}\n")
        out.append("### R5. Event study, half-life, Opportunity Age (recorded)\n\n" + hdr +
                   (f"{len(r['event_study'])} family x anchor rows; half-life {r['half_life'] or 'no entries'}\n"))
        out.append("### R8. Phase 13 profile / depth parts, events at FIRST_EXECUTABLE, gross R\n\n" + hdr +
                   _study(r.get("profile_depth_study"), mh))
    if "verdicts" in res:
        st = res["recorded"]["stage"]
        out.append(f"## Verdicts\n\n**{B.TITLE} · stage {st} · {res['recorded']['good_sessions']} good sessions**\n\n" +
                   _table(["Phase 8 family", "verdict", "reason"], [[f, v[0], v[1]] for f, v in res["verdicts"].items()]))
    if "pipeline_check" in res:
        pc = res["pipeline_check"]
        out.append(f"## PIPELINE_CHECK {pc['day']} (EXCLUDED session; not part of any result)\n\n"
                   f"run_day: {pc['run_day']}; trades: {len(pc['trades'])}; event rows: {pc['events']}; age entries: "
                   f"{pc['age_entries']}; class entries: {pc['class_entries']}; OI delay: {pc['oi_delay_diagnostic']}\n\n" +
                   _table(["family @ anchor", "n", "n anchor unavailable"] + list(B.SEGMENTS),
                          [[k, v["n"], v["n_unavailable"]] + [v["segments"].get(x, 0) for x in B.SEGMENTS]
                           for k, v in pc["event_study"].items()]) +
                   "\n### Phase 13 profile / depth parts (PIPELINE_CHECK)\n\n" + _study(pc.get("profile_depth_study"), mh))
    out.append(f"Half-life file: `{res.get('half_life_file')}`. Runtime {res.get('runtime_s')} s.\n")
    return "\n".join(out)


def _study(st, mh) -> str:
    if not isinstance(st, dict):
        return f"{st}\n"
    return "".join(f"**{p}**: verdict {v['verdict']} ({v['why']}); weight {v['weight']}\n\n" +
                   (_table([p] + mh[1:], _metric_rows(v["groups"], "R")) if v["groups"] else "No rows.\n") + "\n"
                   for p, v in st.items())


def _oi_summary(rows) -> dict:
    ok = [r for r in rows if not isinstance(r["oi_at_decision"], Unavailable)]
    d = [abs(r["oi_eventually_reported"] - r["oi_at_decision"]) / r["oi_at_decision"] * 100 for r in ok
         if r["differs"] and r["oi_at_decision"]]
    return {"label": "LOOK_AHEAD_DIAGNOSTIC (never a decision input)", "positioning_decisions": len(rows),
            "oi_unavailable_at_decision": len(rows) - len(ok), "differs": sum(r["differs"] for r in rows),
            "median_abs_diff_pct": _med(d)}


def _slip_share(trades) -> dict:
    ok = [t for t in trades if "net_inr" in t]
    g = sum(t["gross_inr"] for t in ok)
    return {"slippage_inr": round(sum(t["slippage_inr"] for t in ok), 2), "gross_inr": round(g, 2),
            "share_of_gross": round(sum(t["slippage_inr"] for t in ok) / g, 6) if g > 0 else None}


def _default(x):
    return {"UNAVAILABLE": x.reason} if isinstance(x, Unavailable) else str(x)


if __name__ == "__main__":
    sys.exit(main())
