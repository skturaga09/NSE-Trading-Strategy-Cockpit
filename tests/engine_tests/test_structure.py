"""Phase 5: structure, liquidity, VWAP, LevelMap. Synthetic fixtures only (scripted bars + one flat history session)."""

import random
import tempfile
import re
import unittest
from datetime import date
from pathlib import Path

import yaml

from engine import structure as T
from engine.candles import MIN, _ns
from engine.config import ConfigError

DAY = date(2026, 11, 6)
O = _ns(DAY, "09:15")
TOK = 7
CFG = T.load()


def candle(start, tf, o, h, lo, c, vol=1000, vwap=None, comp="COMPLETE", status="OK"):
    return {"token": TOK, "interval": f"{tf}m", "start_ns": start, "end_ns": start + tf * MIN, "open": o, "high": h,
            "low": lo, "close": c, "volume": vol, "vwap": c if vwap is None else vwap, "completeness": comp,
            "quality": {"status": status}}


def series(bars, tf=3, bad=()):
    """bars: (h, l, c) or (o, h, l, c); open defaults to the previous close. Indexes in `bad` are PARTIAL."""
    out, pc = [], 10000
    for i, b in enumerate(bars):
        o, h, lo, c = b if len(b) == 4 else (pc, *b)
        out.append(candle(O + i * tf * MIN, tf, o, h, lo, c, comp="PARTIAL" if i in bad else "COMPLETE"))
        pc = c
    return out


def history():
    """Previous session 2026-11-05: flat 100.00, every minute high 100.50 / low 99.50 (3m TR = 100 paise);
    previous week: 2026-10-30 high 101.00 / low 99.00."""
    rows = []
    for d, h, lo in (("2026-10-30", 101.0, 99.0), ("2026-11-05", 100.5, 99.5)):
        for m in range(555, 555 + 385):                      # 09:15-15:39, as Kite futures minutes (F-HIST-9)
            rows.append([f"{d}T{m // 60:02d}:{m % 60:02d}:00+0530", 100.0, h, lo, 100.0, 1000, 0])
    return rows


def run(bars3, c1=(), tf=3, bad=()):
    return T.detect("STK", TOK, {f"{tf}m": series(bars3, tf, bad), "1m": list(c1)}, history(), CFG, DAY)


def of(dets, typ):
    return [d for d in dets if d.type == typ]


def end(i, tf=3):
    return O + (i + 1) * tf * MIN


UPTREND = [(10050, 9950, 10000), (10100, 10000, 10050), (10200, 10100, 10150), (10300, 10200, 10250),
           (10250, 10150, 10200), (10200, 10100, 10150), (10150, 10050, 10100), (10200, 10100, 10150),
           (10250, 10150, 10200), (10350, 10250, 10320), (10400, 10300, 10350), (10350, 10250, 10300),
           (10300, 10200, 10250), (10250, 10150, 10200), (10300, 10200, 10250), (10350, 10250, 10300)]
BOX = [(10060, 9960, 10010), (10040, 9940, 9990)] * 6


class Levels(unittest.TestCase):
    def test_history_and_opening_range_levels(self):
        c1 = [candle(O + k * MIN, 1, 10000, 10000 + 10 * k, 9990 - k, 10005) for k in range(15)]
        d = {x.type: x for x in run([], c1)}
        self.assertEqual((d["PDH"].level, d["PDL"].level, d["PDC"].level), (10050, 9950, 10000))
        self.assertEqual((d["PWH"].level, d["PWL"].level), (10100, 9900))
        self.assertEqual((d["ORH"].level, d["ORL"].level), (10140, 9976))
        self.assertEqual(d["ORH"].confirmed_ts, O + 15 * MIN)
        self.assertEqual(d["PDH"].source, ("HISTORICAL_API:2026-11-05",))
        c1[3] = candle(O + 3 * MIN, 1, 1, 1, 1, 1, comp="EMPTY")
        self.assertFalse(of(run([], c1), "ORH"), "an unusable minute in the window => no opening range")


    def test_atr_seed_continues_from_the_cut_last_bucket(self):
        rows = history()
        rows[-1][4] = 100.2                                   # 15:39 minute close
        for tf in CFG.get("structure.timeframes_min"):
            s = T.seed(rows, tf, DAY, date(2026, 11, 5), CFG)
            self.assertEqual((s.close, len(s.trs)), (10020, CFG.get("structure.atr.bars")), tf)


