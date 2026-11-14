"""Phase 10 backend: access control, envelopes (age / STALE / UNAVAILABLE), shaping, per-ledger performance, API reads over
synthetic stores. No live calls; the API functions are called directly (FastAPI's TestClient would need httpx, not installed)."""

import ast
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from starlette.requests import Request

from engine import api as A
from engine import dashboard as D
from engine import ledger as L
from engine import paper as P
from engine import signals as G
from engine.candles import S
from engine.config import EngineConfig
from tests.engine_tests.test_paper import CFG as PCFG, DAY, FUT, LOT, T0, depth, live_feed, quote, run, tick, trade

REPO = Path(__file__).resolve().parents[2]
CFG = A.cfg()


def req(host="127.0.0.1", **headers):
    return Request({"type": "http", "client": (host, 50000), "method": "GET", "path": "/api/engine/x",
                    "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]})


def cfg_root(root: Path) -> EngineConfig:
    v = dict(CFG.values)
    v["storage"] = {**v["storage"], "root": str(root)}
    return EngineConfig(CFG.version, CFG.sha256, v)


class Access(unittest.TestCase):
    def test_loopback_same_origin_only(self):
        A.local_only(req())                                                  # curl on the same machine
        A.local_only(req(sec_fetch_site="same-origin"))                      # the dashboard itself
        A.local_only(req("::1", origin="http://localhost:5173", sec_fetch_site="same-origin"))   # vite dev proxy
        for bad in (req("192.168.1.20"), req(sec_fetch_site="cross-site"), req(sec_fetch_site="same-site"),
                    req(origin="https://evil.example"), req(origin="http://127.0.0.1.evil.example")):
            with self.assertRaises(HTTPException) as e:
                A.local_only(bad)
            self.assertEqual(e.exception.status_code, 403)

    def test_router_requires_the_check_on_every_route(self):
        self.assertIn(A.local_only, [d.dependency for d in A.router.dependencies])
        paths = {r.path for r in A.router.routes}
        self.assertTrue({"/api/engine/radar", "/api/engine/trades", "/api/engine/feedback"} <= paths)

    def test_no_secret_is_read_or_returned(self):
        for f in ("api.py", "dashboard.py", "dashboard_export.py"):
            src = (REPO / "engine" / f).read_text()
            for s in ("kite_config", "access_token", "api_secret", "enctoken", "KiteConnect"):
                self.assertNotIn(s, src, f)

    def test_latest_config_version_is_numeric(self):
        import sqlite3
        db = sqlite3.connect(":memory:")
        db.executescript("CREATE TABLE runs (config_version TEXT); INSERT INTO runs VALUES ('v9'), ('v13'), ('v10');")
        self.assertEqual(A._latest_version(db, "runs"), "v13")             # text order would say v9
        db.close()

    def test_date_is_validated_before_any_path_is_built(self):
        for bad in ("../../etc", "2026-11-6", "2026-13-01", "", "2026-11-06/../x"):
            with self.assertRaises((HTTPException, ValueError)):
                A._day_dir(bad)


class Shaping(unittest.TestCase):
    def test_envelope_age_stale_and_unavailable(self):
        lim = CFG.get("dashboard.stale_after_s")["radar"]
        ok = D.envelope("radar", [], source="s", observed_ns=T0, received_ns=T0, processed_ns=T0, now_ns=T0 + 5 * S,
                        mode="REPLAY", cfg=CFG)
        self.assertEqual((ok["status"], ok["age_s"], ok["provenance"]["tz"]), (D.OK, 5.0, "Asia/Kolkata"))
        st = D.envelope("radar", [], source="s", observed_ns=T0, received_ns=None, processed_ns=None,
                        now_ns=T0 + (lim + 1) * S, mode="LIVE", cfg=CFG)
        self.assertEqual(st["status"], D.STALE)
        self.assertIn("old", st["reason"])
        un = D.envelope("radar", None, source="s", observed_ns=None, received_ns=None, processed_ns=None, now_ns=T0,
                        mode="LIVE", cfg=CFG)
        self.assertEqual((un["status"], un["age_s"]), (D.UNAVAILABLE, None))

    def test_no_look_ahead_in_a_replay(self):
        e = D.envelope("health", {"ticks_per_s": 9.0}, source="status.json", observed_ns=T0 + 300 * S, received_ns=T0 + 300 * S,
                       processed_ns=None, now_ns=T0, mode="REPLAY", cfg=CFG)
        self.assertEqual((e["status"], e["data"], e["age_s"]), (D.UNAVAILABLE, None, None))
        self.assertIn("look-ahead", e["reason"])

    def test_hypothesis_unavailable_vs_evaluated_neutral(self):
        self.assertEqual(D.hypothesis(G.NEUTRAL, ["OI_WINDOW_DISABLED"]),
                         {"UNAVAILABLE": "POSITIONING_UNAVAILABLE: OI_WINDOW_DISABLED"})
        self.assertEqual(D.hypothesis(G.NEUTRAL, ["NOT_SIGNIFICANT"]), G.NEUTRAL)
        self.assertEqual(D.hypothesis(G.LONG_BUILDUP, []), G.LONG_BUILDUP)
        cell = D.positioning_cell("X", {"ts_ns": T0, "hypothesis": G.SHORT_COVERING, "reasons": [], "suppressed": None,
                                        "price_chg_pct": 0.4, "oi_chg_pct": -1.0, "rvol": 2.0})
        self.assertEqual((cell["price_axis"], cell["oi_axis"]), ("PRICE_UP", "OI_DOWN"))

    def test_timeliness_mapping(self):
        self.assertEqual([D.timeliness(x) for x in (
            {"classification": "TIMELY", "reason": "ok"}, {"classification": "TIMELY", "reason": "RETEST"},
            {"classification": "VALID_BUT_LATE"}, {"classification": "EXHAUSTED"}, {"classification": "UNKNOWN"})],
            ["TIMELY", "RETEST", "LATE", "EXHAUSTED", "UNKNOWN"])
        self.assertTrue(D.is_u(D.timeliness({})))


class Performance(unittest.TestCase):
    def t(self, net, k, ledger=P.SIMULATED):
        return {"id": f"t{k}", "ledger": ledger, "net": net, "gross": net + 50, "charges": 50.0, "slippage_inr": 5.0,
                "entry_ns": T0 + k * 60 * S, "exit_ns": T0 + (k * 60 + 30) * S, "family": "E", "underlying": "STK",
                "score_band": "RESEARCH_PRIORITY_LOW", "timeliness": "TIMELY"}

    def test_metrics_for_one_ledger(self):
        m = D.performance(P.SIMULATED, [self.t(300, 0), self.t(-100, 1), self.t(-200, 2), self.t(400, 3)])
        self.assertEqual((m["trades"], m["win_rate"], m["expectancy_inr"], m["profit_factor"], m["max_drawdown_inr"]),
                         (4, 0.5, 100.0, round(700 / 300, 4), 300.0))
        self.assertEqual((m["charges_inr"], m["slippage_inr"], m["net_inr"]), (200.0, 20.0, 400.0))
        self.assertEqual(m["cumulative"][-1]["cumulative_net_inr"], 400.0)
        self.assertTrue(D.is_u(m["by"]["regime"]))
        self.assertEqual(m["by"]["family"]["E"]["trades"], 4)

    def test_empty_ledger_is_unavailable_not_zero(self):
        m = D.performance(P.ACTUAL, [])
        for k in ("win_rate", "expectancy_inr", "profit_factor", "net_inr", "max_drawdown_inr"):
            self.assertTrue(D.is_u(m[k]), k)

    def test_never_mixes_ledgers(self):
        with self.assertRaises(ValueError):
            D.performance(P.SIMULATED, [self.t(1, 0), self.t(2, 1, ledger=P.ACTUAL)])
        src = (REPO / "engine" / "dashboard.py").read_text() + (REPO / "engine" / "api.py").read_text()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.upper().lstrip().startswith("SELECT"):
                self.assertFalse("SIM_" in node.value.upper() and "ACTUAL_" in node.value.upper(), node.value)


class ApiOverStores(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        (self.root / DAY.isoformat()).mkdir()
        self.patch = mock.patch.object(A, "cfg", lambda: cfg_root(self.root))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.td.cleanup()

    def test_missing_stores_are_unavailable_envelopes(self):
        d = DAY.isoformat()
        for f in (A.radar, A.overview, A.positioning, A.health, A.trades):
            e = f(date=d, as_of=T0) if f is not A.trades else f(as_of=T0)
            self.assertEqual(e["status"], D.UNAVAILABLE, f.__name__)
            self.assertTrue(e["data"] is None or all(D.is_u(v) for v in e["data"].values()), f.__name__)
            self.assertTrue(e["reason"])
        with self.assertRaises(HTTPException):
            A.radar(date="2026-11-09")                                      # not recorded

    def test_chain_panel_reads_options_store_with_no_look_ahead(self):
        import json
        import sqlite3
        d = DAY.isoformat()
        e = A.chain(date=d, as_of=T0)
        self.assertEqual(e["status"], D.UNAVAILABLE)
        self.assertIn("no options.sqlite", e["reason"])
        u = {"UNAVAILABLE": "SPREAD_TOO_WIDE_FOR_IV: 12.0 % > 10.0 % (not computed from LTP)"}
        row = lambda kind, k, tok: {"token": tok, "kind": kind, "strike": k, "premium": 1000, "spread_pct": 1.0, "iv": u,  # noqa: E731
                                    "greeks": u, "oi": 5000, "oi_change": u, "volume_day": 10, "depth_bid_qty": 1,
                                    "depth_ask_qty": 1, "hypothesis": "UNCERTAIN", "receive_ns": T0 - 2 * S}
        snap = {"expiry": "2026-11-26", "atm_strike": 100.0,
                "rows": [row("CE", k, i) for i, k in enumerate((99.0, 100.0, 101.0, 102.0))]}
        db = sqlite3.connect(self.root / d / "options.sqlite")
        db.executescript("CREATE TABLE chain_snapshots (underlying TEXT, expiry TEXT, as_of INTEGER, config_version TEXT, payload TEXT);"
                         "CREATE TABLE runs (config_version TEXT PRIMARY KEY, info TEXT);")
        db.execute("INSERT INTO runs VALUES ('v14', '{}')")
        db.execute("INSERT INTO chain_snapshots VALUES ('STK', '2026-11-26', ?, 'v14', ?)", (T0, json.dumps(snap)))
        db.commit()
        db.close()
        early = A.chain(date=d, as_of=T0 - S)
        self.assertEqual(early["status"], D.UNAVAILABLE, "a snapshot after the view time is never shown")
        e = A.chain(date=d, underlying="STK", as_of=T0 + S)
        self.assertEqual((e["status"], e["data"]["underlying"], e["data"]["snapshot_ns"]), (D.OK, "STK", T0))
        self.assertTrue(D.is_u(e["data"]["comparison"]))                   # no recommendation stored
        rec = {"token": 3, "instrument_type": "CE", "expiry": "2026-11-26", "strike": 102.0, "contract": "STK102CE"}
        cmp_ = D.chain_view([snap], rec)["comparison"]
        self.assertEqual([(r["strike"], r["role"], r["selected"]) for r in cmp_],
                         [(99.0, "ITM", False), (100.0, "ATM", False), (101.0, "OTM", False), (102.0, "SELECTED", True)])
        self.assertEqual(cmp_[0]["iv"], u)                                   # copied, never recomputed

    def test_trades_and_performance_are_per_ledger(self):
        db = L.open_ledger(L.path_of(cfg_root(self.root)))
        sim, act = trade(tid="s1"), trade(ledger=P.ACTUAL, tid="a1")
        L.add_sim_trade(db, sim, P.paper_fill("BUY", 100, LOT, quote(FUT, 100000, 100010, T0 - S), T0, PCFG))
        L.record_taken(db, act, fill_price=100020.0, qty=100, filled_ns=T0, recorded_ns=T0 + S)
        ev = live_feed(T0, T0 + 5 * S) + [tick(FUT, 98990, T0 + 6 * S), depth(FUT, 98985, 98995, T0 + 6 * S)]
        L.store_result(db, run([sim], ev))
        db.close()
        e = A.trades(date=DAY.isoformat(), as_of=T0 + 10 * S)
        self.assertEqual([t["id"] for t in e["data"]["SIMULATED"]], ["s1"])
        self.assertEqual([t["id"] for t in e["data"]["ACTUAL"]], ["a1"])
        self.assertEqual(e["data"]["SIMULATED"][0]["decision"], P.EXIT_REQUIRED)
        self.assertTrue(D.is_u(e["data"]["ACTUAL"][0]["decision"]))       # no monitor run for it: no invented status
        early = A.trades(date=DAY.isoformat(), as_of=T0 + 3 * S)            # replay: nothing after the view time
        self.assertTrue(D.is_u(early["data"]["SIMULATED"][0]["decision"]) or
                        early["data"]["SIMULATED"][0]["decision"] != P.EXIT_REQUIRED)
        ps, pa = A.performance("SIMULATED"), A.performance("ACTUAL")
        self.assertEqual((ps["data"]["trades"], ps["data"]["label"]), (1, "SIMULATED"))
        self.assertEqual((pa["data"]["trades"], pa["status"]), (0, D.UNAVAILABLE))

    def test_feedback_post_stores_and_changes_no_config(self):
        before = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in (REPO / "config").rglob("*") if f.is_file()}
        out = A.feedback(A.FeedbackIn(ledger="ACTUAL", recommendation_id="r1", taken=False, skip_reason="spread",
                                      behaved_as_expected=None, notes="n"))
        self.assertEqual(out, {"ok": True, "ledger": "ACTUAL"})
        db = L.open_ledger(L.path_of(cfg_root(self.root)))
        self.assertEqual(L.feedback(db, P.ACTUAL)[0]["skip_reason"], "spread")
        db.close()
        after = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in (REPO / "config").rglob("*") if f.is_file()}
        self.assertEqual(before, after)
        with self.assertRaises(HTTPException):
            A.feedback(A.FeedbackIn(ledger="ACTUAL", recommendation_id="r1", taken=True, behaved_as_expected=None))

    def test_health_from_status_files(self):
        import json
        day = self.root / DAY.isoformat()
        (day / "status.json").write_text(json.dumps({"ts_ns": T0, "connections": {"1": "connected"}, "ticks_per_s": 12.5,
                                                     "instruments": {"1": {"symbol": "NFO:X", "last_receive_ns": T0 - 60 * S},
                                                                     "2": {"symbol": "NFO:Y", "last_receive_ns": T0}}}))
        e = A.health(date=DAY.isoformat(), as_of=T0 + S)
        self.assertEqual((e["status"], e["data"]["stale_instruments"], e["data"]["ticks_per_s"]), (D.OK, 1, 12.5))
        self.assertTrue(D.is_u(e["data"]["allocator"]))
        self.assertEqual(replace(CFG).version, "v14")   # Phase 11: the API reads v14 (chain stale threshold)


if __name__ == "__main__":
    unittest.main()


class EodDashboardChain(unittest.TestCase):
    """engine.eod runs Phase 8 -> 9 -> dashboard export per recorded day, before compaction, as subprocesses."""

    def setUp(self):
        import subprocess
        from engine import eod
        self.eod, self.sp = eod, subprocess
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.calls = []

    def tearDown(self):
        self.td.cleanup()

    def day(self, name, buffer=True, snapshots="sqlite"):
        d = self.root / name
        d.mkdir()
        if buffer:
            (d / "buffer.sqlite").touch()
        if snapshots == "sqlite":
            (d / "snapshots.sqlite").touch()
        elif snapshots == "parquet":
            (d / "parquet" / "snapshots").mkdir(parents=True)
        return d

    def runner(self, fail=()):
        def run(argv, **kw):
            self.calls.append((argv[2:], kw["cwd"]))
            return self.sp.CompletedProcess(argv, 1 if argv[2] in fail else 0, "", "boom" if argv[2] in fail else "")
        return run

    def test_order_skips_and_dependencies(self):
        live = self.day("2026-11-06")
        self.day("2026-11-09", buffer=False, snapshots="parquet")        # compacted: no buffer any more
        self.day("2026-11-10", buffer=False, snapshots=None)             # nothing usable
        out = self.eod.dashboard_chain(sorted(self.root.iterdir()), runner=self.runner())
        self.assertEqual([c[0] for c in self.calls], [["engine.chain_report", "2026-11-06"],     # Phase 11 step first
                                                      ["engine.signal_report", "2026-11-06"], ["engine.ledger", "run", "2026-11-06"],
                                                      ["engine.dashboard_export", "2026-11-06"], ["engine.dashboard_export", "2026-11-09"]])
        self.assertTrue(all(cwd == G.REPO for _, cwd in self.calls))
        self.assertEqual(out["2026-11-06"], {"chain": "ok", "signals": "ok", "paper": "ok", "dashboard": "ok"})
        self.assertEqual(out["2026-11-09"]["signals"], "skipped: no buffer (compacted or not recorded)")
        self.assertEqual(out["2026-11-09"]["dashboard"], "ok")          # the export does not need Phase 8
        self.assertNotIn("2026-11-10", out)
        self.assertFalse(self.eod.failed({"days": {}, "dashboard_chain": out}))
        del live

    def test_done_steps_are_not_rerun(self):
        import sqlite3
        d = self.day("2026-11-06")
        db = sqlite3.connect(d / "signals.sqlite")
        db.execute("CREATE TABLE runs (config_version TEXT PRIMARY KEY)")
        db.execute("INSERT INTO runs VALUES (?)", (G.load().version,))
        db.commit()
        db.close()
        out = self.eod.dashboard_chain([d], runner=self.runner())
        self.assertEqual(out["2026-11-06"]["signals"], "done")
        self.assertNotIn(["engine.signal_report", "2026-11-06"], [c[0] for c in self.calls])

    def test_today_reruns_append_only_steps_but_never_the_paper_ledger(self):
        import sqlite3
        d = self.day("2026-11-06")
        db = sqlite3.connect(d / "signals.sqlite")
        db.execute("CREATE TABLE runs (config_version TEXT PRIMARY KEY)")
        db.execute("INSERT INTO runs VALUES (?)", (G.load().version,))   # an intraday run already wrote today's row
        db.commit()
        db.close()
        out = self.eod.dashboard_chain([d], runner=self.runner(), rerun={"2026-11-06"}, only=self.eod.RERUNNABLE, live=True)
        self.assertEqual(out["2026-11-06"], {"chain": "ok", "signals": "ok", "dashboard": "ok"})   # re-run, no "done"
        self.assertIn(["engine.signal_report", "2026-11-06", "--live"], [c[0] for c in self.calls])
        self.assertNotIn(["engine.ledger", "run", "2026-11-06"], [c[0] for c in self.calls])
        self.assertNotIn("paper", self.eod.RERUNNABLE)

    def test_eod_trader_test_runs_before_compaction_and_saves_its_report(self):
        d = self.day("2026-11-06")
        self.assertEqual(self.eod.trader_test(d, runner=self.runner()), "skipped: no signals or no buffer")
        (d / "signals.sqlite").touch()
        seen = []

        def run(argv, **kw):
            seen.append(argv)
            kw["stdout"].write("# report")
            return self.sp.CompletedProcess(argv, 0, "", "")
        self.assertEqual(self.eod.trader_test(d, runner=run), "ok")
        self.assertTrue(seen[0][1].endswith("scripts/options_trader_test.py"))
        self.assertEqual(seen[0][2:], ["2026-11-06", "--save", str(d / "trader_test.json")])
        self.assertEqual((d / "trader_test.md").read_text(), "# report")

    def test_intraday_runs_only_during_a_live_session(self):
        from engine import intraday
        from engine.recorder import acquire_lock
        from tests.engine_tests.fixtures import make_config
        cfg, now, seen = make_config(self.root), datetime(2026, 11, 6, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")), []
        chain = lambda days, **kw: seen.append(([x.name for x in days], kw)) or {"ok": True}
        self.assertEqual(intraday.run(cfg, now, chain), {"skipped": "recorder not running"})
        lock = acquire_lock(self.root)                                   # the recorder is live
        try:
            self.assertEqual(intraday.run(cfg, now, chain), {"skipped": "no buffer for 2026-11-06"})
            self.day("2026-11-06")
            self.assertEqual(intraday.run(cfg, now, chain), {"ok": True})
        finally:
            lock.close()
        self.assertEqual(seen, [(["2026-11-06"], {"rerun": {"2026-11-06"}, "only": self.eod.RERUNNABLE, "live": True})])

    def test_failure_skips_dependents_and_fails_the_job(self):
        d = self.day("2026-11-06")
        out = self.eod.dashboard_chain([d], runner=self.runner(fail=("engine.signal_report",)))
        r = out["2026-11-06"]
        self.assertTrue(r["signals"].startswith("error: exit 1"))
        self.assertEqual(r["paper"], "skipped: signals not done")
        self.assertEqual(r["dashboard"], "ok")
        self.assertTrue(self.eod.failed({"days": {}, "dashboard_chain": out}))

    def test_eod_runs_the_chain_before_compaction(self):
        from tests.engine_tests.fixtures import make_config
        from tests.engine_tests.test_storage import record_day
        record_day(self.root, "2026-11-06", n=30)
        seen = {}

        def chain(days):
            seen.update({d.name: (d / "buffer.sqlite").exists() for d in days})
            return {"ok": True}
        out = self.eod.run(make_config(self.root, **{"retention.archive_target": str(self.root / "arch")}),
                           oi_out=self.root / "oi.md", send=lambda *a, **k: {"success": True}, before_compaction=chain)
        self.assertEqual(seen, {"2026-11-06": True})                   # buffer still there when the chain ran
        self.assertEqual(out["dashboard_chain"], {"ok": True})
        self.assertTrue(out["days"]["2026-11-06"]["buffer_deleted"])     # and compaction still happened after it
