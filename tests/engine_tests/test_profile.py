"""Phase 13: session volume profile (TICK_BASED / APPROXIMATE), profile levels, rejection at high-volume zones, Tier B depth
behaviour, the profile+depth score parts. Synthetic fixtures only."""

import json
import re
import unittest
from dataclasses import replace
from datetime import date

from engine import opportunity as O
from engine import profile as P
from engine import signals as G
from engine import structure as T
from engine.candles import MIN, S, Unavailable, _ns
from engine.config import REPO, load_config

CFG = load_config(REPO / "config/engine/v17.yaml")
V16 = load_config(REPO / "config/engine/v16.yaml")
DAY = date(2026, 11, 6)
OPEN = _ns(DAY, "09:15")
TOK, TICK = 7, 5                     # master tick_size 0.05 rupees = 5 paise
BASE = 2_000_000                     # 20,000.00 rupees: bin = 2,000,000 x 5 bps = 1,000 paise (a multiple of the tick)


def candle(k, o, h, lo, c, vol, comp="COMPLETE", status="OK"):
    s = OPEN + k * MIN
    return {"token": TOK, "interval": "1m", "start_ns": s, "end_ns": s + MIN, "open": o, "high": h, "low": lo, "close": c,
            "volume": vol, "vwap": c, "completeness": comp, "quality": {"status": status}}


