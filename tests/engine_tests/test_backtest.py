"""Phase 12: event-driven backtesting, timing studies, walk-forward. Synthetic fixtures plus a small slice of the NIFTY index
lab file (golden/nifty_index_2021-01_*.csv, copied from the read-only lab dataset); no live calls."""

import ast
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from engine import backtest as B
from engine import backtest_report as BR
from engine import ledger as L
from engine import opportunity as O
from engine import paper as P
from engine import positioning as PS
from engine import risk as R
from engine.candles import IST, MIN, S, Unavailable, _ns
from engine.config import REPO, load_config
from engine.structure import Bar, Detection

from tests.engine_tests import test_contracts_risk as TC
from tests.engine_tests import test_opportunity as TO
from tests.engine_tests import test_paper as TP
from tests.engine_tests import test_positioning as TPS

CFG = load_config(REPO / "config" / "engine" / "v16.yaml")
GOLD = Path(__file__).parent / "golden"
DAY = date(2026, 11, 9)
OPEN, CLOSE = _ns(DAY, "09:15"), _ns(DAY, "15:40")


def bar(start, o, h, lo, c, res=1, ok=True):
    return Bar(start, start + res * MIN, o, h, lo, c, None, None, ok)


def path(start, closes, res=1, spread=5):
    """Contiguous bars from `start`: open = previous close, high/low = max/min(open, close) +/- spread."""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(bar(start + i * res * MIN, prev, max(prev, c) + spread, min(prev, c) - spread, c, res))
        prev = c
    return out


def setup(sid="s1", typ="SWEEP_LOW", d=1, first=None, conf=None, price=10000, stop=9900, tf=1):
    first = first or _ns(DAY, "10:00")
    conf = conf or first
    return O.Setup(sid, "SWEEP", typ, "STK", 1, tf, d, first, price, conf, price, stop, None, 0.2, None)


def lab(iv):
    data = {}
    for line in (GOLD / f"nifty_index_2021-01_{iv}.csv").read_text().splitlines()[1:]:
        ts, o, h, lo, c = line.split(",")
        t = datetime.fromisoformat(ts)
        data.setdefault(t.date(), []).append(B.index_payload(int(t.timestamp()) * S, int(iv[:-1]), float(o), float(h),
                                                             float(lo), float(c), "LAB_CSV:fixture"))
    return data


HC = BR.hist_config(CFG)
D5, D15 = lab("5m"), lab("15m")
HDAYS = sorted(D5)


def hist_day(i, as_of=None, extra5=(), cfg=HC):
    d = HDAYS[i]
    prior = [r for pd in HDAYS[max(0, i - 30):i] for r in B.history_rows(D5[pd])]
    return B.historical_day("NIFTY", d, {"5m": D5[d] + list(extra5), "15m": D15[d]}, prior, cfg, "LAB_CSV:fixture", as_of=as_of)


# ---------------------------------------------------------------- data sufficiency and protocol
class Sessions(unittest.TestCase):
    def ev(self, *rows):
        return [(t, c, k) for t, c, k in rows]

    def test_full_session_is_good(self):
        q = B.session_quality(DAY, self.ev((OPEN - 600 * S, 0, "connect"), (CLOSE + 60 * S, 0, "shutdown")), [], None, CFG)
        self.assertTrue(q.good)
        self.assertEqual(q.coverage, 1.0)

    def test_low_coverage_and_edge_gap_exclude_and_say_why(self):
        late = B.session_quality(DAY, self.ev((OPEN + 3600 * S, 0, "connect"), (CLOSE, 0, "shutdown")), [], None, CFG)
        self.assertFalse(late.good)
        self.assertTrue(any(r.startswith("COVERAGE") for r in late.reasons) and any(r.startswith("EDGE_GAP") for r in late.reasons))
        # 99 % coverage overall but a 60 s gap inside the last 30 minutes
        gap = [(CLOSE - 600 * S, CLOSE - 540 * S)]
        q = B.session_quality(DAY, self.ev((OPEN - S, 0, "connect"), (CLOSE + S, 0, "shutdown")), gap, None, CFG)
        self.assertFalse(q.good)
        self.assertEqual([r.split()[0] for r in q.reasons], ["EDGE_GAP"])
        # the same gap mid-session is fine
        mid = [(_ns(DAY, "12:00"), _ns(DAY, "12:01"))]
        self.assertTrue(B.session_quality(DAY, self.ev((OPEN - S, 0, "connect"), (CLOSE + S, 0, "shutdown")), mid, None, CFG).good)

    def test_stall_ends_a_connection_and_an_unclosed_one_ends_at_the_last_packet(self):
        st = B.session_quality(DAY, self.ev((OPEN - S, 0, "connect"), (_ns(DAY, "15:20"), 0, "stall"),
                                            (_ns(DAY, "15:25"), 1, "connect"), (CLOSE + S, 1, "shutdown")), [], None, CFG)
        self.assertFalse(st.good)                                   # 5 min dark inside the last 30 min
        crash = B.session_quality(DAY, self.ev((OPEN - S, 0, "connect")), [], _ns(DAY, "14:00"), CFG)
        self.assertLess(crash.coverage, 0.95)

    def test_real_2026_11_06_control_rows_shape_is_excluded(self):
        """The real session: connected 09:00:44, restart gap 09:03:08-11:26:38 IST (half-open socket after sleep): not GOOD."""
        ev = [(1793935844687013000, 0, "connect"), (1793945046148857000, 1, "shutdown"), (1793944600420391000, 1, "connect"),
              (1793945055033080000, 2, "connect"), (1793960100516541000, 2, "shutdown")]
        q = B.session_quality(date(2026, 11, 6), ev, [(1793935988194393000, 1793944598462304000)], None, CFG)
        self.assertFalse(q.good)
        self.assertLess(q.coverage, 0.7)


