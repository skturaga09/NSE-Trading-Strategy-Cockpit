"""Phase 10 API (edge): `/api/engine/*`, mounted into dashboard/api_server.py like dashboard/api/mcx.py.

Access (owner, Q-10-3): only a loopback client, and only a request the browser marks same-origin (`Sec-Fetch-Site`
same-origin / none, or an `Origin` on localhost). A page on another site open in the same browser cannot read or write.
No Kite credential is read here and none is ever returned.

GET  sessions | overview | radar | positioning | signal/{id} | trades | performance | health | health/stream (SSE)
POST journal/take | journal/skip | journal/exit | feedback   (Phase 9 journal and feedback: stored only)

Every GET returns engine.dashboard.envelope(...): provenance, age at the view time, OK / STALE / UNAVAILABLE.
`as_of` (ns) replays a recorded day: only rows observed at or before it are returned and ages are measured from it.
"""

import asyncio
import json
import pickle
import re
import sqlite3
import time
import zlib
from contextlib import closing
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import dashboard as D
from . import ledger as L
from . import paper as P
from .candles import IST, _ns
from .contracts import OPTION_KINDS
from .costs import round_trip
from .config import REPO
from .dashboard_export import load as load_cfg

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@lru_cache(maxsize=1)
def cfg():
    return load_cfg(REPO / "config" / "engine" / "v14.yaml")   # Phase 11: adds dashboard.stale_after_s.chain


def local_only(request: Request) -> None:
    host = request.client.host if request.client else None
    if host not in LOOPBACK:
        raise HTTPException(403, "engine API: loopback clients only")
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        raise HTTPException(403, f"engine API: cross-site request refused ({site})")
    origin = request.headers.get("origin")
    if origin is not None and re.sub(r"^https?://|:\d+$", "", origin) not in LOOPBACK:
        raise HTTPException(403, "engine API: foreign Origin refused")


router = APIRouter(prefix="/api/engine", tags=["engine"], dependencies=[Depends(local_only)])


# ---------------------------------------------------------------- helpers (edge reads, read-only)
def _day_dir(d: str) -> Path:
    if not DATE_RE.match(d or ""):
        raise HTTPException(400, "date must be YYYY-MM-DD")
    date.fromisoformat(d)
    p = cfg().root / d
    if not p.is_dir():
        raise HTTPException(404, f"no recorded session {d}")
    return p


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        from .retention import fetch
        path = fetch(path)   # a past day moved to the cloud archive: read it back from there
        if path is None:
            return None
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _now(as_of: int | None) -> tuple[int, str]:
    return (as_of, "REPLAY") if as_of is not None else (time.time_ns(), "LIVE")


def _latest_version(db, table: str) -> str | None:
    vs = [r[0] for r in db.execute(f"SELECT DISTINCT config_version FROM {table}")]
    return max(vs, key=lambda v: int(v.lstrip("v")), default=None)   # numeric: v13 > v9


def _quality(p: dict) -> tuple:
    q = p.get("quality") or {}
    return q.get("receive_ts"), q.get("processing_ts")


def _missing(panel, why, now, mode, source):
    return D.envelope(panel, None, source=source, observed_ns=None, received_ns=None, processed_ns=None, now_ns=now,
                      mode=mode, cfg=cfg(), reason=why)


# ---------------------------------------------------------------- GET
@router.get("/sessions")
def sessions():
    root, out = cfg().root, []
    for p in sorted(root.iterdir()) if root.exists() else []:
        if p.is_dir() and DATE_RE.match(p.name):
            d = date.fromisoformat(p.name)
            out.append({"date": p.name, "open_ns": _ns(d, cfg().get("sessions.fno.open")),
                        "close_ns": _ns(d, cfg().get("sessions.fno.close")), **{k: (p / f).exists() for k, f in (
                            ("signals", "signals.sqlite"), ("dashboard", "dashboard.sqlite"), ("status", "status.json"))}})
    return {"sessions": out, "today": datetime.now(IST).date().isoformat(), "config_version": cfg().version}


