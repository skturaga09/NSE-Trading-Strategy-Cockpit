"""Phase 6: opportunity age, timeliness, retest, exhaustion, timing recorder. Synthetic fixtures only."""

import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import yaml

from engine import opportunity as O
from engine import structure as T
from engine.candles import MIN, S, Unavailable, _ns
from engine.config import ConfigError
from tests.engine_tests.test_structure import DAY, TOK, candle, history, random_day

CFG = O.load()
T0 = _ns(DAY, "10:00")
T1 = T0 + 6 * MIN
CLOSE = _ns(DAY, "15:40")
ATR = 100.0
# A breakout first seen at 100.00, confirmed after a 2 ATR run; box 99.00-99.90, so the stop is the box low.
BREAKOUT = O.Setup("b1", "BREAKOUT", "BREAKOUT_ACCEPTED", "STK", TOK, 3, 1, T0, 10000, T1, 10200, 9900, 9990, 0.3, None)


def lmap(t, price, above=10250, below=None):
    ob = lambda lv: None if lv is None else T.Obstacle("SWING_HIGH" if lv > price else "SWING_LOW", "3m", lv, lv - price,  # noqa: E731
                                                      {"3m": (lv - price) / ATR}, f"o{lv}")
    return T.LevelMap("STK", TOK, t, price, {"3m": ATR}, ob(above), ob(below), 2)


def snap(t, price, above=10250, vwap=10230, lm=True, structure=(), positioning=None, vwap_atr=ATR):
    return O.Snapshot(t, price, t, t + S, ATR, vwap, lmap(t, price, above) if lm else None, structure, positioning, vwap_atr)


class Timeliness(unittest.TestCase):
    def test_late_breakout_rr_below_min_creates_retest_plan(self):
        ev = O.track(BREAKOUT, [snap(T1, 10200)], CFG)[0]
        self.assertEqual(ev.classification, O.LATE)
        self.assertIn("RR_BELOW_MIN", ev.failed_rules)
        self.assertEqual(ev.failed_rules, ("RR_BELOW_MIN", "EXTENDED", "STOP_TOO_WIDE"))
        self.assertEqual((ev.extension_atr, ev.obstacle_distance_atr, ev.stop_distance_atr), (2.0, 0.5, 3.0))
        p = ev.retest_plan          # VWAP 102.30 is above price (not a valid long re-entry), so the broken level wins
        self.assertEqual((p.level_type, p.zone_low, p.zone_high, p.invalidation, p.expires_ts),
                         ("BROKEN_LEVEL", 9990, 10015, 9900, T1 + 30 * MIN))
        self.assertAlmostEqual(p.rr_if_filled, (10250 - 10015) / (10015 - 9900))

    def test_return_to_zone_is_timely_with_reason_retest(self):
        evs = O.track(BREAKOUT, [snap(T1, 10200), snap(T1 + MIN, 10120), snap(T1 + 2 * MIN, 10005),
                                 snap(T1 + 3 * MIN, 10010)], CFG)
        self.assertEqual([e.classification for e in evs], [O.LATE, O.LATE, O.TIMELY, O.TIMELY])
        self.assertEqual(evs[2].reason, "RETEST")
        self.assertEqual(evs[1].retest_plan, evs[0].retest_plan, "one plan, not re-created")
        self.assertIsNone(evs[3].retest_plan)

    def test_missing_level_map_is_unknown_never_timely(self):
        evs = O.track(BREAKOUT, [snap(T1 + k * MIN, px, lm=False) for k, px in enumerate((10200, 10005, 10010, 10003))], CFG)
        self.assertEqual({e.classification for e in evs}, {O.UNKNOWN})
        self.assertTrue(all("NO_LEVEL_MAP" in " ".join(e.missing) for e in evs))
        no_obstacle = O.opportunity_age(BREAKOUT, snap(T1, 10005, above=None), CFG)
        self.assertEqual((no_obstacle.classification, no_obstacle.obstacle_distance_atr.reason),
                         (O.UNKNOWN, "NO_OBSTACLE_IN_TRADE_DIRECTION"))

    def test_unavailable_fields_are_explicit(self):
        ev = O.opportunity_age(BREAKOUT, snap(T1, 10005), CFG)
        for v in (ev.current_rr_net, ev.option_premium_change, ev.option_iv_change, ev.age_vs_half_life):
            self.assertIsInstance(v, Unavailable)
        self.assertTrue(ev.current_rr_net.reason.startswith("NET_UNAVAILABLE"))
        self.assertEqual((ev.age_first_s, ev.age_confirmed_s, ev.price_age_s), (360.0, 0.0, 0.0))

    def test_invalidation_and_retest_expiry_end_the_setup(self):
        evs = O.track(BREAKOUT, [snap(T1, 10200), snap(T1 + MIN, 9890), snap(T1 + 2 * MIN, 10005)], CFG)
        self.assertEqual([e.state for e in evs], ["ACTIVE", "INVALIDATED"])
        evs = O.track(BREAKOUT, [snap(T1, 10200), snap(T1 + MIN, 9900)], CFG)     # Q-OPP-2 (owner): equal = invalidated
        self.assertEqual((evs[-1].state, evs[-1].reason), ("INVALIDATED", "CLOSE_THROUGH_STOP: 9900 vs 9900"))
        short = replace(BREAKOUT, direction=-1, first_price=10000, confirmed_price=9800, structural_stop=10100)
        self.assertEqual(O.track(short, [snap(T1, 10100, above=None)], CFG)[0].state, "INVALIDATED")
        evs = O.track(BREAKOUT, [snap(T1 + k * MIN, 10200) for k in range(40)], CFG)
        self.assertEqual((evs[-1].state, evs[-1].as_of, len(evs)), ("RETEST_EXPIRED", T1 + 30 * MIN, 31))

    def test_structural_stop_identical_across_reevaluations(self):
        rnd = random.Random(5)
        snaps = [snap(T1 + k * MIN, rnd.randint(9950, 10400), above=rnd.choice((10300, 10500, None)),
                      lm=rnd.random() > 0.1) for k in range(60)]
        evs = O.track(BREAKOUT, snaps, CFG)
        self.assertEqual({e.structural_stop for e in evs}, {9900})
        # setups rebuilt from Phase 5 at every 3m prefix of a random day are the same objects (stop never recomputed)
        day, rows = random_day(11), history()
        full_d = T.detect("STK", TOK, day, rows, CFG, DAY)
        full = {s.id: s for s in O.setups_from_structure(full_d, day, O.Context("STK", TOK, full_d, day["1m"], None).atr_at, CFG)}
        self.assertGreater(len(full), 5)
        for k in range(3, 376, 3):
            t = _ns(DAY, "09:15") + k * MIN
            pre = {iv: [c for c in cs if c["end_ns"] <= t] for iv, cs in day.items()}
            d = T.detect("STK", TOK, pre, rows, CFG, DAY)
            for s in O.setups_from_structure(d, pre, O.Context("STK", TOK, d, pre["1m"], None).atr_at, CFG):
                self.assertEqual(s, full[s.id])