class Protocol(unittest.TestCase):
    def test_stages_from_good_session_count(self):
        self.assertEqual([B.stage(n, CFG) for n in (0, 19, 20, 59, 60, 124, 125)],
                         [B.BELOW, B.BELOW, B.SYSTEM_CHECK, B.SYSTEM_CHECK, B.TENTATIVE, B.TENTATIVE, B.FINAL])

    def test_holdout_is_the_last_30_of_the_first_125_good_sessions(self):
        days = [f"d{i:03d}" for i in range(1, 141)]
        sp = B.split(days, CFG)
        self.assertEqual((sp["holdout"][0], sp["holdout"][-1], len(sp["holdout"])), ("d096", "d125", 30))
        self.assertEqual(sp["development"][-1], "d095")
        self.assertEqual(len(sp["post_window"]), 15)
        self.assertEqual(B.split(days[:70], CFG)["holdout"], [])

    def test_holdout_read_only_at_final_once_and_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = BR.overlay(CFG, {"storage.root": tmp}, "test")
            for st in (B.SYSTEM_CHECK, B.TENTATIVE):
                self.assertFalse(BR.read_holdout(cfg, st, ["x"], "t")[0])
            self.assertFalse(BR.holdout_log(cfg).exists())
            self.assertTrue(BR.read_holdout(cfg, B.FINAL, ["x"], "t1")[0])
            ok, why = BR.read_holdout(cfg, B.FINAL, ["x"], "t2")
            self.assertFalse(ok)
            self.assertIn("HOLDOUT_ALREADY_READ", why)
            self.assertEqual(len(BR.holdout_log(cfg).read_text().splitlines()), 1)

    def test_holdout_rule_is_in_versioned_config(self):
        self.assertEqual(CFG.get("backtest.holdout"), {"window_good_sessions": 125, "last_n": 30})
        self.assertEqual(CFG.version, "v16")