@router.get("/overview")
def overview(date: str, as_of: int | None = None):
    now, mode = _now(as_of)
    db = _ro(_day_dir(date) / "dashboard.sqlite")
    if db is None:
        return _missing("overview", "no dashboard.sqlite: run python3 -m engine.dashboard_export " + date, now, mode, "dashboard.sqlite")
    with closing(db):
        v = _latest_version(db, "runs")
        m = db.execute("SELECT * FROM market WHERE config_version=? AND ts_ns<=? ORDER BY ts_ns DESC LIMIT 1", (v, now)).fetchone()
        idx = cfg().get("positioning.beta.index_underlying")
        cs = [json.loads(r["payload"]) for r in db.execute(
            "SELECT payload FROM candles WHERE config_version=? AND underlying=? AND end_ns<=? ORDER BY end_ns", (v, idx, now))]
        mark = m["ts_ns"] if m else None
        pos = [dict(r) for r in db.execute(
            "SELECT * FROM positioning WHERE config_version=? AND view='primary' AND ts_ns=?", (v, mark))]
    usable = [c for c in cs if c["completeness"] == "COMPLETE" and not D.is_u(c["close"]) and not D.is_u(c["vwap"])]
    last = usable[-1] if usable else None
    counts = {}
    for r in pos:
        h = D.hypothesis(r["hypothesis"], json.loads(r["reasons"]))
        k = "UNAVAILABLE" if D.is_u(h) else h
        counts[k] = counts.get(k, 0) + 1
    oi = [{"end_ns": c["end_ns"], "oi": c["oi_at_close"], "oi_age_s": c["oi_age_seconds"]} for c in cs[::cfg().get("dashboard.scrub_step_min")]]
    data = {
        "index": idx, "contract": cs[-1].get("token") if cs else None,
        "market_context": json.loads(m["payload"]) if m else D.U("no market mark at or before the view time"),
        "close": last["close"] if last else D.U("no usable 1m candle of the index future"),
        "vwap": last["vwap"] if last else D.U("no usable 1m candle of the index future"),
        "vwap_relation": (("ABOVE" if last["close"] > last["vwap"] else "BELOW" if last["close"] < last["vwap"] else "AT")
                          if last else D.U("no usable 1m candle")),
        "index_futures_oi": oi or D.U("no index future candles"),
        "india_vix": D.U(f"{cfg().get('dashboard.vix_underlying')} is not in the recorded universe (universe.index_spots)"),
        "positioning_summary": {"view": "primary (residual)", "mark_ns": mark, "counts": counts,
                                "label": "positioning hypotheses from price and OI; not a measure of who is buying"},
    }
    rx, px = _quality(last) if last else (None, None)
    return D.envelope("overview", data, source="dashboard.sqlite (Phase 3 candles, Phase 4/5 recomputed, signals.market_context)",
                      observed_ns=last["end_ns"] if last else mark, received_ns=rx, processed_ns=px, now_ns=now, mode=mode, cfg=cfg())


def _signals_db(day_dir: Path):
    db = _ro(day_dir / "signals.sqlite")
    if db is None:
        return None, None
    return db, _latest_version(db, "runs")


@router.get("/radar")
def radar(date: str, as_of: int | None = None):
    now, mode = _now(as_of)
    db, v = _signals_db(_day_dir(date))
    if db is None:
        return _missing("radar", "no signals.sqlite (Phase 8 not run for this date)", now, mode, "signals.sqlite")
    with closing(db):
        recs = db.execute("SELECT payload, inputs FROM recommendations WHERE config_version=? AND as_of<=? ORDER BY as_of",
                          (v, now)).fetchall()
        life = {}
        for r in db.execute("SELECT signal_id, to_state FROM lifecycle WHERE config_version=? AND ts<=? ORDER BY signal_id, seq",
                            (v, now)):
            life[r["signal_id"]] = r["to_state"]
    fw = cfg().get("positioning.feature_window_min")
    rows = []
    for r in recs:
        p = json.loads(r["payload"])
        rows.append(D.radar_row(p, pickle.loads(zlib.decompress(r["inputs"])), fw, life.get(p["signal_id"])))
    newest = max((r["as_of"] for r in rows), default=None)
    fresh = json.loads(recs[-1]["payload"])["data_freshness"] if recs else {}
    return D.envelope("radar", {"rows": rows, "feature_window_min": fw, "signals_config_version": v,
                                "track_record": D.track_record(cfg().root, date)},
                      source="signals.sqlite (Phase 8 recommendations)", observed_ns=newest,
                      received_ns=fresh.get("price_receive_ns"), processed_ns=fresh.get("processed_ns"), now_ns=now,
                      mode=mode, cfg=cfg(), reason=None if rows else "no recommendation at or before the view time")


