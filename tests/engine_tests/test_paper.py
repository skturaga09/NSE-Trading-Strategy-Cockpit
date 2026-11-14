"""Phase 9: paper broker, actual-trade journal, live monitor, alerts, feedback. Synthetic fixtures only, no live calls."""

import ast
import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine import ledger as L
from engine import paper as P
from engine.config import EngineConfig
from engine import signals as G
from engine.candles import S, Unavailable, _ns
from engine.contracts import Quote
from engine.store import Event

REPO = Path(__file__).resolve().parents[2]
CFG = P.load()
DAY = date(2026, 11, 6)
T0 = _ns(DAY, "11:00")
FUT, CE = 101, 201
LOT = 100


def trade(kind="FUT", ledger=P.SIMULATED, qty=100, entry=100010.0, tid="t1", family="E", direction=1, contract_stop=None):
    tok = FUT if kind == "FUT" else CE
    stop = 99000 if direction > 0 else 101000
    return P.Trade(tid, ledger, f"rec-{tid}", f"sig-{tid}", "STK", family, direction, DAY, FUT, tok, kind,
                   "BUY" if direction > 0 or kind != "FUT" else "SELL", qty, LOT, entry, T0,
                   100000, stop, contract_stop if contract_stop is not None else (stop if kind == "FUT" else 1400.0),
                   103000 if direction > 0 else 97000, None, CFG.version)