def state(close, price_chg, oi_chg, rvol, hyp="NEUTRAL_OR_MIXED"):
    f = {"fut_close": close, "fut_price_chg_15m_pct": price_chg, "combined_oi_chg_15m_pct": oi_chg, "rvol_15m": rvol}
    return SimpleNamespace(feature=f.get, primary=SimpleNamespace(positioning_hypothesis=hyp))


class Exhaustion(unittest.TestCase):
    def flags(self, **kw):
        ev = O.opportunity_age(BREAKOUT, snap(T1, 10005, **kw), CFG)
        return ev, [f.split(":")[0] for f in ev.exhaustion_flags]

    def test_no_flags_without_evidence_and_skipped_checks_are_noted(self):
        ev, fl = self.flags()
        self.assertEqual((fl, ev.classification), ([], O.TIMELY))
        self.assertTrue(any(n.startswith("HIGH_VOLUME_ZONE_REJECTION skipped") for n in ev.exhaustion_notes))
        self.assertTrue(any(n.startswith("OPPOSING_POSITIONING not checked") for n in ev.exhaustion_notes))

    def test_each_flag_individually(self):
        ev, fl = self.flags(vwap=9790)
        self.assertEqual((fl, ev.classification, ev.exhaustion), (["VWAP_EXTENSION"], O.EXHAUSTED, "POSSIBLE_EXHAUSTION"))
        # Q-OPP-1: measured in the 15m ATR, not the setup's: 2.15 x 100 = 1.07 x a 200-paise 15m ATR => no flag
        self.assertEqual(self.flags(vwap=9790, vwap_atr=200.0)[1], [])
        ev, fl = self.flags(vwap=9790, vwap_atr=None)
        self.assertEqual(fl, [])
        self.assertTrue(any(n.startswith("VWAP_EXTENSION not checked: INSUFFICIENT_DATA: no 15m ATR") for n in ev.exhaustion_notes))
        fails = tuple(T._det("SWEEP_HIGH", "STK", TOK, "3m", 10250 + k, T0 + k * MIN, T0 + k * MIN, (), {}, "v7")
                      for k in range(3))
        self.assertEqual(self.flags(structure=fails)[1], ["REPEATED_FAILURE"])
        self.assertEqual(self.flags(structure=fails[:2])[1], [])
        ts = [T1 - 30 * MIN, T1 - 15 * MIN, T1]
        oi = {t: state(10000 + 100 * i, p, 1.0, 1.0) for i, (t, p) in enumerate(zip(ts, (0.6, 0.4, 0.2)))}
        self.assertEqual(self.flags(positioning=oi)[1], ["OI_PROGRESS_DECLINING"])
        rv = {t: state(10000 + 100 * i, 0.1, -1.0, r) for i, (t, r) in enumerate(zip(ts, (2.0, 1.5, 1.1)))}
        self.assertEqual(self.flags(positioning=rv)[1], ["RVOL_DECLINING_WHILE_EXTENDING"])
        opp = {t: state(10000, 0.1, -1.0, 1.0, "SHORT_BUILDUP" if t == T1 else "NEUTRAL_OR_MIXED") for t in ts}
        self.assertEqual(self.flags(positioning=opp)[1], ["OPPOSING_POSITIONING"])