@router.get("/positioning")
def positioning(date: str, view: Literal["primary", "raw"] = "primary", mark: int | None = None, as_of: int | None = None):
    now, mode = _now(as_of)
    day_dir = _day_dir(date)
    db = _ro(day_dir / "dashboard.sqlite")
    if db is None:
        return _missing("positioning", "no dashboard.sqlite: run python3 -m engine.dashboard_export " + date, now, mode, "dashboard.sqlite")
    with closing(db):
        v = _latest_version(db, "runs")
        marks = [r[0] for r in db.execute("SELECT DISTINCT ts_ns FROM positioning WHERE config_version=? AND ts_ns<=? ORDER BY ts_ns",
                                          (v, now))]
        sel = mark if mark in marks else (marks[-1] if marks else None)
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM positioning WHERE config_version=? AND view=? AND ts_ns=? ORDER BY underlying", (v, view, sel))]
    for r in rows:
        r["reasons"] = json.loads(r["reasons"])
        for k in ("price_chg_pct", "oi_chg_pct", "rvol"):
            r[k] = json.loads(r[k])
    sdb, sv = _signals_db(day_dir)
    acc = []
    if sdb is not None and sel is not None:
        with closing(sdb):
            acc = [json.loads(r["payload"]) for r in sdb.execute(
                "SELECT payload FROM observations WHERE config_version=? AND ts<=? AND label IN "
                "('SUSPECTED_ACCUMULATION','SUSPECTED_DISTRIBUTION') ORDER BY ts", (sv, sel))]
    data = {"view": view, "marks": marks, "mark_ns": sel, "cells": [D.positioning_cell(r["underlying"], r) for r in rows],
            "suspected": acc, "disclaimer": "positioning hypotheses from price and OI changes; rising OI is not institutional buying"}
    return D.envelope("positioning", data, source="dashboard.sqlite (Phase 4 recomputed)", observed_ns=sel, received_ns=None,
                      processed_ns=None, now_ns=now, mode=mode, cfg=cfg())


@router.get("/chain")
def chain(date: str, underlying: str | None = None, as_of: int | None = None):
    now, mode = _now(as_of)
    day_dir, src = _day_dir(date), "options.sqlite (engine.chain_report: recorded option quotes, Black-76)"
    db = _ro(day_dir / "options.sqlite")
    if db is None:
        return _missing("chain", "no options.sqlite: no option recorded for this session, or run python3 -m engine.chain_report "
                        + date, now, mode, src)
    with closing(db):
        v = _latest_version(db, "runs")
        unds = [r[0] for r in db.execute("SELECT DISTINCT underlying FROM chain_snapshots WHERE config_version=? AND as_of<=? "
                                          "ORDER BY underlying", (v, now))]
        und = underlying if underlying in unds else (unds[0] if unds else None)
        if und is None:
            return _missing("chain", f"no chain snapshot at or before the view time ({v})", now, mode, src)
        t = db.execute("SELECT max(as_of) FROM chain_snapshots WHERE config_version=? AND underlying=? AND as_of<=?",
                       (v, und, now)).fetchone()[0]
        snaps = [json.loads(r[0]) for r in db.execute(
            "SELECT payload FROM chain_snapshots WHERE config_version=? AND underlying=? AND as_of=? ORDER BY expiry", (v, und, t))]
    rec = None
    sdb, sv = _signals_db(day_dir)
    if sdb is not None:
        with closing(sdb):
            r = sdb.execute("SELECT payload FROM recommendations WHERE config_version=? AND underlying=? AND as_of<=? "
                            "ORDER BY as_of DESC LIMIT 1", (sv, und, now)).fetchone()
            rec = None if r is None else json.loads(r[0])
    newest = max((r["receive_ns"] for s in snaps for r in s["rows"] if r.get("receive_ns")), default=None)
    return D.envelope("chain", {"underlying": und, "underlyings": unds, "snapshot_ns": t, "options_config_version": v,
                                **D.chain_view(snaps, rec)},
                      source=src, observed_ns=t, received_ns=newest, processed_ns=t, now_ns=now, mode=mode, cfg=cfg())