# ---------------------------------------------------------------- price path, fills, stop gaps
class PricePath(unittest.TestCase):
    T = _ns(DAY, "10:00")

    def test_gap_through_stop_exits_at_the_first_price_beyond_not_at_the_stop(self):
        bars = path(self.T, [10010, 10020]) + [bar(self.T + 2 * MIN, 9850, 9860, 9800, 9820)]
        r, ts, px = B.walk(1, self.T, 9900, 10300, bars, CLOSE)
        self.assertEqual((r, px), (B.STOP, 9850))
        self.assertLess(B.r_multiple(1, 10000, 9900, px), -1)
        short = B.walk(-1, self.T, 10100, 9700, [bar(self.T, 10180, 10200, 10150, 10160)], CLOSE)
        self.assertEqual(short[2], 10180)

    def test_touching_stop_and_target_in_one_bar_counts_as_the_stop(self):
        r = B.walk(1, self.T, 9900, 10100, [bar(self.T, 10000, 10150, 9850, 10000)], CLOSE)
        self.assertEqual(r[:1] + r[2:], (B.STOP, 9900))

    def test_target_end_and_data_interruption(self):
        self.assertEqual(B.walk(1, self.T, 9900, 10030, path(self.T, [10010, 10040]), CLOSE)[0], B.TARGET)
        self.assertEqual(B.walk(1, self.T, 9900, 99999, path(self.T, [10010, 10020]), CLOSE)[0], B.END)
        holed = path(self.T, [10010, 10020, 10030])
        self.assertEqual(B.walk(1, self.T, 9900, 99999, holed[:1] + holed[2:], CLOSE)[0], B.GAP)
        bad = [replace(holed[0], ok=False)]
        self.assertEqual(B.walk(1, self.T, 9900, 99999, bad, CLOSE)[0], B.GAP)

    def test_excursions_below_resolution_are_unavailable(self):
        ex = B.excursions(1, self.T, 10000, {b.start: b for b in path(self.T, [10010, 10050, 9990], res=5)}, 5, CLOSE, 100,
                          50.0, [1, 3, 5, 10, 15])
        self.assertIsInstance(ex[1], Unavailable)
        self.assertIn("BELOW_DATA_RESOLUTION", ex[3].reason)
        self.assertEqual(ex[5]["mfe_paise"], 15)
        self.assertEqual(ex[15]["mae_paise"], 10000 - (9990 - 5))
        self.assertEqual(ex[10]["mfe_r"], (10050 + 5 - 10000) / 100)

    def test_segments_come_from_each_events_measured_exit(self):
        t = self.T
        seg = lambda same, later=(None, None, None): B.segment(same, later, t, CFG)  # noqa: E731
        self.assertEqual(seg((B.TARGET, t + 4 * MIN, 1)), "IMMEDIATE_1_5")
        self.assertEqual(seg((B.TARGET, t + 20 * MIN, 1)), "CONTINUATION_5_30")
        self.assertEqual(seg((B.TARGET, t + 60 * MIN, 1)), "MID_30_90")
        self.assertEqual(seg((B.TARGET, t + 200 * MIN, 1)), "INCONCLUSIVE")
        self.assertEqual(seg((B.STOP, t + MIN, 1)), "FAILED")
        self.assertEqual(seg((B.END, t, 1), (B.TARGET, t + 1440 * MIN, 1)), "MULTI_SESSION")
        self.assertEqual(seg((B.END, t, 1), (B.TARGET, t + 330 * MIN, 1)), "INCONCLUSIVE", "after the cutoff, same session")
        self.assertEqual(seg((B.END, t, 1), (B.END, t, 1)), "INCONCLUSIVE")
        self.assertEqual(seg((B.GAP, t, None)), "INCONCLUSIVE")


# ---------------------------------------------------------------- metrics, verdicts, half-life, walk-forward
def rows(vals, days=None):
    return [{"r": v, "day": f"2026-11-{(days or (lambda i: i % 10 + 1))(i):02d}", "exit_reason": B.TARGET if v > 0 else B.STOP}
            for i, v in enumerate(vals)]