def tick(t, ltp, cum, seq=[0]):     # noqa: B006  (a running sequence number)
    seq[0] += 1
    return (t // S, t, 0, seq[0], ltp, cum)


# Hand-computed fixture: bin volumes 10, 20, 50, 100, 40, 30, 5 at bins B0..B6 = BASE + k x 1,000 (each traded at the bin
# centre). Total 255; 70 % = 178.5. POC = B3 (100). Expand: B2 50 > B4 40 -> 150; then B1 20 < B4 40 -> 190 >= 178.5.
# Value area B2..B4: VAL = B2 low = BASE + 2,000; VAH = B4 high = BASE + 5,000; POC = B3 centre = BASE + 3,500.
VOLS = [10, 20, 50, 100, 40, 30, 5]
PLAN = [[(0, 10), (1, 20)], [(2, 50)], [(3, 60)], [(3, 40), (4, 40)], [(5, 30), (6, 5)]]   # minute -> (bin, qty)


def tick_day():
    ticks, c1, cum = [tick(OPEN - 30 * S, BASE + 500, 1000)], [], 1000      # pre-open baseline, as Phase 3's carry
    for k, prints in enumerate(PLAN):
        px = []
        for j, (b, q) in enumerate(prints):
            cum += q
            p = BASE + b * 1000 + 500
            ticks.append(tick(OPEN + k * MIN + (j + 1) * 10 * S, p, cum))
            px.append(p)
        c1.append(candle(k, BASE if k == 0 else px[0], max(px), min(px), px[-1], sum(q for _, q in prints)))
    return ticks, c1


class Levels(unittest.TestCase):
    def test_poc_and_value_area_match_the_hand_computation(self):
        lv = P.levels({BASE + k * 1000: v for k, v in enumerate(VOLS)}, 1000, CFG)
        self.assertEqual((lv.poc, lv.val, lv.vah), (BASE + 3500, BASE + 2000, BASE + 5000))
        self.assertEqual((lv.hvn, lv.lvn), ((), ()))

    def test_hvn_and_lvn(self):
        # smoothed (3-bin) volume peaks at B2 (36.7) and B6 (41.7, also the POC); trough B4 8.7 <= 0.25 x 41.7, between them
        lv = P.levels({10000 + k * 100: v for k, v in enumerate([5, 10, 80, 20, 1, 5, 90, 30, 5, 2])}, 100, CFG)
        self.assertEqual((lv.poc, lv.hvn, lv.lvn), (10650, (10250,), (10450,)))

    def test_poc_tie_goes_to_the_bin_nearest_the_middle_then_the_lower(self):
        self.assertEqual(P.levels({0: 50, 100: 10, 200: 10, 300: 50, 400: 10}, 100, CFG).poc, 350)
        self.assertEqual(P.levels({0: 10, 100: 50, 200: 50, 300: 10}, 100, CFG).poc, 150)

    def test_bin_is_bps_of_the_first_price_rounded_up_to_the_tick(self):
        self.assertEqual(P.bin_size(BASE, TICK, CFG), 1000)
        self.assertEqual(P.bin_size(150_000, 10, CFG), 80)       # 1,500.00 x 5 bps = 75 paise -> 80 on a 10-paise tick


class TickProfile(unittest.TestCase):
    def test_tick_profile_matches_the_hand_computed_poc_and_value_area(self):
        ticks, c1 = tick_day()
        p = P.profile_at("STK", TOK, c1, ticks, TICK, OPEN + 5 * MIN, DAY, CFG)
        self.assertEqual(p.method, P.TICK_BASED)
        self.assertEqual((p.poc, p.val, p.vah, p.coverage, p.total), (BASE + 3500, BASE + 2000, BASE + 5000, 1.0, 255))
        self.assertIn("last price", p.note)

    def test_minute_tick_volume_equals_its_candle_volume_or_the_minute_is_not_used(self):
        ticks, c1 = tick_day()
        c1[2] = dict(c1[2], volume=61)                          # candle disagrees with the tick deltas
        p = P.profile_at("STK", TOK, c1, ticks, TICK, OPEN + 5 * MIN, DAY, CFG)
        self.assertIsInstance(p, Unavailable)
        self.assertIn("coverage 0.80", p.reason)

    def test_no_look_ahead(self):
        ticks, c1 = tick_day()
        a = P.profile_at("STK", TOK, c1, ticks, TICK, OPEN + 2 * MIN, DAY, CFG)
        b = P.profile_at("STK", TOK, c1[:2], [x for x in ticks if x[1] <= OPEN + 2 * MIN], TICK, OPEN + 2 * MIN, DAY, CFG)
        self.assertEqual(a, b)
        self.assertEqual(a.total, 80)

    def test_partial_or_missing_minutes_make_the_profile_unavailable(self):
        ticks, c1 = tick_day()
        c1[1] = dict(c1[1], completeness="PARTIAL")
        p = P.profile_at("STK", TOK, c1, ticks, TICK, OPEN + 5 * MIN, DAY, CFG)
        self.assertIsInstance(p, Unavailable)
        self.assertTrue(p.reason.startswith("INSUFFICIENT_COVERAGE"))


class CandleProfile(unittest.TestCase):
    def test_candle_based_profile_is_labelled_approximate_in_data(self):
        _, c1 = tick_day()
        p = P.profile_at("STK", TOK, c1, None, TICK, OPEN + 5 * MIN, DAY, CFG)
        self.assertEqual(p.method, P.APPROXIMATE)
        self.assertIn("APPROXIMATE", p.note)
        self.assertIn("not a trade-at-price distribution", p.note)
        dets = P.profile_detections("STK", TOK, c1, None, TICK, (), DAY, CFG)
        levels = [d for d in dets if d.type in P.LEVEL_TYPES]
        self.assertTrue(levels)
        self.assertTrue(all(d.label == "APPROXIMATE" and d.attrs["method"] == "APPROXIMATE" for d in levels))

    def test_candle_volume_is_spread_evenly_over_the_range(self):
        c1 = [candle(k, 10000, 10299, 10000, 10100, 300) for k in range(5)]
        p = P.profile_at("STK", TOK, c1, None, 1, OPEN + 5 * MIN, DAY, replace(CFG, values={
            **CFG.values, "profile": {**CFG.values["profile"], "bin_bps": 100}}))
        self.assertEqual(p.bin, 100)
        self.assertEqual(dict(p.bins), {10000: 500.0, 10100: 500.0, 10200: 500.0})

    def test_no_ticks_for_the_token_falls_back_to_approximate(self):
        _, c1 = tick_day()
        self.assertEqual(P.profile_at("STK", TOK, c1, [], TICK, OPEN + 5 * MIN, DAY, CFG).method, P.APPROXIMATE)


class LevelMapAndExhaustion(unittest.TestCase):
    def test_level_map_uses_only_the_latest_profile_snapshot(self):
        ticks, c1 = tick_day()
        dets = P.profile_detections("STK", TOK, c1, ticks, TICK, (), DAY, CFG)
        first = OPEN + 5 * MIN
        lv = T.levels_at(dets, first)
        self.assertEqual(sorted((t, x) for t, _, x, _ in lv), [("PROFILE_POC", BASE + 3500), ("PROFILE_VAH", BASE + 5000),
                                                               ("PROFILE_VAL", BASE + 2000)])
        later = T.levels_at(dets, first + 5 * MIN)               # 09:25 snapshot: coverage 5/10 -> unavailable, no levels
        self.assertEqual(later, [])
        unav = [d for d in dets if d.type == "PROFILE_UNAVAILABLE" and d.confirmed_ts == first + 5 * MIN]
        self.assertTrue(unav and unav[0].attrs["reason"].startswith("INSUFFICIENT_COVERAGE"))

    def test_hvz_rejection_detection_and_exhaustion_flag(self):
        ticks, c1 = tick_day()
        poc = BASE + 3500
        c1.append(candle(5, poc - 2000, poc - 100, poc - 2100, poc - 1500, 10))   # probes the POC from below, closes 15 back
        vw = T.Detection("v", "VWAP", "STK", TOK, "5m", poc, OPEN, OPEN + 5 * MIN, (), {"atr": 2000.0}, "", "fixture")
        dets = P.profile_detections("STK", TOK, c1, ticks, TICK, (vw,), DAY, CFG)
        rej = [d for d in dets if d.type == "HVZ_REJECTION"]
        self.assertEqual([(d.level, d.attrs["direction"], d.attrs["zone"], d.confirmed_ts) for d in rej],
                         [(poc, -1, "PROFILE_POC", OPEN + 6 * MIN)])
        t = OPEN + 7 * MIN
        long_ = O.Setup("s", "BREAKOUT", "BREAKOUT_ACCEPTED", "STK", TOK, 5, 1, t, poc, t, poc, poc - 3000, None, 0.1, None)
        snap = O.Snapshot(t, poc - 1500, t, t, 2000.0, poc - 1500, None, tuple(dets), None, 2000.0)
        flags, notes = O.exhaustion(long_, snap, None, CFG)
        self.assertTrue(any(f.startswith("HIGH_VOLUME_ZONE_REJECTION") for f in flags), (flags, notes))
        self.assertFalse(any(f.startswith("HIGH_VOLUME_ZONE_REJECTION") for f in
                             O.exhaustion(replace(long_, direction=-1), snap, None, CFG)[0]))
        late = replace(snap, as_of=t + 30 * MIN)
        self.assertFalse(any(f.startswith("HIGH_VOLUME_ZONE_REJECTION") for f in O.exhaustion(long_, late, None, CFG)[0]))

    def test_configs_before_v17_keep_the_old_note(self):
        t = OPEN + 7 * MIN
        s = O.Setup("s", "BREAKOUT", "BREAKOUT_ACCEPTED", "STK", TOK, 5, 1, t, 100, t, 100, 90, None, 0.1, None)
        snap = O.Snapshot(t, 100, t, t, 10.0, 100, None, (), None, 10.0)
        self.assertIn("HIGH_VOLUME_ZONE_REJECTION skipped: no volume profile available yet", O.exhaustion(s, snap, None, V16)[1])
        self.assertIn("HIGH_VOLUME_ZONE_REJECTION not checked: no volume profile snapshot at as_of",
                      O.exhaustion(s, snap, None, CFG)[1])


def book(t, bid_q, ask_q, bid=BASE, ask=BASE + TICK):
    lv = lambda p, q, step: [[q if i == 0 else 100, p + step * i * TICK, 1] for i in range(5)]  # noqa: E731
    return {"token": TOK, "receive_ns": t, "exchange_ts": t // S, "bids": lv(bid, bid_q, -1), "asks": lv(ask, ask_q, 1)}


class Depth(unittest.TestCase):
    T1 = OPEN + 10 * MIN

    def window(self, asks, trades=()):
        snaps = [book(self.T1 - 60 * S + (i + 1) * 5 * S, 500, q) for i, q in enumerate(asks)]
        return snaps, list(trades)

    def test_replenishment_and_possible_absorption_at_the_offer(self):
        snaps, ticks = self.window([1000, 300, 900, 200, 950, 100, 1000])   # three refills of the best offer, price unmoved
        ticks = [tick(self.T1 - 50 * S + i * 5 * S, BASE + TICK, 10_000 + 600 * (i + 1)) for i in range(8)]
        d = P.depth_behaviour(snaps, ticks, self.T1, TICK, CFG)
        self.assertEqual(d["ask_replenishments"], 3)
        self.assertEqual(d["possible_absorption"], "POSSIBLE_ABSORPTION_AT_OFFER")
        self.assertEqual(d["ask_withdrawals"], 0, "the drops traded at that price")
        self.assertEqual(d["spread"], TICK)

    def test_withdrawal_needs_no_trade_at_the_price_and_less_volume_than_the_drop(self):
        snaps, _ = self.window([1000, 1000, 200])
        ticks = [tick(self.T1 - 52 * S, BASE, 10_000), tick(self.T1 - 46 * S, BASE, 10_050)]   # traded 50 at the bid only
        d = P.depth_behaviour(snaps, ticks, self.T1, TICK, CFG)
        self.assertEqual((d["ask_withdrawals"], d["possible_absorption"]), (1, None))

    def test_imbalance_from_visible_pending_quantity(self):
        d = P.depth_behaviour([book(self.T1 - S, 1100, 300)], [], self.T1, TICK, CFG)
        self.assertAlmostEqual(d["imbalance"], (1500 - 700) / 2200)

    def test_no_tier_b_snapshots_is_unavailable(self):
        d = P.depth_behaviour([], [], self.T1, TICK, CFG)
        self.assertIsInstance(d, Unavailable)
        self.assertTrue(d.reason.startswith("NOT_TIER_B"))

    def test_no_depth_field_claims_confirmed_spoofing_iceberg_or_aggressor(self):
        snaps, _ = self.window([1000, 300, 900, 200, 950, 100, 1000])
        ticks = [tick(self.T1 - 50 * S + i * 5 * S, BASE + TICK, 10_000 + 600 * (i + 1)) for i in range(8)]
        dets = P.depth_detections("STK", TOK, snaps, ticks, TICK, DAY, CFG)
        text = json.dumps([d.attrs | {"type": d.type, "label": d.label} for d in dets]
                          + [P.depth_behaviour(snaps, ticks, self.T1, TICK, CFG)], default=str)
        self.assertTrue(dets)
        self.assertNotRegex(text.lower(), r"confirm")
        self.assertIsNone(re.search(r"spoof|iceberg|aggress", " ".join(k for d in dets for k in d.attrs).lower()))
        self.assertTrue(all(d.label == "OBSERVED_IN_5_LEVEL_DEPTH" for d in dets))
        self.assertIn("observed in 5-level depth", text)


class ScoreParts(unittest.TestCase):
    def test_v17_profile_depth_parts_carry_weight_zero_and_scores_do_not_change(self):
        from tests.engine_tests.test_signals import inputs
        a, b = G.load(REPO / "config/engine/v16.yaml"), G.load(REPO / "config/engine/v17.yaml")
        ra, rb = G.recommend(inputs(), a), G.recommend(inputs(), b)
        self.assertEqual((ra.score.headline.points, ra.score.headline.available_max),
                         (rb.score.headline.points, rb.score.headline.available_max))
        fa = next(f for f in ra.score.headline.factors if f.name == "profile_depth")
        fb = next(f for f in rb.score.headline.factors if f.name == "profile_depth")
        self.assertEqual([p.name for p in fa.parts], ["volume_profile", "visible_depth"])
        self.assertEqual([(p.name, p.max_points) for p in fb.parts],
                         [("volume_profile", 0.0), ("depth_behaviour", 0.0), ("visible_depth", 5.0)])

    def test_profile_part_value_and_label(self):
        ticks, c1 = tick_day()
        dets = tuple(P.profile_detections("STK", TOK, c1, ticks, TICK, (), DAY, CFG))
        v, det = P.profile_part(1, BASE + 4000, dets, OPEN + 5 * MIN)
        self.assertEqual(v, 1.0)
        self.assertIn("TICK_BASED", det)
        v, det = P.profile_part(-1, BASE + 4000, tuple(P.profile_detections("STK", TOK, c1, None, TICK, (), DAY, CFG)),
                                OPEN + 5 * MIN)
        self.assertEqual(v, 0.0)
        self.assertIn("APPROXIMATE", det)
        self.assertIsInstance(P.profile_part(1, BASE, (), OPEN)[0], Unavailable)
        v, det = P.depth_part(1, (), OPEN)
        self.assertIsInstance(v, Unavailable)
        self.assertTrue(v.reason.startswith("NOT_TIER_B"))


class OutOfSample(unittest.TestCase):
    def rows(self, n, r1, r0):
        return [{"day": f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}", "t0": i, "r": r1 if i % 2 else r0,
                 "volume_profile": "1.0" if i % 2 else "0.0"} for i in range(n)]

    def test_below_final_or_small_samples_are_insufficient_and_weights_stay_zero(self):
        from engine import backtest as B
        bt = load_config(REPO / "config/engine/v17.yaml")
        st = B.factor_study(self.rows(10, 1.0, -1.0), "volume_profile", B.BELOW, bt)
        self.assertEqual((st["verdict"], st["weight"]), (B.INSUFFICIENT, "unchanged (0 in v17)"))
        self.assertEqual(B.factor_study(self.rows(10, 1.0, -1.0), "volume_profile", B.FINAL, bt)["verdict"], B.INSUFFICIENT)

    def test_final_with_separated_cis_adds_value_else_no_evidence(self):
        from engine import backtest as B
        bt = replace(CFG, values={**CFG.values, "backtest": {**CFG.values["backtest"], "min_trades": 20,
                                                             "bootstrap": {"resamples": 200, "ci": 0.95, "seed": 1}}})
        rows = [dict(r, r=r["r"] + (0.1 if i % 3 else -0.1)) for i, r in enumerate(self.rows(400, 1.0, -1.0))]
        self.assertEqual(B.factor_study(rows, "volume_profile", B.FINAL, bt)["verdict"], "ADDS_VALUE")
        same = [dict(r, r=(0.1 if i % 3 else -0.1)) for i, r in enumerate(self.rows(400, 0, 0))]
        self.assertEqual(B.factor_study(same, "volume_profile", B.FINAL, bt)["verdict"], "NO_EVIDENCE")

    def test_historical_dataset_lists_the_profile_as_not_representable(self):
        src = (REPO / "engine/backtest_report.py").read_text()
        self.assertIn("Phase 13 volume profile and depth behaviour (index: no volume, no depth, F-WS-7)", src)


class Purity(unittest.TestCase):
    def test_profile_core_reads_no_clock(self):
        src = (REPO / "engine/profile.py").read_text()
        core = src.split("# ---------------------------------------------------------------- edge")[0]
        for bad in ("time.time", "datetime.now", "date.today", "sqlite3.connect", "open(", "requests"):
            self.assertNotIn(bad, core)


if __name__ == "__main__":
    unittest.main()