class Structure(unittest.TestCase):
    def test_swing_confirmed_after_right_bars_with_labels(self):
        dets = run(UPTREND)
        hs, ls = of(dets, "SWING_HIGH"), of(dets, "SWING_LOW")
        self.assertEqual([(h.level, h.attrs["swing_label"], h.confirmed_ts, h.created_ts) for h in hs],
                         [(10300, None, end(5), end(3)), (10400, "HH", end(12), end(10))])
        self.assertEqual([(x.level, x.attrs["swing_label"], x.confirmed_ts) for x in ls],
                         [(10050, None, end(8)), (10150, "HL", end(15))])
        self.assertEqual([t.attrs["state"] for t in of(dets, "TREND")], ["UP"])  # UNDEFINED until both sides have a label

    def test_every_detection_carries_type_level_times_source_and_config_version(self):   # Phase 5 R3 (Phase 15 G-8)
        dets = run(UPTREND + [(10450, 10350, 10430)])
        self.assertTrue(dets)
        for d in dets:
            self.assertTrue(d.type and d.source, d)
            self.assertTrue(d.level is not None or {"low", "high"} <= set(d.attrs) or d.type == "TREND", d)
            self.assertLessEqual(d.created_ts, d.confirmed_ts, d)
            self.assertEqual(d.config_version, CFG.version)
            self.assertTrue(all(re.match(r"^(\d+m@\d\d:\d\d|HISTORICAL_API:.+)$", x) for x in d.source), d.source)

    def test_bos_in_trend_direction(self):
        dets = run(UPTREND + [(10450, 10350, 10430)])
        bos = of(dets, "BOS_UP")
        self.assertEqual([(b.level, b.confirmed_ts, b.label) for b in bos], [(10400, end(16), "")])
        self.assertFalse(of(dets, "CHOCH_DOWN"))

    def test_choch_is_first_break_against_structure_and_heuristic(self):
        dets = run(UPTREND + [(10300, 10100, 10120), (10150, 10000, 10020)])
        ch = of(dets, "CHOCH_DOWN")
        self.assertEqual([(c.level, c.confirmed_ts, c.label) for c in ch], [(10150, end(16), "HEURISTIC")])
        self.assertFalse(of(dets, "BOS_UP"))

    def test_gap_breaks_the_pivot_window(self):
        dets = run(UPTREND, bad={4})
        self.assertNotIn(10300, [h.level for h in of(dets, "SWING_HIGH")])


class Breakouts(unittest.TestCase):
    def test_consolidation_then_accepted_breakout(self):
        dets = run(BOX + [(10150, 10000, 10120), (10180, 10080, 10140)])
        box = of(dets, "CONSOLIDATION")
        self.assertEqual([(b.attrs["high"], b.attrs["low"], b.confirmed_ts) for b in box], [(10060, 9940, end(11))])
        acc = of(dets, "BREAKOUT_ACCEPTED")
        self.assertEqual([(a.level, a.created_ts, a.confirmed_ts, a.attrs["via"]) for a in acc],
                         [(10060, end(12), end(13), "closes")])
        self.assertFalse(of(dets, "BREAKOUT_FAILED"))

    def test_failed_breakout_back_inside(self):
        dets = run(BOX + [(10150, 10000, 10120), (10130, 10000, 10030)])
        f = of(dets, "BREAKOUT_FAILED")
        self.assertEqual([(x.level, x.confirmed_ts, x.attrs["back_inside_bars"]) for x in f], [(10060, end(13), 1)])
        self.assertFalse(of(dets, "BREAKOUT_ACCEPTED"))

    def test_accepted_breakdown_by_hold_when_closes_threshold_is_higher(self):
        cfg = config_with(acceptance={"closes": 9, "hold_min": 6, "fail_bars": 3})
        dets = T.detect("STK", TOK, {"3m": series(BOX + [(10000, 9850, 9870), (9900, 9820, 9850), (9880, 9800, 9830)])},
                        history(), cfg, DAY)
        acc = of(dets, "BREAKDOWN_ACCEPTED")
        self.assertEqual([(a.level, a.confirmed_ts, a.attrs["via"]) for a in acc], [(9940, end(14), "hold")])