class Metrics(unittest.TestCase):
    def test_figures_and_day_clustered_bootstrap_are_deterministic(self):
        rs = rows([2, -1, -1, 3, -1] * 30)
        m = B.metrics(rs, CFG)
        self.assertEqual((m["n"], m["win_rate"], m["expectancy"], m["profit_factor"]), (150, 0.4, 0.4, round(5 / 3, 6)))
        self.assertEqual(m["avg_win"], 2.5)
        self.assertEqual(m["precision"], 0.4)
        lo, hi = m["ci"]["expectancy"]
        self.assertLessEqual(lo, 0.4)
        self.assertGreaterEqual(hi, 0.4)
        self.assertEqual(m["ci"], B.metrics(rs, CFG)["ci"], "seeded")
        self.assertEqual(B.max_drawdown([1, -2, -1, 3, -5]), 5)

    def test_verdicts_conservative_by_stage_and_sample(self):
        small = B.metrics(rows([1] * 99), CFG)
        self.assertEqual(B.verdict(small, B.FINAL, CFG)[0], B.INSUFFICIENT)
        big = B.metrics(rows([2, -1] * 100), CFG)
        for st in (B.BELOW, B.SYSTEM_CHECK, B.TENTATIVE):
            self.assertEqual(B.verdict(big, st, CFG)[0], B.INSUFFICIENT)
        self.assertEqual(B.verdict(big, B.FINAL, CFG)[0], B.REVISE, "no go-live criteria => never KEEP")
        losing = B.metrics(rows([-1, -1, 0.5] * 100), CFG)
        self.assertEqual(B.verdict(losing, B.FINAL, CFG)[0], B.DROP)

    def test_half_life_measured_and_conservative_statuses(self):
        e = lambda age, vals: [{"age_min": age, "r": v, "day": "d"} for v in vals]  # noqa: E731
        ent = e(0, [1.0] * 100) + e(5, [0.8] * 100) + e(15, [0.4] * 100) + e(30, [0.1] * 100)
        h = B.half_life(ent, CFG)
        self.assertEqual((h["status"], h["half_life_s"]), ("MEASURED", 900))
        self.assertEqual(B.half_life(e(0, [1.0] * 99), CFG)["status"], B.INSUFFICIENT)
        self.assertEqual(B.half_life(e(0, [-0.1] * 100), CFG)["status"], "NO_POSITIVE_EDGE")
        self.assertEqual(B.half_life(e(0, [1.0] * 100) + e(5, [0.9] * 50), CFG)["status"], "NOT_REACHED_WITHIN_SAMPLE")

    def test_walk_forward_chooses_on_train_and_scores_on_test_only(self):
        self.assertEqual(B.windows(100, 40, 10, 10)[0], (range(0, 40), range(40, 50)))
        self.assertEqual(len(B.windows(100, 40, 10, 10)), 6)
        days = [f"2024-{m:02d}-01" for m in range(1, 13)]
        self.assertEqual(B.month_windows(days, 6, 3, 3)[0], (days[:6], days[6:9]))
        data = {"a": {d: (1.0 if d < "2024-07" else -1.0) for d in days}, "b": {d: 0.5 for d in days}}
        rf = lambda p, ds: [{"r": data[p][d], "day": d} for d in ds for _ in range(60)]  # noqa: E731
        w = B.walk_forward(B.month_windows(days, 6, 3, 3), ["a", "b"], rf, CFG)
        self.assertEqual(w["windows"][0]["chosen"], "a")             # best in train, worst in test
        self.assertEqual(w["windows"][0]["test"]["expectancy"], -1.0)
        self.assertTrue(all(r["day"] >= "2024-07" for r in w["oos_rows"]))


