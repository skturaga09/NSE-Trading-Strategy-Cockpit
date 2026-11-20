"""After-close job: dashboard data chain (Phase 8 signals -> Phase 9 paper run -> Phase 10 dashboard export) ->
health summary -> feed report -> compaction -> snapshot compaction -> OI cadence doc ->
Phase 6 opportunity + timing recorder (Q-OPP-6) -> retention.

  python3 -m engine.eod [--config ...]

Idempotent: it compacts every day directory that still has a buffer (so a missed evening is
caught up), regenerates docs/measured-oi-cadence.md over all recorded days, then runs retention.
Refuses to touch anything while a recorder holds the lock. Summary: <root>/eod_last.json.
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from .candles import aggregate
from .compact import compact
from .replay import day_events
from .feed_report import report as feed_report
from .snapshots import compact_snapshots
from .config import load_config
from .health import IST, summary
from .oi_cadence import DEFAULT_OUT, report
from .opportunity import eod as opportunity_eod
from .alerts import alert_once
from .recorder import acquire_lock, last_run_end
from .retention import DAY, run as retention_run
from .universe import Registry
from . import signals


def is_verified_holiday(cfg, d) -> bool:
    """F&O holiday per the calendar, with its circulars re-verified on d (F-NSE-5). Unverified => False."""
    reg = Registry(cfg)
    try:
        return reg.restriction_reasons(d, False, "") == ["HOLIDAY"]
    finally:
        reg.close()


def check_today(cfg, now: datetime, send=None) -> list[str]:
    """Weekday after-close checks: nothing recorded today, or the recorder died and never came back.
    Skipped on weekends and on verified F&O holidays (Q-UNI-4)."""
    if now.weekday() >= 5 or is_verified_holiday(cfg, now.date()):
        return []
    kw = {"send": send} if send else {}
    d = cfg.root / now.date().isoformat()
    buf = d / "buffer.sqlite"
    if not buf.exists():
        if not (d / "parquet").exists():
            alert_once(cfg.root, "no_data", "Engine: NOTHING recorded today",
                       "No recording for today (ignore if NSE was closed). Check dashboard/logs/engine_recorder.err.log", **kw)
            return ["no_data"]
        return []
    db = sqlite3.connect(f"file:{buf}?mode=ro", uri=True)
    try:
        packets = db.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        last, unclean = last_run_end(db)
    finally:
        db.close()
    sent = []
    if packets == 0:
        alert_once(cfg.root, "no_ticks", "Engine: no ticks recorded today", "The recorder ran but stored no ticks.", **kw)
        sent.append("no_ticks")
    if unclean is not None:
        alert_once(cfg.root, f"unclean:{unclean}", "Engine recorder DIED and did not restart",
                   f"Last data {datetime.fromtimestamp(unclean / 1e9, IST):%H:%M:%S} IST; no clean shutdown logged.", **kw)
        sent.append("unclean")
    return sent


# Dashboard data chain, per recorded day, BEFORE compaction: signal_report and the paper run read buffer.sqlite, which a
# verified compaction deletes. Each step is its own process (its memory is freed before compaction, Q-6-5) and is skipped
# once its store records a run for that step's config version (catch-up for missed evenings).
CHAIN = (  # name, module argv, store (day dir, or root for the ledger), done query, input it needs, step it needs first
    ("chain", ["engine.chain_report"], "options.sqlite", "SELECT 1 FROM runs WHERE config_version=?", "buffer", None),
    ("signals", ["engine.signal_report"], "signals.sqlite", "SELECT 1 FROM runs WHERE config_version=?", "buffer", None),
    ("paper", ["engine.ledger", "run"], "../ledger.sqlite", "SELECT 1 FROM runs WHERE config_version=? AND day=?", "buffer",
     "signals"),
    ("dashboard", ["engine.dashboard_export"], "dashboard.sqlite", "SELECT 1 FROM runs WHERE config_version=?", "snapshots",
     None),
)


def _done(path: Path, sql: str, args: tuple) -> bool:
    if not path.exists():
        return False
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return db.execute(sql, args).fetchone() is not None
    except sqlite3.OperationalError:          # store exists but has no runs table yet
        return False
    finally:
        db.close()


# append-only steps that are safe to re-run on a growing day: each run's rows are a prefix of the full day's (Phase 15)
RERUNNABLE = ("chain", "signals", "dashboard")


def dashboard_chain(days: list, runner=subprocess.run, rerun=(), only=None, live=False, timeout=None) -> dict:
    """-> {day: {step: 'done' | 'ok' | 'skipped: ...' | 'error: ...'}}. A step whose prerequisite is not done is skipped.
    Days named in `rerun` run their RERUNNABLE steps even when a run row exists (the intraday job wrote it mid-session).
    `only` limits the run to those step names (the intraday job: never the paper ledger, which is not re-runnable).
    `live` passes --live to the signal step (store nothing after the day's last packet; the intraday job).
    `timeout` (s) overrides the dashboard config's per-step limit (the evening job passes its config's eod.step_timeout_s)."""
    from . import options, paper, signals
    from .dashboard_export import load as load_dashboard
    dcfg = load_dashboard()
    versions = {"chain": options.load().version, "signals": signals.load().version, "paper": paper.load().version,
                "dashboard": dcfg.version}
    timeout = timeout or dcfg.get("dashboard.eod_step_timeout_s")
    out = {}
    for d in days:
        has = {"buffer": (d / "buffer.sqlite").exists(),
               "snapshots": (d / "snapshots.sqlite").exists() or (d / "parquet" / "snapshots").exists()}
        if not any(has.values()):
            continue
        r = out.setdefault(d.name, {})
        for name, argv, store, sql, needs, after in CHAIN:
            if only is not None and name not in only:
                continue
            args = (versions[name], d.name) if "day=?" in sql else (versions[name],)
            if _done((d / store).resolve(), sql, args) and not (d.name in rerun and name in RERUNNABLE):
                r[name] = "done"
            elif not has[needs]:
                r[name] = f"skipped: no {needs} (compacted or not recorded)"
            elif after and r.get(after) not in ("done", "ok"):
                r[name] = f"skipped: {after} not done"
            else:
                try:
                    extra = ["--live"] if live and name == "signals" else []
                    p = runner([sys.executable, "-m", *argv, d.name, *extra], cwd=signals.REPO, capture_output=True, text=True,
                               timeout=timeout)
                    r[name] = "ok" if p.returncode == 0 else f"error: exit {p.returncode}: {(p.stderr or '')[-400:]}"
                except subprocess.TimeoutExpired:
                    r[name] = f"error: timeout after {timeout} s"
    return out


def run(cfg, oi_out=None, send=None, before_compaction=None, now: datetime | None = None) -> dict:
    lock = acquire_lock(cfg.root)
    if lock is None:
        return {"error": "recorder still running (lock held); nothing done"}
    now = now or datetime.now(IST)   # tests pin it (guardrail 11); the CLI passes the wall clock
    out = {"started": now.isoformat(timespec="seconds"), "days": {}}
    try:
        days = sorted(p for p in cfg.root.iterdir() if p.is_dir() and DAY.match(p.name))
        out["alerts"] = check_today(cfg, now, send)
        if before_compaction is not None:   # the CLI passes dashboard_chain; library callers and tests do not
            try:
                out["dashboard_chain"] = before_compaction(days)
            except Exception as e:
                out["dashboard_chain"] = {"error": repr(e)}
        held = held_days(out.get("dashboard_chain", {}), [d.name for d in days])
        for d in days:
            if not (d / "buffer.sqlite").exists():
                continue
            r = out["days"][d.name] = {}
            if d.name in held:   # compaction deletes buffer.sqlite, the only input a failed step can be re-run from
                r["compaction_held"] = held[d.name]
                continue
            if (d / "status.json").exists():
                (d / "health.txt").write_text(summary(d) + "\n")
            try:  # Phase 3: before compaction, while frames.bin and snapshots.sqlite are still there
                (d / "feed_report.json").write_text(json.dumps(feed_report(d), indent=2))
            except Exception as e:
                r["feed_report_error"] = repr(e)
            if (d / "snapshots.sqlite").exists():
                try:  # archive = a full deterministic replay of the day; live differences are listed
                    day = date.fromisoformat(d.name)
                    cap = cfg.values.get("eod", {}).get("replay_check_max_buffer_mb")   # D-75 (v23+); None = always
                    buf = d / "buffer.sqlite"
                    if cap is not None and buf.exists() and buf.stat().st_size > cap * 2 ** 20:
                        r["snapshots"] = {**compact_snapshots(d), "replay_check": f"skipped: buffer above {cap} MB (D-75)"}
                    else:
                        ev = day_events(d, "buffer", control=True)
                        r["snapshots"] = compact_snapshots(d, aggregate(ev, cfg, day, not is_verified_holiday(cfg, day)))
                except Exception as e:  # the SQLite file stays
                    r["snapshots_error"] = repr(e)
            try:
                rep = compact(d)
                r["verified"], r["buffer_deleted"] = rep["verified"], rep["buffer_deleted"]
            except Exception as e:  # keep going for other days; the buffer stays
                r["compact_error"] = repr(e)
        recorded = [d.name for d in days if (d / "parquet").exists() or (d / "buffer.sqlite").exists()]
        if recorded:
            report(cfg, recorded, oi_out or DEFAULT_OUT)
            out["oi_cadence_days"] = recorded
        try:  # after the cadence doc (Phase 4 reads it); per-day failures are inside the result
            out["opportunity"] = opportunity_eod(cfg.root, oi_out or DEFAULT_OUT)
        except Exception as e:
            out["opportunity"] = {"error": repr(e)}
        try:  # e.g. no cloud key: the summary is still written and the phone is told; local files stay
            out["retention"] = retention_run(cfg)
        except Exception as e:
            out["retention"] = {"error": repr(e)}
        kept = retention_problems(out["retention"])
        if kept:
            alert_once(cfg.root, "retention", "Engine archive to cloud FAILED: files kept on the Mac",
                       f"{len(kept)} problem(s), first: {kept[0]}"[:400], **({"send": send} if send else {}))
    finally:
        lock.close()
    (cfg.root / "eod_last.json").write_text(json.dumps(out, indent=2, default=str))
    return out


def trader_test(day_dir: Path, runner=subprocess.run) -> str:
    """scripts/options_trader_test.py for one day (every signal taken as a long option, one lot, on Kite's 1-minute option
    candles, in rupees after charges; D-69 options only) -> <day>/trader_test.md + trader_test.json. Research only."""
    if not (day_dir / "signals.sqlite").exists() or not (day_dir / "buffer.sqlite").exists():
        return "skipped: no signals or no buffer"
    with open(day_dir / "trader_test.md", "w") as md:
        p = runner([sys.executable, str(signals.REPO / "scripts" / "options_trader_test.py"), day_dir.name,
                    "--save", str(day_dir / "trader_test.json")], cwd=signals.REPO, stdout=md, stderr=subprocess.PIPE, text=True)
    return "ok" if p.returncode == 0 else f"error: exit {p.returncode}: {(p.stderr or '')[-300:]}"


BUFFER_STEPS = tuple(name for name, _, _, _, needs, _ in CHAIN if needs == "buffer")


def held_days(chain: dict, days: list) -> dict:
    """Dashboard-chain result -> {day: reason} for days whose buffer must not be compacted yet: a step that reads
    buffer.sqlite failed (or the whole chain raised), so deleting the buffer would lose that day's results for good."""
    if "error" in chain:
        return {d: f"dashboard chain failed: {chain['error']}"[:200] for d in days}
    return {d: f"{s} failed: {v}"[:200] for d, r in chain.items() if isinstance(r, dict)
            for s, v in r.items() if s in BUFFER_STEPS and str(v).startswith("error")}