@router.get("/signal/{recommendation_id}")
def signal(recommendation_id: str, date: str, as_of: int | None = None):
    now, mode = _now(as_of)
    day_dir = _day_dir(date)
    db, v = _signals_db(day_dir)
    if db is None:
        return _missing("signal", "no signals.sqlite", now, mode, "signals.sqlite")
    with closing(db):
        r = db.execute("SELECT payload FROM recommendations WHERE recommendation_id=? AND config_version=?",
                       (recommendation_id, v)).fetchone()
        if r is None:
            raise HTTPException(404, f"no recommendation {recommendation_id} on {date}")
        p = json.loads(r["payload"])
        if p["as_of"] > now:
            return _missing("signal", f"look-ahead: recommendation {recommendation_id} was made after the view time", now, mode,
                            "signals.sqlite")
        life = [dict(x) for x in db.execute("SELECT ts, from_state, to_state, cause FROM lifecycle WHERE signal_id=? AND "
                                            "config_version=? AND ts<=? ORDER BY seq", (p["signal_id"], v, now))]
    candles, dets, evals = [], [], []
    ddb = _ro(day_dir / "dashboard.sqlite")
    if ddb is not None:
        with closing(ddb):
            dv = _latest_version(ddb, "runs")
            candles = [json.loads(x["payload"]) for x in ddb.execute(
                "SELECT payload FROM candles WHERE config_version=? AND token=? AND end_ns<=? ORDER BY end_ns",
                (dv, p["price_token"], now))]
    st = _ro(day_dir / "structure.sqlite")
    if st is not None:
        with closing(st):
            dets = [json.loads(x["payload"]) for x in st.execute(
                "SELECT payload FROM structure_detections WHERE underlying=? AND config_version=? AND confirmed_ts<=? "
                "ORDER BY confirmed_ts", (p["underlying"], L.cfg_str_version(day_dir), now))]
    op = _ro(day_dir / "opportunity.sqlite")
    if op is not None:
        with closing(op):
            evals = [json.loads(x["payload"]) for x in op.execute(
                "SELECT payload FROM evaluations WHERE setup_id=? AND config_version=? AND as_of<=? ORDER BY as_of",
                (p["signal_id"], L.cfg_opp_version(day_dir), now))]
    bars = [{"end_ns": c["end_ns"], "start_ns": c["start_ns"], "open": c["open"], "high": c["high"], "low": c["low"],
             "close": c["close"], "volume": c["volume"], "vwap": c["vwap"], "completeness": c["completeness"],
             "status": (c.get("quality") or {}).get("status"), "oi": c["oi_at_close"], "oi_age_s": c["oi_age_seconds"],
             "oi_last_change_ns": c["oi_last_change_ns"]} for c in candles]
    first_tl = next((e for e in evals if e["classification"] == "TIMELY"), None)
    data = {"recommendation": p, "bars": bars, "detections": dets, "lifecycle": life,
            "timeline": {"detected_ns": p["first_detected_ts"], "confirmed_ns": p["confirmed_ts"],
                         "eligible_ns": next((x["ts"] for x in life if x["to_state"] == "ENTRY_ELIGIBLE"),
                                             D.U(f"never ENTRY_ELIGIBLE (status {p['status']})")),
                         "first_timely_ns": first_tl["as_of"] if first_tl else D.U("no TIMELY Phase 6 evaluation")},
            "evaluations": evals[-120:]}
    last = candles[-1] if candles else None
    rx, px = _quality(last) if last else (None, None)
    return D.envelope("signal", data, source="signals / structure / opportunity / dashboard stores",
                      observed_ns=last["end_ns"] if last else p["as_of"], received_ns=rx, processed_ns=px, now_ns=now,
                      mode=mode, cfg=cfg())