class Liquidity(unittest.TestCase):
    LOW = [(10100, 10000, 10050), (10050, 9950, 10000), (10000, 9900, 9950), (10050, 9950, 10000), (10100, 10000, 10050),
           (10150, 10050, 10100)]

    def test_bullish_sweep_and_reclaim(self):
        dets = run(self.LOW + [(10050, 9850, 9950)])
        sw = of(dets, "SWEEP_LOW")
        atr = next(v.attrs["atr"] for v in of(dets, "VWAP") if v.confirmed_ts == end(6))
        self.assertEqual([(s.level, s.attrs["extreme"], s.attrs["reclaim_bars"], s.confirmed_ts) for s in sw],
                         [(9900, 9850, 1, end(6))])
        self.assertAlmostEqual(sw[0].attrs["depth_atr"], 50 / atr, places=5)
        self.assertAlmostEqual(sw[0].attrs["rejection_rvol"], 1000 / 3000, places=5)

    def test_sweep_reclaimed_on_second_bar_and_not_after_k(self):
        two = of(run(self.LOW + [(10000, 9850, 9880), (9990, 9870, 9960)]), "SWEEP_LOW")
        self.assertEqual([(s.attrs["reclaim_bars"], s.created_ts, s.confirmed_ts) for s in two], [(2, end(6), end(7))])
        late = run(self.LOW + [(10000, 9850, 9880), (9890, 9860, 9870), (9990, 9870, 9960)])
        self.assertFalse(of(late, "SWEEP_LOW"), "held beyond for K bars: taken, not swept")

    def test_bearish_sweep_and_rejection(self):
        bars = [(10000, 9900, 9950), (10050, 9950, 10000), (10100, 10000, 10050), (10050, 9950, 10000),
                (10000, 9900, 9950), (9950, 9850, 9900), (10150, 9950, 10050)]
        sw = of(run(bars), "SWEEP_HIGH")
        self.assertEqual([(s.level, s.attrs["extreme"], s.attrs["reclaim_bars"]) for s in sw], [(10100, 10150, 1)])

    def test_equal_lows_cluster(self):
        bars = self.LOW + [(10100, 10000, 10050), (10050, 9950, 10000), (10000, 9905, 9950), (10050, 9950, 10000),
                           (10100, 10000, 10050)]
        eq = of(run(bars), "EQUAL_LOWS")
        self.assertEqual([(e.level, e.attrs["count"], e.confirmed_ts) for e in eq], [(9900, 2, end(10))])

    def test_reclaim_and_loss_of_key_levels(self):
        dets = run([(10040, 9990, 10030), (10080, 10020, 10070), (10070, 10010, 10020)])
        ev = [(d.type, d.attrs["level_type"], d.confirmed_ts) for d in dets if d.type in ("RECLAIM", "LOSS")]
        self.assertEqual(ev, [("RECLAIM", "PDH", end(1)), ("LOSS", "PDH", end(2))])


class Zones(unittest.TestCase):
    BARS = [(10000, 10030, 9980, 10010), (10010, 10030, 9990, 10000), (10000, 10210, 10000, 10200),
            (10200, 10250, 10150, 10220), (10220, 10220, 10020, 10100), (10150, 10080, 10140), (10200, 10120, 10180),
            (10260, 10170, 10250), (10300, 10220, 10280), (10280, 10280, 9900, 9950)]

    def test_demand_zone_test_defended_then_invalidated(self):
        dets = run(self.BARS)
        z = of(dets, "DEMAND_ZONE")
        self.assertEqual([(x.attrs["low"], x.attrs["high"], x.attrs["base_bars"], x.confirmed_ts) for x in z],
                         [(9980, 10030, 2, end(2))])
        self.assertEqual([(t.attrs["test"], t.confirmed_ts) for t in of(dets, "ZONE_TEST")], [(1, end(4)), (2, end(9))])
        dfd = of(dets, "ZONE_DEFENDED")
        atr = next(v.attrs["atr"] for v in of(dets, "VWAP") if v.confirmed_ts == end(7))
        self.assertEqual([d.confirmed_ts for d in dfd], [end(7)])
        self.assertAlmostEqual(dfd[0].attrs["reaction_atr"], (10260 - 10030) / atr, places=5)
        inv = of(dets, "ZONE_INVALIDATED")
        self.assertEqual([(i.attrs["zone"], i.confirmed_ts) for i in inv], [(z[0].id, end(9))])
        edges = lambda t: {x[0] for x in T.levels_at(dets, t)}  # noqa: E731
        self.assertIn("DEMAND_ZONE_LOW", edges(end(8)))
        self.assertNotIn("DEMAND_ZONE_LOW", edges(end(9)))