def _chain_then_trader_test(days: list, today: str, timeout=None) -> dict:
    # a buffer that outlived its evening was held by a failed step: re-run it even though the intraday job wrote a run row
    out = dashboard_chain(days, rerun={today} | {d.name for d in days if (d / "buffer.sqlite").exists()}, timeout=timeout)
    for d in days:
        if d.name == today and isinstance(out.get(today), dict):
            out[today]["trader_test"] = trader_test(d)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.eod")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    now = datetime.now(IST)
    cfg = load_config(a.config) if a.config else load_config()
    limit = cfg.values.get("eod", {}).get("step_timeout_s")   # v25+: a full day's signal step takes ~45 min (2026-11-19)
    out = run(cfg, now=now, before_compaction=lambda days: _chain_then_trader_test(days, now.date().isoformat(), limit))
    print(json.dumps(out, indent=2, default=str))
    return 1 if failed(out) else 0


def retention_problems(ret: dict) -> list[str]:
    """Retention result -> each failure: the step's own error, or a file KEPT locally (upload or checksum failed)."""
    return [str(ret["error"])] if "error" in ret else \
        [f"{k}: {v}" for r in ret.values() if isinstance(r, dict) for k, v in r.items() if "KEPT" in str(v)]


def failed(out: dict) -> bool:
    if retention_problems(out.get("retention", {})):
        return True
    opp, chain = out.get("opportunity", {}), out.get("dashboard_chain", {})
    chain_err = "error" in chain or any(str(v).startswith("error") for r in chain.values() if isinstance(r, dict)
                                        for v in r.values())
    return "error" in out or chain_err or "error" in opp or any("error" in r for r in opp.values() if isinstance(r, dict)) or \
        any("compact_error" in r or not all(r.get("verified", {}).values()) for r in out["days"].values())


if __name__ == "__main__":
    sys.exit(main())