def _ledger_db():
    return _ro(L.path_of(cfg()))


def _closed(db, ledger: str) -> list[dict]:
    """One ledger's closed trades with gross, estimated charges, slippage and the recommendation's tags."""
    out = []
    exits = {}
    for f in db.execute(L.Q_EXITS[ledger]):
        exits.setdefault(f["trade_id"], []).append(dict(f))
    entries = {}
    if ledger == P.SIMULATED:
        for f in db.execute("SELECT trade_id, slippage_per_unit, qty_filled FROM sim_fills WHERE role='ENTRY'"):
            entries[f["trade_id"]] = f["slippage_per_unit"] * f["qty_filled"] / 100
        slip_x = {}
        for f in db.execute("SELECT trade_id, slippage_per_unit, qty_filled FROM sim_fills WHERE role='EXIT'"):
            slip_x[f["trade_id"]] = slip_x.get(f["trade_id"], 0.0) + f["slippage_per_unit"] * f["qty_filled"] / 100
    for t in L.trades(db, ledger):
        xs = exits.get(t["id"], [])
        if sum(x["qty"] for x in xs) < t["qty"]:
            continue
        prod, sgn, day = ("OPT" if t["kind"] in OPTION_KINDS else "FUT"), (1 if t["side"] == "BUY" else -1), date.fromisoformat(t["day"])
        gross = sum(sgn * (x["price"] - t["entry_price"]) * x["qty"] / 100 for x in xs)
        charges = sum(round_trip(cfg(), prod, t["side"], t["entry_price"] / 100, x["price"] / 100, x["qty"], day).total_inr for x in xs)
        tags = _rec_tags(t["day"], t["recommendation_id"])
        out.append({"id": t["id"], "ledger": ledger, "underlying": t["underlying"], "family": t["family"],
                    "entry_ns": t["entry_ns"], "exit_ns": max(x["ns"] for x in xs), "gross": gross, "charges": charges,
                    "net": gross - charges,
                    "slippage_inr": (entries.get(t["id"], 0.0) + slip_x.get(t["id"], 0.0)) if ledger == P.SIMULATED
                    else D.U("ACTUAL slippage is not recorded per fill (see feedback.slippage)"), **tags})
    return out


def _rec_tags(day: str, rec_id: str) -> dict:
    db, v = _signals_db(cfg().root / day) if DATE_RE.match(day) else (None, None)
    if db is None:
        return {"score_band": D.U("no signals.sqlite"), "timeliness": D.U("no signals.sqlite")}
    with closing(db):
        r = db.execute("SELECT payload FROM recommendations WHERE recommendation_id=? AND config_version=?", (rec_id, v)).fetchone()
    if r is None:
        return {"score_band": D.U("recommendation not found"), "timeliness": D.U("recommendation not found")}
    p = json.loads(r["payload"])
    return {"score_band": p["score"]["headline"]["band"], "timeliness": D.timeliness(p["opportunity_age"])}