class LevelMapTest(unittest.TestCase):
    def test_nearest_obstacles_and_no_lookahead(self):
        dets = run(UPTREND)
        c1 = [candle(O + 16 * MIN, 1, 10260, 10270, 10250, 10260)]
        m = T.level_map("STK", TOK, dets, c1, O + 18 * MIN - 1)          # swing 10300 confirmed at 09:33
        self.assertEqual(m.price, 10260)
        self.assertIsNone(m.above)
        self.assertEqual((m.below.type, m.below.level, m.below.distance), ("VWAP", 10200, -60))   # latest 3m VWAP (bar 4)
        m = T.level_map("STK", TOK, dets, c1, end(5))
        self.assertEqual((m.above.type, m.above.level, m.above.distance), ("SWING_HIGH", 10300, 40))
        self.assertAlmostEqual(m.above.distance_atr["3m"], round(40 / m.atr["3m"], 4))
        at = [candle(O, 1, 10050, 10050, 10050, 10050)]
        m = T.level_map("STK", TOK, run([]), at, O + MIN)
        self.assertEqual((m.above.type, m.above.distance, m.below.type), ("PDH", 0, "PDC"))
        self.assertTrue(T.level_map("STK", TOK, run([]), [], O + MIN).price.reason.startswith("INSUFFICIENT_DATA"))


def random_day(seed):
    """A 1m random walk with a few PARTIAL minutes, rolled up into 3/5/15m candles (PARTIAL if any minute is)."""
    rnd, px, m1 = random.Random(seed), 10000, []
    for k in range(375):
        o = px
        px += rnd.choice((-30, -20, -10, 0, 10, 20, 30))
        h, lo = max(o, px) + rnd.randint(0, 20), min(o, px) - rnd.randint(0, 20)
        m1.append(candle(O + k * MIN, 1, o, h, lo, px, vol=rnd.randint(100, 900), vwap=10000 + k,
                         comp="PARTIAL" if rnd.random() < 0.01 else "COMPLETE"))
    out = {"1m": m1}
    for tf in CFG.get("structure.timeframes_min"):
        out[f"{tf}m"] = []
        for s in range(0, 375, tf):
            w = m1[s:s + tf]
            out[f"{tf}m"].append(candle(O + s * MIN, tf, w[0]["open"], max(x["high"] for x in w), min(x["low"] for x in w),
                                        w[-1]["close"], vol=sum(x["volume"] for x in w), vwap=w[-1]["vwap"],
                                        comp="PARTIAL" if any(x["completeness"] != "COMPLETE" for x in w) else "COMPLETE"))
    return out


class NonRepainting(unittest.TestCase):
    def test_prefix_equals_batch_filtered_and_nothing_before_confirmed_ts(self):
        """Look-ahead + non-repainting: candle-by-candle (every 1m close) == full-day batch cut at confirmed_ts."""
        rows = history()
        for seed in (1, 2, 3):
            day = random_day(seed)
            full = T.detect("STK", TOK, day, rows, CFG, DAY)
            self.assertGreater(len(of(full, "SWING_HIGH")), 10)
            self.assertEqual(full, T.detect("STK", TOK, day, rows, CFG, DAY), "same input twice => identical")
            for k in range(1, 376):
                t = O + k * MIN
                pre = T.detect("STK", TOK, {iv: [c for c in cs if c["end_ns"] <= t] for iv, cs in day.items()},
                               rows, CFG, DAY)
                self.assertTrue(all(d.confirmed_ts <= t for d in pre))
                self.assertEqual(pre, [d for d in full if d.confirmed_ts <= t], f"seed {seed} at minute {k}")

    def test_store_is_append_only_and_idempotent(self):
        dets = T.detect("STK", TOK, random_day(4), history(), CFG, DAY)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(T.write_detections(Path(d), dets), len(dets))
            self.assertEqual(T.write_detections(Path(d), dets), 0)


def config_with(**structure):
    vals = yaml.safe_load(Path(T.DEFAULT_CONFIG).read_text())
    vals["structure"].update(structure)
    d = tempfile.mkdtemp()
    p = Path(d) / "c.yaml"
    p.write_text(yaml.safe_dump(vals))
    return T.load(p)


class ConfigTest(unittest.TestCase):
    def test_missing_structure_key_fails(self):
        with self.assertRaises(ConfigError):
            config_with(swing={"left_bars": 2})


if __name__ == "__main__":
    unittest.main()