class PositioningSetup(unittest.TestCase):
    def test_phase4_event_becomes_a_setup_and_its_invalidation_ends_it(self):
        ev = {"event_id": "p1", "state": "CONFIRMED", "ts_ns": T1, "underlying": "STK", "direction": "PRICE_DOWN",
              "positioning_hypothesis": "SHORT_BUILDUP", "contracts": {"price": [TOK, "STKNOV", "2026-11-23"]},
              "first_observed_ts": "2026-11-06T10:00:00+05:30", "price_first_observed_paise": 10000.0,
              "price_confirmed_paise": 9950.0, "invalidation": [{}, {"level_paise": 10050.0}]}
        inv = {"event_id": "p1", "state": "INVALIDATED", "ts_ns": T1 + 2 * MIN}
        s = O.setups_from_positioning([ev, inv], {}, lambda u, m, t: ATR, CFG)[0]
        self.assertEqual((s.direction, s.structural_stop, s.first_ts, s.timeframe, s.invalidated_ts),
                         (-1, 10050, T0, 5, T1 + 2 * MIN))
        self.assertTrue(s.pre_signal_move_atr.reason.startswith("INSUFFICIENT_DATA"))
        evs = O.track(s, [snap(T1 + k * MIN, 9950, above=None) for k in range(5)], CFG)
        self.assertEqual((evs[-1].state, evs[-1].reason, len(evs)), ("INVALIDATED", "SOURCE_INVALIDATED", 3))