# ---------------------------------------------------------------- Phase 6 half-life wiring (D-56)
class HalfLifeRule(unittest.TestCase):
    def test_rule_disabled_without_value_and_fails_timely_when_older_than_half_life(self):
        s, sn = TO.BREAKOUT, TO.snap(TO.T1, 10200, above=10600)
        base = O.opportunity_age(s, sn, TO.CFG)
        self.assertIsInstance(base.age_vs_half_life, Unavailable)
        cfg = BR.overlay(CFG, {}, "t")
        on = O.opportunity_age(s, replace(sn, as_of=TO.T1 + 10 * MIN), cfg, half_life=300.0)
        self.assertEqual(on.age_vs_half_life, 2.0)
        self.assertIn("AGE_VS_HALF_LIFE", on.failed_rules)
        self.assertEqual(on.classification, O.LATE)
        young = O.opportunity_age(s, sn, cfg, half_life=3600.0)
        self.assertNotIn("AGE_VS_HALF_LIFE", young.failed_rules)

    def test_half_life_file_is_versioned_and_partial_runs_carry_other_datasets(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = BR.overlay(CFG, {"opportunity.half_life_file": str(Path(tmp) / "hl" / "v1.json")}, "t")
            e1 = {"RECORDED": {}, BR.HIST: {"SWEEP_LOW": {"status": "NO_POSITIVE_EDGE"}}}
            self.assertEqual(BR.write_half_life(cfg, {"entries": e1}).name, "v1.json")
            self.assertEqual(BR.write_half_life(cfg, {"entries": e1}).name, "v1.json", "unchanged entries: no new version")
            carried = BR.latest_half_life(cfg)
            self.assertEqual(carried[BR.HIST], e1[BR.HIST])
            carried["RECORDED"] = {"SWEEP_LOW": {"status": "INSUFFICIENT_SAMPLE"}}
            p2 = BR.write_half_life(cfg, {"entries": carried})
            self.assertEqual(p2.name, "v2.json")
            self.assertEqual(json.loads(p2.read_text())["entries"][BR.HIST], e1[BR.HIST])

    def test_phase6_reads_only_recorded_measured_tentative_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "hl.json"
            f.write_text(json.dumps({"entries": {
                "RECORDED": {"SWEEP_LOW": {"status": "MEASURED", "stage": "TENTATIVE", "half_life_s": 900},
                             "SWEEP_HIGH": {"status": "MEASURED", "stage": "SYSTEM_CHECK", "half_life_s": 600},
                             "ZONE_DEFENDED": {"status": "INSUFFICIENT_SAMPLE", "stage": "FINAL", "half_life_s": None}},
                "HISTORICAL_CANDLES": {"BREAKOUT_ACCEPTED": {"status": "MEASURED", "stage": "HISTORICAL_CANDLES",
                                                             "half_life_s": 300}}}}))
            cfg = BR.overlay(CFG, {"opportunity.half_life_file": str(f)}, "t")
            self.assertEqual(O.half_lives(cfg), {"SWEEP_LOW": 900})
        self.assertEqual(O.half_lives(TO.CFG), {}, "configs before v16 have no half-life file")
        self.assertEqual(O.half_lives(CFG), {}, "the repo file holds no measured RECORDED value")


# ---------------------------------------------------------------- HISTORICAL_CANDLES and the look-ahead guard
class Historical(unittest.TestCase):
    def test_lab_days_reuse_phase5_and_phase6_and_label_the_source(self):
        hd = hist_day(5)
        self.assertTrue(hd.setups, "the fixture week has sweep / zone setups")
        self.assertTrue(all(x.config_version.startswith("v16:HIST") for x in hd.dets))
        lv = [x for x in hd.dets if x.type in ("PDH", "PDL", "PDC")]
        self.assertTrue(lv and all(s.startswith("LAB_CSV:") for x in lv for s in x.source), "never labelled HISTORICAL_API")
        self.assertFalse([x for x in hd.dets if x.type == "VWAP"], "no volume => no VWAP")
        ev = next(iter(hd.evals.values()))
        self.assertTrue(all("VWAP_EXTENSION not checked" in " ".join(e.exhaustion_notes) for e in ev if e.state == "ACTIVE"))

    def test_look_ahead_guard_sentinel_future_bar_changes_nothing_known_before_it(self):
        i = 5
        t = _ns(HDAYS[i], "12:00")
        prefix = hist_day(i, as_of=t)
        d5 = [p for p in D5[HDAYS[i]] if p["end_ns"] <= t]
        sentinel = [{**p, "high": 10 ** 9, "close": 10 ** 9 - 1, "open": 10 ** 9 - 2} for p in D5[HDAYS[i]] if p["end_ns"] > t][:1]
        rest = [p for p in D5[HDAYS[i]] if p["end_ns"] > t][1:]
        poisoned = B.historical_day("NIFTY", HDAYS[i], {"5m": d5 + sentinel + rest, "15m": D15[HDAYS[i]]},
                                    [r for pd in HDAYS[:i] for r in B.history_rows(D5[pd])], HC, "LAB_CSV:fixture")
        known = lambda hd: (  # noqa: E731
            [x for x in hd.dets if x.confirmed_ts <= t],
            [s for s in hd.setups if s.confirmed_ts <= t],
            {s.id: [e for e in hd.evals[s.id] if e.as_of <= t] for s in hd.setups if s.confirmed_ts <= t},
            {s.id: hd.targets[s.id] for s in hd.setups if s.confirmed_ts <= t})
        self.assertEqual(known(prefix), known(poisoned), "a future observation changed a past decision: LEAKAGE")
        self.assertTrue(known(prefix)[0])
        # the guard is sensitive: the same sentinel placed BEFORE t does change what is known at t
        past = [p if p["end_ns"] != d5[-3]["end_ns"] else {**p, "high": 10 ** 9} for p in d5]
        moved = B.historical_day("NIFTY", HDAYS[i], {"5m": past, "15m": D15[HDAYS[i]]},
                                 [r for pd in HDAYS[:i] for r in B.history_rows(D5[pd])], HC, "LAB_CSV:fixture", as_of=t)
        self.assertNotEqual(known(prefix), known(moved))

    def test_event_rows_three_anchors_and_not_representable_families(self):
        with tempfile.TemporaryDirectory():
            data = {"5m": D5, "15m": D15}
            out = BR.run_historical(HC, data, HDAYS)
        anchors = {r["anchor"] for r in out["events"]}
        self.assertEqual(anchors, set(BR.ANCHORS))
        fx = [r for r in out["events"] if r["anchor"] == "FIRST_EXECUTABLE" and "unavailable" not in r]
        self.assertTrue(fx)
        self.assertTrue(all(r["score_band"] == B.NOT_REPRESENTABLE and r["excursions"][1].reason.startswith("BELOW")
                            for r in fx))
        self.assertTrue(all(r["dataset"] == BR.HIST for r in out["events"]))


# ---------------------------------------------------------------- required scenarios
class Scenarios(unittest.TestCase):
    def positioning_setups(self, price, oi):
        n = TPS.N
        d = TPS.session(n, extra=TPS.steps(n, 20, price), near_oi=TPS.steps(n, 20, oi), next_oi=TPS.steps(n, 20, oi))
        ev = PS.track_events(TPS.run(d), TPS.CFG)
        c1 = {"STK": [{**c, "start_ns": c["end_ns"] - MIN} for c in d.c1[TPS.SF].values()]}
        return O.setups_from_positioning([e for e in ev if e["underlying"] == "STK"], c1, lambda u, m, t: 100.0, O.load()), d

    def test_long_short_buildup_covering_unwinding_become_backtest_events(self):
        for price, oi, hyp, direction in ((0.0006, 0.002, PS.LONG_BUILDUP, 1), (-0.0006, 0.002, PS.SHORT_BUILDUP, -1),
                                          (0.0006, -0.002, PS.SHORT_COVERING, 1), (-0.0006, -0.002, PS.LONG_UNWINDING, -1)):
            with self.subTest(hyp=hyp):
                setups, d = self.positioning_setups(price, oi)
                self.assertTrue(setups)
                s = setups[0]
                self.assertEqual((s.source_type, s.direction), (hyp, direction))
                bars = [Bar(c["end_ns"] - MIN, c["end_ns"], c["open"], c["high"], c["low"], c["close"], None, None, True)
                        for c in sorted(d.c1[TPS.SF].values(), key=lambda c: c["end_ns"])]
                row = B.outcome(s, "CONFIRMATION", (s.confirmed_ts, s.confirmed_price), Unavailable("no target"), bars, 1,
                                lambda tf, t: 100.0, CLOSE, CLOSE, CLOSE, CFG, family=s.source_type)
                self.assertEqual(row["family"], hyp)
                self.assertIn(row["exit_reason"], (B.STOP, B.END))

    def test_oi_price_contradiction_produces_no_event(self):
        setups, _ = self.positioning_setups(0.0, 0.002)               # OI up, price flat: not a buildup
        self.assertEqual(setups, [])

    def test_oi_publication_delay_decision_uses_only_received_oi(self):
        t = _ns(DAY, "11:00")
        rows_ = [(t - 120 * S, t - 110 * S, 1000), (t - 30 * S, t + 40 * S, 1200)]   # stamped 10:59:30, received 11:00:40
        now, later = B.oi_views(rows_, t)
        self.assertEqual((now, later), (1000, 1200))
        self.assertIsInstance(B.oi_views(rows_[1:], t)[0], Unavailable)

    def test_sweeps_and_false_breakouts(self):
        hd = hist_day(5)
        sw = [s for s in hd.setups if s.family == "SWEEP"]
        self.assertTrue(sw and all(s.structural_stop == next(x for x in hd.dets if x.id == s.id).attrs["extreme"] for s in sw))
        mk = lambda typ, i, **a: Detection(i, typ, "STK", 1, "5m", 10000, _ns(DAY, "10:00"), _ns(DAY, "10:05"), (), a, "", "v")  # noqa
        box = mk("CONSOLIDATION", "box", high=10000, low=9900)
        dets = [box, mk("BREAKOUT_FAILED", "f1", box="box"), mk("BREAKOUT_ACCEPTED", "a1", box="box")]
        made = O.setups_from_structure(dets, {}, lambda tf, t: 100.0, O.load())
        self.assertEqual([s.id for s in made], ["a1"], "a failed breakout is never a setup")
        fake = setup(typ="BREAKOUT_ACCEPTED", stop=9900)
        r = B.outcome(fake, "CONFIRMATION", (fake.confirmed_ts, 10000), 10300, path(fake.confirmed_ts, [10020, 9950, 9880]),
                      1, lambda tf, t: 50.0, CLOSE, CLOSE, CLOSE, CFG)
        self.assertEqual(r["segment"], "FAILED")

    def test_expiry_and_rollover_labels_and_expiry_day_block(self):
        self.assertEqual([B.expiry_label(DAY, date(2026, 11, d), CFG) for d in (9, 11, 20)],
                         ["EXPIRY_DAY", "ROLLOVER_WINDOW", "NORMAL"])
        c = TC.Risk.eligible(None)
        d = R.risk_check(replace(c, expiry=TC.DAY), TC.FLAT, TC.CFG)
        self.assertTrue(any(r.startswith("EXPIRY_DAY") for r in d.reasons))

    def test_illiquid_option_is_never_traded(self):
        atm = TC.tok("CE", TC.E2, 1000)
        sel = TC.select(quotes={atm: TC.quote(atm, 1990, 2010, volume=1000, oi=None)})
        c = next(x for x in sel.candidates if x.token == atm)
        self.assertTrue(any(r.startswith("ILLIQUID") for r in c.reasons))
        self.assertEqual(R.risk_check(c, TC.FLAT, TC.CFG).status, R.REJECTED)

    def test_data_interruption_excludes_the_session_and_breaks_the_path(self):
        q = B.session_quality(DAY, [(OPEN - S, 0, "connect"), (CLOSE + S, 0, "shutdown")],
                              [(_ns(DAY, "09:20"), _ns(DAY, "09:22"))], None, CFG)
        self.assertFalse(q.good)
        bars = path(_ns(DAY, "10:00"), [10010, 10020, 10030])
        self.assertEqual(B.walk(1, _ns(DAY, "10:00"), 9900, None, [bars[0], bars[2]], CLOSE)[0], B.GAP)

    def paper_trade(self, db, qty=100, gap_to=98500, tid="t1", day=None):
        t = TP.trade(qty=qty, tid=tid)
        t = replace(t, day=day) if day else t
        entry = P.paper_fill("BUY", qty, TP.LOT, TP.quote(TP.FUT, 100000, 100010, TP.T0), TP.T0, TP.CFG)
        t = replace(t, entry_price=entry.avg_price)
        L.add_sim_trade(db, t, entry)
        ev = TP.live_feed(TP.T0, TP.T0 + 5 * S) + [TP.tick(TP.FUT, gap_to, TP.T0 + 6 * S),
                                                    TP.depth(TP.FUT, gap_to - 5, gap_to + 5, TP.T0 + 6 * S)]
        L.store_result(db, TP.run([t], ev))
        return t

    def test_stop_gap_paper_exit_fills_beyond_the_stop_and_costs_are_date_effective(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = L.open_ledger(Path(tmp) / "bt.sqlite")
            self.paper_trade(db)
            self.paper_trade(db, tid="old", day=date(2026, 11, 5))
            rs = {r["trade_id"]: r for r in BR.trade_rows(db, CFG, {})}
        r = rs["t1"]
        self.assertEqual(r["exit_rule"], "HARD_STOP_UNDERLYING")
        self.assertLess(r["r"], -1, "the gap exit at the bid (98495) is worse than the 99000 stop")
        self.assertAlmostEqual(r["gross_inr"], (98495 - 100010) * 100 / 100, places=2)
        self.assertGreater(r["cost_inr"], 0)
        self.assertFalse(r["cost_unverified"])
        self.assertTrue(rs["old"]["cost_unverified"], "no verified rate in force on 2026-11-05")
        self.assertGreater(r["slippage_inr"], 0)

    def test_simultaneous_signals_resolved_by_the_live_risk_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = L.open_ledger(Path(tmp) / "bt.sqlite")
            t = TP.trade(tid="open1")
            entry = P.paper_fill("BUY", 100, TP.LOT, TP.quote(TP.FUT, 100000, 100010, TP.T0), TP.T0, TP.CFG)
            L.add_sim_trade(db, t, entry)
            L.store_result(db, TP.run([t], TP.live_feed(TP.T0, TP.T0 + 310 * S)))   # one 300 s review => a net P&L
            st = L.portfolio_state(db, P.SIMULATED, TP.DAY, TP.T0 + 310 * S, CFG)
        self.assertEqual(st.open_underlyings, ("STK",))
        c = replace(TC.Risk.eligible(None), as_of=TP.T0 + 310 * S)
        pair = P.risk_both(c, st, TC.FLAT, TC.CFG)
        self.assertFalse(pair.approved)
        self.assertTrue(any(r.startswith("SINGLE_POSITION_PER_UNDERLYING") for r in pair.simulated.reasons))

    def test_position_sizing_whole_lots_within_the_risk_budget(self):
        c = TC.Risk.eligible(None)
        self.assertEqual(c.quantity, c.lots * c.lot_size)
        self.assertLessEqual(c.planned_risk_inr, TC.CFG.get("risk.max_risk_per_trade_inr"))

    def test_daily_loss_limit_blocks_the_next_signal_in_the_backtest_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = L.open_ledger(Path(tmp) / "bt.sqlite")
            self.paper_trade(db, qty=500)
            st = L.portfolio_state(db, P.SIMULATED, TP.DAY, TP.T0 + 60 * S, CFG)
        self.assertLessEqual(st.realized_pnl_inr, -CFG.get("risk.max_daily_loss_inr"))
        d = R.risk_check(replace(TC.Risk.eligible(None), as_of=TP.T0 + 60 * S), st, TC.CFG)
        self.assertTrue(any(r.startswith("DAILY_LOSS_LIMIT") for r in d.reasons))

    def test_costs_and_slippage_share(self):
        share = BR._slip_share([{"net_inr": 1, "gross_inr": 1000.0, "slippage_inr": 100.0}])
        self.assertEqual(share["share_of_gross"], 0.1)
        self.assertIsNone(BR._slip_share([{"net_inr": 1, "gross_inr": -5.0, "slippage_inr": 1.0}])["share_of_gross"])


# ---------------------------------------------------------------- recorded sessions: Parquet rebuild
class Rehydrate(unittest.TestCase):
    def test_buffer_rebuilt_from_parquet_equals_the_original(self):
        from engine.compact import compact
        from tests.engine_tests.test_storage import record_day
        with tempfile.TemporaryDirectory() as tmp:
            d = record_day(Path(tmp), "2026-11-02", n=30, gap_after=10)
            q = lambda p, t: sorted(sqlite3.connect(p).execute(f"SELECT * FROM {t}").fetchall(), key=repr)  # noqa: E731
            before = {t: q(d / "buffer.sqlite", t) for t in ("ticks", "depth", "events", "gaps")}
            ev0 = BR.control_rows(d)
            compact(d)
            self.assertFalse((d / "buffer.sqlite").exists())
            self.assertEqual(sorted(BR.control_rows(d)[0]), sorted(ev0[0]), "control rows from the derived Parquet")
            cfg = BR.overlay(CFG, {"storage.root": tmp, "retention.archive_target": str(Path(tmp) / "archive")}, "t")
            out = BR.rehydrate(d, cfg, Path(tmp) / "re" / d.name)
            for t, rows_ in before.items():
                self.assertEqual(q(out / "buffer.sqlite", t), rows_, t)
            self.assertIsNotNone(BR.last_packet_ns(d, cfg))


# ---------------------------------------------------------------- hygiene
class Hygiene(unittest.TestCase):
    def test_pure_module_does_no_io_and_reads_no_clock(self):
        tree = ast.parse((REPO / "engine" / "backtest.py").read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        mods = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names} | \
               {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertFalse({"open", "now", "time", "today", "sqlite3", "requests", "urlopen"} & names)
        self.assertFalse({"sqlite3", "time", "requests", "os", "socket"} & mods)

    def test_every_table_is_titled_with_its_dataset_stage_and_good_sessions(self):
        m = B.metrics(rows([1, -1] * 3), CFG)
        res = {"run_at": "t", "config_version": "v16", "recorded": {
            "stage": B.BELOW, "good_sessions": 0, "split": {}, "holdout": "x", "quality": [], "families_trades_inr": {"E": m},
            "families_trades_r": {"E": m}, "slippage_share": {}, "oi_delay_diagnostic": {}, "event_study": {}, "half_life": {}},
            "verdicts": {"E": (B.INSUFFICIENT, "n")}}
        md = BR.render(res, CFG)
        for sec in md.split("\n### ")[1:] + md.split("\n## Verdicts")[1:]:
            self.assertIn("SIMULATED / HYPOTHETICAL", sec)
            self.assertRegex(sec, r"stage BELOW_SYSTEM_CHECK · 0 good sessions")
        self.assertIn("RECORDED sessions", md)
        self.assertIsNone(B.metrics([{"r": 1.0, "day": "d"}], CFG)["precision"], "no target concept => no precision")


if __name__ == "__main__":
    unittest.main()