@router.get("/trades")
def trades(date: str | None = None, as_of: int | None = None):
    now, mode = _now(as_of)
    db = _ledger_db()
    if db is None:
        return _missing("trades", "no ledger.sqlite (run python3 -m engine.ledger run)", now, mode, "ledger.sqlite")
    out, newest = {}, None
    with closing(db):
        for led in P.LEDGERS:
            ds, al = L.decisions(db, led), L.alerts(db, led)
            exits = {}
            for f in db.execute(L.Q_EXITS[led]):
                if f["ns"] <= now:
                    exits[f["trade_id"]] = exits.get(f["trade_id"], 0) + f["qty"]
            rows = []
            for t in L.trades(db, led):
                if (date and t["day"] != date) or t["entry_ns"] > now:
                    continue
                mine = [d for d in ds if d["trade_id"] == t["id"] and d["as_of"] <= now]
                last = mine[-1] if mine else None
                newest = max(newest or 0, last["as_of"]) if last else newest
                obs = {o["field"]: o for o in json.loads(last["observations"])} if last else {}
                mark = {k: obs[k]["value"] if k in obs else D.U(f"no {k} in the latest decision's observations")
                        for k in ("bid", "ask")}
                mark["observed_ns"] = next((obs[k]["exchange_ts_ns"] or obs[k]["receive_ns"] for k in ("bid", "ask") if k in obs), None)
                rows.append({**t, "open_qty": t["qty"] - exits.get(t["id"], 0), "lots": t["qty"] // t["lot_size"],
                             "mark": mark, "mark_label": "executable side of the contract book at the latest decision (5 visible levels)",
                             "decision": last["decision"] if last else D.U("no monitor decision yet"),
                             "rule_id": last["rule_id"] if last else None, "stop": last["stop"] if last else t["underlying_stop"],
                             "pnl_gross_inr": D.U(last["pnl_unavailable"]) if last and last["pnl_gross_inr"] is None
                             else (last["pnl_gross_inr"] if last else D.U("no monitor decision yet")),
                             "pnl_net_inr": D.U(last["pnl_unavailable"]) if last and last["pnl_net_inr"] is None
                             else (last["pnl_net_inr"] if last else D.U("no monitor decision yet")),
                             "warnings": json.loads(last["warnings"]) if last else [],
                             "thesis": D.U("DATA_UNAVAILABLE: cannot reassess") if last and last["decision"] == P.DATA_UNAVAILABLE
                             else ("INVALIDATED" if last and last["rule_id"] == "STRUCTURAL_INVALIDATION" else
                                   ("NOT_INVALIDATED" if last else D.U("not yet reviewed"))),
                             "alerts": [a for a in al if a["trade_id"] == t["id"] and a["as_of"] <= now]})
            out[led] = rows
    return D.envelope("trades", out, source="ledger.sqlite (Phase 9)", observed_ns=newest, received_ns=None,
                      processed_ns=None, now_ns=now, mode=mode, cfg=cfg(),
                      reason=None if newest else "no monitor decision at or before the view time")


@router.get("/performance")
def performance(ledger: Literal["SIMULATED", "ACTUAL"]):
    now, _ = _now(None)
    db = _ledger_db()
    if db is None:
        data = D.performance(ledger, [])
    else:
        with closing(db):
            data = D.performance(ledger, _closed(db, ledger))
    data["label"] = ledger
    return {"panel": "performance", "ledger": ledger, "now_ns": now, "config_version": cfg().version,
            "data": data, "status": D.OK if data["trades"] else D.UNAVAILABLE,
            "reason": None if data["trades"] else f"no closed {ledger} trades", "provenance": {"source": "ledger.sqlite"}}


def _health(day_dir: Path, now: int, mode: str) -> dict:
    sp = day_dir / "status.json"
    fp = day_dir / "feed_report.json"
    status = json.loads(sp.read_text()) if sp.exists() else None
    feed = json.loads(fp.read_text()) if fp.exists() else None
    data = D.health(status, feed, now, cfg().get("quality.stale_price_s"))
    return D.envelope("health", data, source="recorder status.json + EOD feed_report.json",
                      observed_ns=status.get("ts_ns") if status else None, received_ns=status.get("ts_ns") if status else None,
                      processed_ns=None, now_ns=now, mode=mode, cfg=cfg())