class TimingRecorder(unittest.TestCase):
    def test_mfe_mae_not_written_before_horizon_elapses_in_replay_time(self):
        rnd, px, c1 = random.Random(3), 10000, []
        for k in range(385):
            o = px
            px += rnd.choice((-20, -10, 0, 10, 20))
            c1.append(candle(_ns(DAY, "09:15") + k * MIN, 1, o, max(o, px) + 5, min(o, px) - 5, px))
        bars = {b.start: b for b in map(T.bar_of, c1)}
        s = replace(BREAKOUT, first_price=bars[T0 - MIN].c, confirmed_price=bars[T1 - MIN].c, structural_stop=9000)
        hs = CFG.get("opportunity.timing.horizons_min")
        final = O.timing_rows(s, [], bars, 10300, lambda tf, t: ATR, CLOSE, CLOSE, CFG)
        key = lambda r: (r["anchor"], r["metric"])  # noqa: E731
        fin = {key(r): r for r in final}
        start = {"FIRST_DETECTION": T0, "CONFIRMATION": T1}
        for t in range(T0, CLOSE + 1, MIN):
            rows = O.timing_rows(s, [], bars, 10300, lambda tf, t: ATR, t, CLOSE, CFG)
            for r in rows:
                if r["anchor"] not in start:          # never TIMELY: written UNAVAILABLE only at the close
                    self.assertEqual(t, CLOSE, r)
                elif r["metric"].startswith("MFE_MAE_") and "UNAVAILABLE" not in r["value"]:
                    self.assertLessEqual(start[r["anchor"]] + int(r["metric"][8:-1]) * MIN, t, r)
                self.assertEqual(r, fin[key(r)], "a written row never changes later")
            if t < CLOSE:
                self.assertEqual(len([r for r in rows if r["metric"].startswith("MFE")]),
                                 sum(a + h * MIN <= t for a in start.values() for h in hs))
        w = [bars[T1 + k * MIN] for k in range(5)]
        v = fin[("CONFIRMATION", "MFE_MAE_5m")]["value"]
        self.assertEqual((v["mfe_paise"], v["mae_paise"]), (max(b.h for b in w) - s.confirmed_price,
                                                            s.confirmed_price - min(b.l for b in w)))
        self.assertEqual(fin[("FIRST_EXECUTABLE", "MFE_MAE_1m")]["value"]["UNAVAILABLE"][:12], "NEVER_TIMELY")

    def test_unusable_bar_makes_the_horizon_unavailable(self):
        c1 = [candle(T1 + k * MIN, 1, 10000, 10010, 9990, 10000, comp="PARTIAL" if k == 2 else "COMPLETE") for k in range(10)]
        bars = {b.start: b for b in map(T.bar_of, c1)}
        rows = {(r["anchor"], r["metric"]): r["value"] for r in
                O.timing_rows(BREAKOUT, [], bars, 10300, lambda tf, t: ATR, T1 + 10 * MIN, CLOSE, CFG)}
        self.assertIn("mfe_paise", rows[("CONFIRMATION", "MFE_MAE_1m")])
        self.assertIn("UNAVAILABLE", rows[("CONFIRMATION", "MFE_MAE_3m")])
        self.assertIn("UNAVAILABLE", rows[("CONFIRMATION", "TIME_TO_TARGET")])


class Store(unittest.TestCase):
    def test_append_only_and_idempotent(self):
        evs = {"b1": O.track(BREAKOUT, [snap(T1, 10200), snap(T1 + MIN, 10005)], CFG)}
        with tempfile.TemporaryDirectory() as d:
            n = O.write(Path(d), [BREAKOUT], evs, [], CFG.version)
            self.assertEqual((n, O.write(Path(d), [BREAKOUT], evs, [], CFG.version)), (4, 0))   # + the runs row


class EodStep(unittest.TestCase):
    def test_each_recorded_day_once_failures_isolated_and_retried(self):
        from unittest import mock
        from engine.eod import failed
        evs = {"b1": O.track(BREAKOUT, [snap(T1, 10200)], CFG)}
        calls = []

        def run_date(cfg, d, hist, cadence):
            calls.append(d)
            if d == "2026-11-05":
                raise ValueError("boom")
            return DAY, [BREAKOUT], evs, []
        with tempfile.TemporaryDirectory() as td, mock.patch.object(O, "run_date", run_date), \
                mock.patch.object(O, "history_reader", lambda cfg: lambda day: None):
            root = Path(td)
            for d in ("2026-11-04", "2026-11-05", "2026-11-06"):
                (root / d).mkdir()
            for d in ("2026-11-05", "2026-11-06"):
                (root / d / "parquet" / "snapshots").mkdir(parents=True)     # 2026-11-04: nothing recorded
            out = O.eod(root, root / "cadence.md")
            self.assertEqual(sorted(out), ["2026-11-05", "2026-11-06"])
            self.assertIn("boom", out["2026-11-05"]["error"])
            self.assertEqual(out["2026-11-06"]["rows_written"], 1 + 1 + 1)   # setup, evaluation, runs row
            self.assertTrue(O.done(root / "2026-11-06", CFG.version))
            self.assertTrue(failed({"days": {}, "opportunity": out}))
            again = O.eod(root, root / "cadence.md")                         # next night: only the failed day again
            self.assertEqual((sorted(again), calls), (["2026-11-05"], ["2026-11-05", "2026-11-06", "2026-11-05"]))
            self.assertFalse(failed({"days": {}, "opportunity": {"2026-11-06": out["2026-11-06"]}}))
            self.assertTrue(failed({"days": {}, "opportunity": {"error": "x"}}))


class ConfigTest(unittest.TestCase):
    def test_missing_opportunity_key_fails(self):
        vals = yaml.safe_load(Path(O.DEFAULT_CONFIG).read_text())
        del vals["opportunity"]["min_rr"]
        p = Path(tempfile.mkdtemp()) / "c.yaml"
        p.write_text(yaml.safe_dump(vals))
        with self.assertRaises(ConfigError):
            O.load(p)


if __name__ == "__main__":
    unittest.main()