def tick(tok, ltp, t, oi=None):
    return Event(t // S, t, 1, 0, "tick", tok, (("ltp", ltp), ("oi", oi), ("volume", 1000)))


def depth(tok, bid, ask, t, qty=500, levels=5, step=5):
    d = {}
    for i in range(5):
        on = i < levels
        d.update({f"b{i}_price": bid - i * step if on else 0, f"b{i}_qty": qty if on else 0, f"b{i}_orders": 1,
                  f"s{i}_price": ask + i * step if on else 0, f"s{i}_qty": qty if on else 0, f"s{i}_orders": 1})
    return Event(t // S, t, 1, 0, "depth", tok, tuple(d.items()))


def gap(start, end):
    return Event(None, end, -1, 0, "gap", -1, (("start_ns", start), ("end_ns", end), ("conn", -1), ("kind", "disconnect"),
                                              ("reason", "socket closed"), ("count", None)))


def quote(tok, bid, ask, t, qty=500, levels=5, step=5, depth_=True):
    side = lambda p, s: tuple((p + s * i * step, qty, 1) for i in range(levels))  # noqa: E731
    return Quote(tok, side(bid, -1), side(ask, 1), depth_, (bid + ask) // 2, 1000, 1000, t, t, "fixture")


def active(t, close=100200, state="ACTIVE", classification="TIMELY", flags=(), positioning=Unavailable("fixture"),
           swings=(), opposite=(), vwap=99900):
    obs = P.Obs("close_1m", FUT, close, t - 15 * S, t - 15 * S, "fixture: Phase 6 evaluation price")
    return P.ReviewInputs(t, state, obs, classification, flags, positioning, vwap, swings, opposite)


def live_feed(start, end, every_s=1, und=100100, prem=None, tok_c=None):
    """A healthy feed: a tick and a book every second for the price token (and the contract, if different)."""
    out, t = [], start
    while t <= end:
        out += [tick(FUT, und, t), depth(FUT, und - 5, und + 5, t)]
        if tok_c is not None:
            out += [tick(tok_c, prem, t), depth(tok_c, prem - 5, prem + 5, t)]
        t += every_s * S
    return out


def run(trades, events, inputs=None, realized=None, cfg=CFG):
    inputs = inputs or (lambda tid, t: active(t))
    return P.run_trades(trades, sorted(events, key=lambda e: (e.receive_ns, e.kind)), inputs, cfg, realized)


class PaperBroker(unittest.TestCase):
    def test_no_quote_no_fill(self):
        for q, why in ((None, "NO_QUOTE"), (quote(FUT, 100000, 100010, T0 - 60 * S), "STALE_QUOTE"),
                       (quote(FUT, 100010, 100000, T0), "CROSSED_OR_LOCKED_BOOK")):
            f = P.paper_fill("BUY", 100, LOT, q, T0, CFG)
            self.assertIsInstance(f, Unavailable)
            self.assertTrue(f.reason.startswith("NO_FILL"), f.reason)
            self.assertIn(why, f.reason)

    def test_buy_at_ask_sell_at_bid_with_quote_snapshot_and_label(self):
        q = quote(FUT, 100000, 100010, T0 - S)
        b, s = P.paper_fill("BUY", 100, LOT, q, T0, CFG), P.paper_fill("SELL", 100, LOT, q, T0, CFG)
        self.assertEqual((b.avg_price, s.avg_price), (100010, 100000))
        self.assertEqual((b.label, b.qty_filled, b.partial), (P.SIMULATED, 100, False))
        self.assertEqual(b.quote["asks"][0], [100010, 500, 1])       # the snapshot used is stored with the fill
        self.assertEqual(b.quote["receive_ns"], T0 - S)

    def test_partial_fill_when_visible_depth_is_short(self):
        q = quote(FUT, 100000, 100010, T0 - S, qty=100, levels=3)   # 300 units visible on the ask
        f = P.paper_fill("BUY", 500, LOT, q, T0, CFG)
        self.assertEqual((f.qty_requested, f.qty_filled, f.partial), (500, 300, True))
        self.assertAlmostEqual(f.avg_price, (100010 + 100015 + 100020) / 3)
        for bad in (None, 0, -100):
            self.assertIn("no sized quantity", P.paper_fill("BUY", bad, LOT, q, T0, CFG).reason)
        thin = quote(FUT, 100000, 100010, T0 - S, qty=50, levels=1)   # less than one lot
        self.assertIsInstance(P.paper_fill("BUY", 100, LOT, thin, T0, CFG), Unavailable)

    def test_touch_only_quote_fills_touch_qty_with_estimated_slippage(self):
        q = quote(FUT, 100000, 100010, T0 - S, qty=200, levels=1, depth_=False)
        f = P.paper_fill("BUY", 500, LOT, q, T0, CFG)
        self.assertEqual((f.qty_filled, f.method), (200, "ESTIMATED_SPREAD_MULTIPLE"))
        self.assertGreaterEqual(f.avg_price, 100010 - 5)


class Monitor(unittest.TestCase):
    def test_stop_breach_exits_on_the_breaching_tick_not_at_the_review(self):
        breach = T0 + 37 * S
        ev = live_feed(T0, T0 + 36 * S) + [tick(FUT, 98990, breach), depth(FUT, 98985, 98995, breach)] + \
            live_feed(T0 + 38 * S, T0 + 400 * S, und=98990)
        res = run([trade()], ev)
        exits = [d for d in res.decisions if d.decision == P.EXIT_REQUIRED]
        self.assertEqual(exits[0].as_of, breach)
        self.assertEqual(exits[0].rule_id, "HARD_STOP_UNDERLYING")
        o = next(o for o in exits[0].observations if o.field == "ltp")
        self.assertEqual((o.token, o.value, o.receive_ns), (FUT, 98990, breach))
        self.assertLess(exits[0].as_of, T0 + CFG.get("monitor.review_interval_s") * S)
        self.assertEqual(len(exits), 1)                                    # terminal: nothing after it
        self.assertEqual(res.decisions[-1].decision, P.EXIT_REQUIRED)

    def test_tick_equal_to_stop_exits(self):
        res = run([trade()], live_feed(T0, T0 + 5 * S) + [tick(FUT, 99000, T0 + 6 * S)])
        self.assertEqual(res.decisions[-1].rule_id, "HARD_STOP_UNDERLYING")

    def test_short_trade_stop_is_above(self):
        res = run([trade(direction=-1, entry=99990.0)], live_feed(T0, T0 + 5 * S) + [tick(FUT, 101000, T0 + 6 * S)])
        self.assertEqual(res.decisions[-1].rule_id, "HARD_STOP_UNDERLYING")

    def test_brief_premium_dip_with_intact_structure_holds(self):
        t = trade("CE", qty=100, entry=1500.0)                     # contract stop estimate 1400 (APPROXIMATE)
        ev = live_feed(T0, T0 + 120 * S, und=100100, prem=1500, tok_c=CE) + \
            live_feed(T0 + 121 * S, T0 + 150 * S, und=99500, prem=1350, tok_c=CE) + \
            live_feed(T0 + 151 * S, T0 + 320 * S, und=100100, prem=1490, tok_c=CE)
        res = run([t], ev)
        self.assertNotIn(P.EXIT_REQUIRED, [d.decision for d in res.decisions])
        self.assertEqual(res.decisions[-1].decision, P.HOLD)
        self.assertTrue(any("CONTRACT_BELOW_STOP_ESTIMATE" in w for d in res.decisions for w in d.warnings))

    def test_futures_contract_stop_is_a_hard_stop(self):
        t = trade(contract_stop=99500)
        res = run([t], live_feed(T0, T0 + 5 * S) + [tick(FUT, 99400, T0 + 6 * S)])
        self.assertIn(res.decisions[-1].rule_id, ("HARD_STOP_CONTRACT", "HARD_STOP_UNDERLYING"))
        self.assertEqual(res.decisions[-1].decision, P.EXIT_REQUIRED)

    def test_squareoff_cutoff(self):
        cut = _ns(DAY, CFG.get("monitor.squareoff_cutoff"))
        res = run([trade()], live_feed(cut - 10 * S, cut + 5 * S))
        x = [d for d in res.decisions if d.decision == P.EXIT_REQUIRED]
        self.assertEqual((x[0].rule_id, x[0].as_of), ("SQUAREOFF_CUTOFF", cut))

    def test_max_loss_per_trade_on_net_pnl(self):
        # sized on a 2,000 limit (v18 default 10,000 sits above the 6,000 daily-loss exit, which would fire first)
        cfg = EngineConfig(CFG.version, CFG.sha256, {**CFG.values, "risk": {**CFG.values["risk"], "max_risk_per_trade_inr": 2000}})
        t = trade(qty=1000, entry=100010.0)                        # 1,000 units: a ₹2 adverse move = ₹2,000 gross
        res = run([t], live_feed(T0, T0 + 5 * S) + live_feed(T0 + 6 * S, T0 + 8 * S, und=99820), cfg=cfg)
        x = [d for d in res.decisions if d.decision == P.EXIT_REQUIRED]
        self.assertEqual(x[0].rule_id, "MAX_LOSS_PER_TRADE")
        self.assertLessEqual(x[0].pnl_net_inr, -cfg.get("risk.max_risk_per_trade_inr"))

    def test_daily_loss_limit_on_the_ledger(self):
        res = run([trade()], live_feed(T0, T0 + 5 * S, und=99900), realized={P.SIMULATED: 50.0 - CFG.get("risk.max_daily_loss_inr")})  # ₹50 short of the cap
        x = [d for d in res.decisions if d.decision == P.EXIT_REQUIRED]
        self.assertEqual(x[0].rule_id, "DAILY_LOSS_LIMIT")

    def test_feed_disconnect_is_data_unavailable_without_pnl(self):
        ev = live_feed(T0, T0 + 30 * S) + [gap(T0 + 31 * S, T0 + 90 * S)] + live_feed(T0 + 91 * S, T0 + 95 * S)
        res = run([trade()], ev)
        d = next(d for d in res.decisions if d.decision == P.DATA_UNAVAILABLE)
        self.assertEqual((d.rule_id, d.as_of), ("FEED_GAP", T0 + 90 * S))
        self.assertIsInstance(d.pnl_gross_inr, Unavailable)
        self.assertIsInstance(d.pnl_net_inr, Unavailable)
        self.assertEqual(next(o for o in d.observations if o.field == "gap").value["start_ns"], T0 + 31 * S)
        a = next(a for a in res.alerts if a.decision == P.DATA_UNAVAILABLE)
        self.assertIn("DATA_UNAVAILABLE", a.message)
        self.assertNotIn(P.HOLD, [x.decision for x in res.decisions if x.as_of > d.as_of])  # stays until the next review

    def test_disconnect_with_a_fresh_book_still_shows_no_pnl(self):
        close = Event(None, T0 + 10 * S + 1, 1, 0, "conn", -1, (("event", "close"), ("detail", "1006")))
        res = run([trade()], live_feed(T0, T0 + 10 * S) + [close])
        d = res.decisions[-1]
        self.assertEqual((d.decision, d.rule_id), (P.DATA_UNAVAILABLE, "FEED_DISCONNECT"))
        self.assertIsInstance(d.pnl_gross_inr, Unavailable)
        self.assertIsInstance(d.pnl_net_inr, Unavailable)

    def test_daily_loss_is_per_ledger_never_summed(self):
        sim, act = trade(tid="s"), trade(ledger=P.ACTUAL, tid="a")
        res = run([sim, act], live_feed(T0, T0 + 5 * S, und=99900), realized={P.ACTUAL: 50.0 - CFG.get("risk.max_daily_loss_inr")})  # ₹50 short of the cap
        exits = {d.trade_id: d.rule_id for d in res.decisions if d.decision == P.EXIT_REQUIRED}
        self.assertEqual(exits, {"a": "DAILY_LOSS_LIMIT"})

    def test_silent_feed_goes_stale(self):
        ev = live_feed(T0, T0 + 10 * S) + [tick(999, 5, T0 + 40 * S)]   # another token ticks; ours went quiet
        res = run([trade()], ev)
        d = next(d for d in res.decisions if d.decision == P.DATA_UNAVAILABLE)
        self.assertEqual(d.rule_id, "STALE_PRICE")
        self.assertIsInstance(d.pnl_net_inr, Unavailable)

    def test_review_rules(self):
        rv = CFG.get("monitor.review_interval_s") * S
        cases = {
            "STRUCTURAL_INVALIDATION": (lambda tid, t: active(t, close=98990, state="INVALIDATED"), P.EXIT_REQUIRED),
            "THESIS_INPUT_UNAVAILABLE": (lambda tid, t: P.ReviewInputs(t, Unavailable("no evaluation"), Unavailable("x"),
                                                                        None, (), Unavailable("x"), 99900, (), ()),
                                         P.DATA_UNAVAILABLE),
            "NO_EXIT_RULE": (lambda tid, t: active(t, flags=("VWAP_EXTENSION",), classification="EXHAUSTED",
                                                    positioning=G.SHORT_BUILDUP, opposite=("rec-x",), vwap=100500),
                              P.HOLD),
        }
        for rule, (inputs, want) in cases.items():
            res = run([trade()], live_feed(T0, T0 + rv + 2 * S), inputs)
            d = next(d for d in res.decisions if d.as_of >= T0 + rv and d.rule_id != "ENTRY")
            self.assertEqual((d.decision, d.rule_id), (want, rule))
        hold = next(d for d in res.decisions if d.rule_id == "NO_EXIT_RULE")
        self.assertTrue({"OPPOSITE_POSITIONING", "EXHAUSTION", "VWAP_WRONG_SIDE", "OPPOSITE_SIGNAL"} <=
                        {w.split(":")[0] for w in hold.warnings})

    def test_positioning_family_needs_positioning(self):
        rv = CFG.get("monitor.review_interval_s") * S
        res = run([trade(family="A")], live_feed(T0, T0 + rv + 2 * S))
        self.assertEqual(res.decisions[-1].decision, P.DATA_UNAVAILABLE)

    def test_tighten_breakeven_trail_and_t1(self):
        rv = CFG.get("monitor.review_interval_s") * S
        res = run([trade()], live_feed(T0, T0 + rv + 2 * S, und=101100))         # +1.1R
        d = next(d for d in res.decisions if d.decision == P.TIGHTEN_STOP)
        self.assertEqual((d.rule_id, d.stop), ("BREAKEVEN_AT_1R", 100000))
        swing = ("SWING_LOW", "5m", 100500, T0 + 60 * S, "sw1")
        res = run([trade()], live_feed(T0, T0 + rv + 2 * S, und=101100), lambda tid, t: active(t, swings=(swing,)))
        d = next(d for d in res.decisions if d.decision == P.TIGHTEN_STOP)
        self.assertEqual((d.rule_id, d.stop), ("TRAIL_CONFIRMED_SWING", 100500))
        res = run([trade()], live_feed(T0, T0 + 5 * S) + [tick(FUT, 103000, T0 + 6 * S)])
        d = next(d for d in res.decisions if d.decision == P.PARTIAL_EXIT_CANDIDATE)
        self.assertEqual(d.rule_id, "T1_REACHED")
        # after tightening, a tick through the new stop exits
        res = run([trade()], live_feed(T0, T0 + rv + 2 * S, und=101100) + [tick(FUT, 100000, T0 + rv + 3 * S)])
        self.assertEqual(res.decisions[-1].rule_id, "HARD_STOP_UNDERLYING")

    def test_fresh_oi_change_triggers_a_review(self):
        ev = live_feed(T0, T0 + 20 * S) + [tick(FUT, 100100, T0 + 21 * S, oi=5000), tick(FUT, 100100, T0 + 22 * S, oi=5100)]
        res = run([trade()], ev)
        self.assertTrue(any(d.rule_id == "NO_EXIT_RULE" and d.as_of == T0 + 22 * S for d in res.decisions))

    def test_alerts_only_on_change_with_observations_and_rule(self):
        rv = CFG.get("monitor.review_interval_s") * S
        res = run([trade()], live_feed(T0, T0 + 3 * rv))
        self.assertGreaterEqual(sum(d.rule_id == "NO_EXIT_RULE" for d in res.decisions), 3)
        self.assertEqual([a.decision for a in res.alerts], [P.HOLD])          # HOLD, HOLD, HOLD ⇒ one alert
        for a in res.alerts:
            self.assertTrue(a.rule_id and a.observations)
            self.assertTrue(all(o.receive_ns is not None and o.value is not None for o in a.observations))

    def test_paper_exit_fills_at_bid_and_lifecycle_is_legal(self):
        ev = live_feed(T0, T0 + 5 * S) + [tick(FUT, 98990, T0 + 6 * S), depth(FUT, 98985, 98995, T0 + 6 * S)]
        res = run([trade()], ev)
        self.assertEqual([(f.side, f.avg_price) for f in res.fills], [("SELL", 98985)])
        states = [(r.from_state, r.to_state) for r in res.lifecycle]
        self.assertEqual(states, [(G.ENTRY_ELIGIBLE, G.TRIGGERED), (G.TRIGGERED, G.ACTIVE), (G.ACTIVE, G.EXIT_REQUIRED)])
        self.assertTrue(all(b in G.ALLOWED[a] for a, b in states))

    def test_actual_trades_get_decisions_but_no_simulated_fills(self):
        ev = live_feed(T0, T0 + 5 * S) + [tick(FUT, 98990, T0 + 6 * S), depth(FUT, 98985, 98995, T0 + 6 * S)]
        res = run([trade(ledger=P.ACTUAL)], ev)
        self.assertEqual(res.decisions[-1].decision, P.EXIT_REQUIRED)
        self.assertEqual(res.fills, [])
        self.assertTrue(all(d.ledger == P.ACTUAL for d in res.decisions))

    def test_monitor_is_pure(self):
        src = (REPO / "engine" / "paper.py").read_text()
        for bad in ("datetime.now", "time.time", "sqlite3", "requests", "open(", "urlopen"):
            self.assertNotIn(bad, src)


class Risk(unittest.TestCase):
    def test_both_ledgers_checked_separately(self):
        from tests.engine_tests.test_contracts_risk import FLAT, cfg_with, select
        cfg = cfg_with(contracts__futures_margin__fraction=0.2)
        c = next(c for c in select(cfg=cfg).candidates if c.status == "ELIGIBLE" and c.kind == "FUT")
        ok = P.risk_both(c, FLAT, FLAT, cfg)
        self.assertTrue(ok.approved, [d.reasons for d in (ok.simulated, ok.actual)])
        lossy = FLAT.__class__(**{**FLAT.__dict__, "realized_pnl_inr": -7000.0, "worst_day_pnl_inr": -7000.0})
        for sim, act in ((lossy, FLAT), (FLAT, lossy)):
            r = P.risk_both(c, sim, act, cfg)
            self.assertFalse(r.approved)
        r = P.risk_both(c, FLAT, lossy, cfg)
        self.assertEqual((r.simulated.status, r.actual.status), ("APPROVED", "REJECTED"))
        self.assertTrue(any(x.startswith("DAILY_LOSS_LIMIT") for x in r.actual.reasons))


class Ledger(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.db = L.open_ledger(Path(self.td.name) / "ledger.sqlite")

    def tearDown(self):
        self.db.close()
        self.td.cleanup()

    def test_ledgers_are_separate_tables_and_queryable_separately(self):
        sim, act = trade(tid="s1"), trade(ledger=P.ACTUAL, tid="a1")
        L.add_sim_trade(self.db, sim, P.paper_fill("BUY", 100, LOT, quote(FUT, 100000, 100010, T0 - S), T0, CFG))
        L.record_taken(self.db, act, fill_price=100020.0, qty=100, filled_ns=T0, recorded_ns=T0 + S)
        L.record_skipped(self.db, "rec-z", "spread too wide", recorded_ns=T0 + S)
        self.assertEqual([t["id"] for t in L.trades(self.db, P.SIMULATED)], ["s1"])
        self.assertEqual([t["id"] for t in L.trades(self.db, P.ACTUAL)], ["a1"])
        self.assertEqual(L.trades(self.db, P.SIMULATED)[0]["label"], P.SIMULATED)
        self.assertEqual(L.trades(self.db, P.ACTUAL)[0]["label"], P.ACTUAL)
        for bad in (None, "", "BOTH", "SIMULATED' OR 1=1 --"):
            with self.assertRaises(ValueError):
                L.trades(self.db, bad)
            with self.assertRaises(ValueError):
                L.summary(self.db, bad)
        self.assertEqual(L.summary(self.db, P.ACTUAL)["ledger"], P.ACTUAL)

    def test_no_query_joins_the_ledgers_or_reads_shared_tables_without_a_ledger_filter(self):
        shared = ("monitor_decisions", "alerts", "feedback", "lifecycle")
        seen = 0
        for path in (REPO / "engine" / "ledger.py", REPO / "engine" / "paper.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.JoinedStr):       # an f-string can hide a table name from this scan
                    text = "".join(v.value for v in node.values if isinstance(v, ast.Constant)).upper()
                    self.assertFalse(text.lstrip().startswith(("SELECT", "INSERT", "WITH")) and
                                     any(k in text for k in ("SIM_", "ACTUAL_", *map(str.upper, shared))),
                                     f"{path.name}: ledger SQL built with an f-string")
                if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                sql = node.value.upper().lstrip()
                head = sql.split(" ", 1)[0]
                if head not in ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH"):
                    continue
                seen += 1
                self.assertNotIn(head, ("UPDATE", "DELETE"), f"{path.name}: append-only store: {node.value}")
                self.assertFalse("SIM_" in sql and "ACTUAL_" in sql, f"{path.name}: joins both ledgers: {node.value}")
                if head in ("SELECT", "WITH") and any(t.upper() in sql for t in shared):
                    self.assertIn("LEDGER=?", sql.replace(" ", ""), f"{path.name}: no ledger filter: {node.value}")
        self.assertGreaterEqual(seen, 15)                  # the scan really read the ledger queries

    def test_feedback_is_stored_and_changes_no_config(self):
        files = sorted((REPO / "config").rglob("*"))
        before = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}
        act = trade(ledger=P.ACTUAL, tid="a1")
        L.record_taken(self.db, act, fill_price=100020.0, qty=100, filled_ns=T0, recorded_ns=T0 + S)
        L.record_feedback(self.db, P.Feedback(P.ACTUAL, "a1", "rec-a1", True, None, 100020.0, 101000.0, 10.0, "GOOD",
                                              "partly", "filled late"), recorded_ns=T0 + 2 * S)
        with self.assertRaises(ValueError):
            P.Feedback(P.ACTUAL, "a1", "rec-a1", True, None, None, None, None, None, "maybe", "")
        self.assertEqual(L.feedback(self.db, P.ACTUAL)[0]["behaved_as_expected"], "partly")
        self.assertEqual(L.feedback(self.db, P.SIMULATED), [])
        after = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in files if f.is_file()}
        self.assertEqual(before, after)
        self.assertNotIn("config", (REPO / "engine" / "ledger.py").read_text().split("def record_feedback")[1]
                         .split("\ndef ")[0].replace("config_version", ""))

    def test_run_results_are_stored_per_ledger(self):
        ev = live_feed(T0, T0 + 5 * S) + [tick(FUT, 98990, T0 + 6 * S), depth(FUT, 98985, 98995, T0 + 6 * S)]
        t = trade(tid="s1")
        L.add_sim_trade(self.db, t, P.paper_fill("BUY", 100, LOT, quote(FUT, 100000, 100010, T0 - S), T0, CFG))
        L.store_result(self.db, run([t], ev))
        self.assertEqual(L.decisions(self.db, P.SIMULATED)[-1]["decision"], P.EXIT_REQUIRED)
        self.assertEqual(L.decisions(self.db, P.ACTUAL), [])
        self.assertTrue(L.alerts(self.db, P.SIMULATED))
        self.assertEqual(L.summary(self.db, P.SIMULATED)["closed"], 1)


class InAppSink(unittest.TestCase):
    def test_alert_sink_interface(self):
        got = []

        class Mem:
            def send(self, alert):
                got.append(alert)

        res = run([trade()], live_feed(T0, T0 + 5 * S) + [tick(FUT, 98990, T0 + 6 * S)])
        P.deliver(res.alerts, Mem())
        self.assertEqual([a.decision for a in got], [a.decision for a in res.alerts])


if __name__ == "__main__":
    unittest.main()