@router.get("/health")
def health(date: str, as_of: int | None = None):
    now, mode = _now(as_of)
    return _health(_day_dir(date), now, mode)


@router.get("/health/stream")
async def health_stream(date: str):
    day_dir = _day_dir(date)

    async def gen():
        while True:
            yield f"data: {json.dumps(_health(day_dir, time.time_ns(), 'LIVE'), default=str)}\n\n"
            await asyncio.sleep(cfg().get("dashboard.sse_interval_s"))
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- POST: Phase 9 journal and feedback (stored only)
class Take(BaseModel):
    date: str
    recommendation_id: str
    price_inr: float = Field(gt=0)
    qty: int = Field(gt=0)
    time: str


class Skip(BaseModel):
    recommendation_id: str
    reason: str = Field(min_length=1, max_length=500)


class Exit(BaseModel):
    trade_id: str
    price_inr: float = Field(gt=0)
    qty: int = Field(gt=0)
    time: str


class FeedbackIn(BaseModel):
    ledger: Literal["SIMULATED", "ACTUAL"]
    recommendation_id: str
    trade_id: str | None = None
    taken: bool
    skip_reason: str | None = Field(default=None, max_length=500)
    actual_entry_inr: float | None = Field(default=None, gt=0)
    actual_exit_inr: float | None = Field(default=None, gt=0)
    slippage_inr_per_unit: float | None = None
    execution_quality: str | None = Field(default=None, max_length=100)
    behaved_as_expected: Literal["yes", "no", "partly"] | None = None
    notes: str = Field(default="", max_length=2000)


def _paise(inr: float | None) -> float | None:
    """The ledger stores paise (exchange integers, F-WS-9); the forms take rupees as typed."""
    return None if inr is None else round(inr * 100, 2)


def _write():
    return L.open_ledger(L.path_of(cfg()))


@router.post("/journal/take")
def take(b: Take):
    db, v = _signals_db(_day_dir(b.date))
    if db is None:
        raise HTTPException(404, "no signals.sqlite for that date")
    with closing(db):
        r = db.execute("SELECT payload FROM recommendations WHERE recommendation_id=? AND config_version=?",
                       (b.recommendation_id, v)).fetchone()
    if r is None:
        raise HTTPException(404, "no such recommendation")
    rec_ns, now = L._ns_of(b.time), time.time_ns()
    t = L.trade_from_payload(json.loads(r["payload"]), P.ACTUAL, f"ACT:{b.recommendation_id}:{now}", _paise(b.price_inr),
                             b.qty, rec_ns, cfg().version)
    w = _write()
    try:
        L.record_taken(w, t, _paise(b.price_inr), b.qty, rec_ns, now)
    finally:
        w.close()
    return {"ok": True, "trade_id": t.id, "ledger": P.ACTUAL}


@router.post("/journal/skip")
def skip(b: Skip):
    w = _write()
    try:
        L.record_skipped(w, b.recommendation_id, b.reason, time.time_ns())
    finally:
        w.close()
    return {"ok": True, "ledger": P.ACTUAL}


@router.post("/journal/exit")
def exit_(b: Exit):
    w = _write()
    try:
        L.record_exit(w, b.trade_id, _paise(b.price_inr), b.qty, L._ns_of(b.time), time.time_ns())
    except ValueError as e:
        raise HTTPException(404, str(e))
    finally:
        w.close()
    return {"ok": True, "ledger": P.ACTUAL}


@router.post("/feedback")
def feedback(b: FeedbackIn):
    try:
        fb = P.Feedback(b.ledger, b.trade_id, b.recommendation_id, b.taken, b.skip_reason, _paise(b.actual_entry_inr),
                        _paise(b.actual_exit_inr), _paise(b.slippage_inr_per_unit), b.execution_quality,
                        b.behaved_as_expected, b.notes)
    except ValueError as e:
        raise HTTPException(422, str(e))
    w = _write()
    try:
        L.record_feedback(w, fb, time.time_ns())
    finally:
        w.close()
    return {"ok": True, "ledger": b.ledger}
