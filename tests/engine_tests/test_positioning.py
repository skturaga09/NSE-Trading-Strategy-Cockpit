"""Phase 4: positioning hypotheses. Synthetic fixtures only (a seeded 20-session history + one scripted day)."""

import json
import random
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from engine import positioning as P
from engine.candles import MIN, _ns
from engine.config import ConfigError

DAY = date(2026, 11, 6)
O = _ns(DAY, "09:15")
NF, NF2, SF, SF2, SSPOT, NSPOT = 1, 2, 11, 12, 21, 31  # NIFTY near/next, STK near/next, spots (fixture tokens)
BETA = 1.2
CFG = P.load()


def master(near_expiry="2026-11-23"):
    row = lambda u, s, typ, exp, ex: (u, s, typ, exp, "0", "1", "0.05", "NFO-FUT" if ex == "NFO" else "NSE", ex, "0")  # noqa: E731
    return {NF: row("NIFTY", "NIFTYNOV", "FUT", near_expiry, "NFO"), NF2: row("NIFTY", "NIFTYDEC", "FUT", "2026-12-29", "NFO"),
            SF: row("STK", "STKNOV", "FUT", near_expiry, "NFO"), SF2: row("STK", "STKDEC", "FUT", "2026-12-29", "NFO"),
            SSPOT: row("STK", "STK", "EQ", None, "NSE"), NSPOT: row("NIFTY", "NIFTY 50", "EQ", None, "NSE")}


def history(sessions=20, seed=7):
    """Kite-style minute rows per token before DAY: index noise, stock = BETA x index + own noise, OI noise."""
    rnd, days, d = random.Random(seed), [], DAY
    for _ in range(sessions):
        d = P.prev_session(d, CFG)
        days.append(d)
    rows = {t: [] for t in (NF, NF2, SF, SF2)}
    pi, ps, oi = 24000.0, 2500.0, {NF: 1e7, NF2: 2e6, SF: 1e6, SF2: 2e5}
    for d in sorted(days):
        for m in range(375):
            ri = rnd.gauss(0, 0.0003)
            pi *= 1 + ri
            ps *= 1 + BETA * ri + rnd.gauss(0, 0.0003)
            ts = f"{d.isoformat()}T{9 + (15 + m) // 60:02d}:{(15 + m) % 60:02d}:00+0530"
            for t in oi:
                oi[t] *= 1 + rnd.gauss(0, 0.001)
            for t, p in ((NF, pi), (NF2, pi * 1.001), (SF, ps), (SF2, ps * 1.001)):
                rows[t].append([ts, p, p, p, p, 1000, round(oi[t])])
    return lambda tok: rows.get(tok, [])


def candle(tok, end, close, oi, status="OK", completeness="COMPLETE", oi_age=30.0, vol=1000):
    return {"token": tok, "end_ns": end, "close": close, "open": close, "high": close + 5, "low": close - 5,
            "volume": vol, "trades": 50, "vwap": close, "completeness": completeness, "oi_at_close": oi,
            "oi_age_seconds": oi_age, "quality": {"status": status, "oi_age": oi_age}}


def session(n=60, idx=None, extra=None, near_oi=None, next_oi=None, transfer=False, comb_status="OK"):
    """Scripted day: per-minute relative steps (lists of length n; None = 0). Prices in paise, like snapshots."""
    z = [0.0] * n
    idx, extra, near_oi, next_oi = idx or z, extra or z, near_oi or z, next_oi or z
    d = P.DayData({}, {}, {}, {})
    pi, ps = 24000.0, 2500.0
    o = {NF: 1e7, NF2: 2e6, SF: 1e6, SF2: 2e5}
    o0 = dict(o)
    bars = {t: [] for t in (NF, SF)}
    for i in range(1, n + 1):
        end = O + i * MIN
        pi *= 1 + idx[i - 1]
        ps *= 1 + BETA * idx[i - 1] + extra[i - 1]
        for near, nxt in ((NF, NF2), (SF, SF2)):
            o[near] *= 1 + near_oi[i - 1]
            o[nxt] = o0[nxt] + (o0[near] - o[near]) if transfer else o[nxt] * (1 + next_oi[i - 1])
        for t, p in ((NF, pi), (NF2, pi * 1.001), (SF, ps), (SF2, ps * 1.001), (SSPOT, ps - 1), (NSPOT, pi - 1)):
            c = candle(t, end, round(p * 100), round(o[t]) if t in o else None)
            d.c1.setdefault(t, {})[end] = c
            if t in bars:
                bars[t].append(c)
        for und, toks in (("NIFTY", (NF, NF2)), ("STK", (SF, SF2))):
            tot = sum(round(o[t]) for t in toks)
            d.comb.setdefault(und, {})[end] = {"underlying": und, "end_ns": end, "oi": tot,
                                               "components": [[t, round(o[t]), 30.0] for t in toks],
                                               "quality": {"status": comb_status, "oi_age": 30.0 if comb_status == "OK" else 400.0}}
        if i % 5 == 0:
            for t, bs in bars.items():
                last = bs[-5:]
                d.c5.setdefault(t, {})[end] = {**last[-1], "high": max(b["high"] for b in last),
                                               "low": min(b["low"] for b in last)}
    return d


CADENCE = {NF: 60.0, NF2: 60.0, SF: 60.0, SF2: 600.0, "COMBINED:NIFTY": 60.0, "COMBINED:STK": 60.0}


def run(d, hist=None, cadence=CADENCE, m=None):
    return P.evaluate_day(d, m or master(), hist or HIST, cadence, CFG, DAY)


def at(states, und, minute):
    return next(s for s in states if s.underlying == und and s.ts_ns == O + minute * MIN)


def steps(n, start, v):
    return [v if i >= start else 0.0 for i in range(n)]


HIST = history()
N = 60


class Quadrants(unittest.TestCase):
    def test_each_quadrant(self):
        for price, oi, want in ((0.0006, 0.002, P.LONG_BUILDUP), (-0.0006, 0.002, P.SHORT_BUILDUP),
                                (0.0006, -0.002, P.SHORT_COVERING), (-0.0006, -0.002, P.LONG_UNWINDING)):
            with self.subTest(want=want):
                st = at(run(session(N, extra=steps(N, 20, price), near_oi=steps(N, 20, oi), next_oi=steps(N, 20, oi))),
                        "STK", 55)
                self.assertEqual(st.primary.positioning_hypothesis, want, st.primary)
                self.assertEqual(st.raw.positioning_hypothesis, want)   # index flat: raw agrees
                self.assertEqual(st.near_month.positioning_hypothesis, want)

    def test_mixed_windows_are_neutral(self):
        # price falls for 25 minutes, then jumps for the last 5; OI rises throughout: 5 min says LONG_BUILDUP,
        # 30 min says SHORT_BUILDUP => conflicting
        extra = [0.0] * 20 + [-0.0008] * 25 + [0.0012] * 5 + [0.0] * 10
        st = at(run(session(N, extra=extra, near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002))), "STK", 50)
        w = {x.window_min: x.quadrant for x in st.primary.windows}
        self.assertEqual((w[5], w[30]), (P.LONG_BUILDUP, P.SHORT_BUILDUP))
        self.assertEqual(st.primary.positioning_hypothesis, P.NEUTRAL)
        self.assertIn("CONFLICTING_WINDOWS", st.primary.reasons)

    def test_oi_up_with_flat_price_is_not_a_buildup(self):
        st = at(run(session(N, near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002))), "STK", 55)
        self.assertEqual(st.primary.positioning_hypothesis, P.NEUTRAL)
        self.assertEqual(st.primary.reasons, ("NOT_SIGNIFICANT",))
        self.assertTrue(all(w.oi_sig == 1 and w.price_sig == 0 for w in st.primary.windows))

    def test_move_with_beta_times_index_is_index_driven(self):
        st = at(run(session(N, idx=steps(N, 20, 0.0005), near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002))),
                "STK", 55)
        self.assertEqual(st.raw.positioning_hypothesis, P.LONG_BUILDUP)
        self.assertEqual(st.primary.positioning_hypothesis, P.NEUTRAL)
        self.assertIn("INDEX_DRIVEN", st.primary.reasons)
        self.assertLess(abs(st.feature("residual_chg_5m_pct")), 0.1 * abs(st.feature("fut_price_chg_5m_pct")))

    def test_index_itself_uses_raw_price(self):
        st = at(run(session(N, idx=steps(N, 20, 0.0005), near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002))),
                "NIFTY", 55)
        self.assertEqual(st.primary.positioning_hypothesis, P.LONG_BUILDUP)
        self.assertEqual(st.primary, st.raw)


class Filters(unittest.TestCase):
    def long_buildup(self, **kw):
        return session(N, extra=steps(N, 20, 0.0006), near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002), **kw)

    def test_stale_oi_suppressed(self):
        st = at(run(self.long_buildup(comb_status="DEGRADED")), "STK", 55)
        self.assertEqual(st.primary.positioning_hypothesis, P.NEUTRAL)
        self.assertEqual(st.primary.reasons, ("OI_STALE",))
        f = next(f for f in st.features if f.name == "combined_oi_chg_5m_pct")
        self.assertEqual(f.quality.status, "UNAVAILABLE")
        self.assertTrue(f.value.reason.startswith("OI_STALE"))

    def test_rollover_near_falls_next_rises_combined_flat_is_not_long_unwinding(self):
        st = at(run(session(N, extra=steps(N, 20, -0.0006), near_oi=steps(N, 20, -0.003), transfer=True),
                    m=master(near_expiry="2026-11-09")), "STK", 55)
        self.assertNotEqual(st.primary.positioning_hypothesis, P.LONG_UNWINDING)
        self.assertEqual(st.primary.reasons, ("NOT_SIGNIFICANT",))            # combined OI flat
        self.assertTrue(any(f.startswith("ROLLOVER_WINDOW") for f in st.flags))
        self.assertEqual(st.near_month.suppressed_hypothesis, P.LONG_UNWINDING)  # what near-month OI alone says
        self.assertEqual(st.near_month.reasons, ("ROLLOVER_WINDOW",))

    def test_expiry_day_suppresses_every_view(self):
        st = at(run(self.long_buildup(), m=master(near_expiry=DAY.isoformat())), "STK", 55)
        for v in (st.primary, st.raw, st.near_month):
            self.assertEqual((v.positioning_hypothesis, v.reasons, v.suppressed_hypothesis),
                             (P.NEUTRAL, ("EXPIRY_DAY",), P.LONG_BUILDUP))

    def test_illiquid_future(self):
        d = self.long_buildup()
        for c in d.c1[SF].values():
            c["trades"] = 0
        st = at(run(d), "STK", 55)
        self.assertEqual((st.primary.reasons, st.primary.suppressed_hypothesis), (("ILLIQUID_FUTURE",), P.LONG_BUILDUP))

    def test_implausible_oi_jump(self):
        d = self.long_buildup()
        for t in (SF, SF2):
            for end, c in d.c1[t].items():
                if end >= O + 53 * MIN:
                    c["oi_at_close"] *= 3
        for end, x in d.comb["STK"].items():
            if end >= O + 53 * MIN:
                x["oi"] *= 3
        st = at(run(d), "STK", 55)
        self.assertEqual(st.primary.positioning_hypothesis, P.NEUTRAL)
        self.assertIn("OI_JUMP_INVALID", st.primary.reasons)

    def test_low_sample_history(self):
        st = at(run(self.long_buildup(), hist=history(sessions=0)), "STK", 55)
        self.assertEqual(st.primary.positioning_hypothesis, P.NEUTRAL)
        self.assertIn("LOW_SAMPLE", st.primary.reasons)

    def test_window_shorter_than_measured_cadence_is_disabled(self):
        # a slow far month alone (SF2 600 s) does not gate the combined series; its own COMBINED row does
        st = at(run(self.long_buildup(), cadence={**CADENCE, "COMBINED:STK": 400.0}), "STK", 55)
        w = {x.window_min: x for x in st.primary.windows}
        self.assertEqual(w[5].reason, "OI_WINDOW_DISABLED")
        self.assertEqual(w[15].quadrant, P.LONG_BUILDUP)
        self.assertEqual({x.window_min: x.reason for x in st.near_month.windows}[5], None)   # near: its own 60 s
        st = at(run(self.long_buildup(), cadence={}), "STK", 55)
        self.assertEqual(st.primary.reasons, ("OI_WINDOW_DISABLED",))


class Features(unittest.TestCase):
    """Phase 4 F3-F6 values, each checked against the formula applied by hand to the fixture candles (Phase 15 G-8)."""

    def test_rvol_volume_oi_ratio_vwap_move_momentum_and_basis(self):
        fw, t = CFG.get("positioning.feature_window_min"), O + 55 * MIN
        d = session(N, extra=steps(N, 20, 0.0006), near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002))
        ends = [t - k * MIN for k in range(fw)]
        for e in ends:                                   # today's volume = 2 x the 1,000/min history baseline
            d.c1[SF][e]["volume"] = d.c1[SF2][e]["volume"] = 2000
        d.c1[SF][t]["vwap"] = d.c1[SF][t]["close"] - 500
        st = at(run(d), "STK", 55)
        atr, close = st.feature("atr"), d.c1[SF][t]["close"]
        self.assertAlmostEqual(st.feature(f"rvol_{fw}m"), 2.0)                                   # F3
        oi_chg = abs(d.comb["STK"][t]["oi"] - d.comb["STK"][t - fw * MIN]["oi"])
        self.assertAlmostEqual(st.feature(f"volume_oi_ratio_{fw}m"), 2 * 2000 * fw / oi_chg)    # F4: both futures
        self.assertAlmostEqual(st.feature("vwap_dev_atr"), 500 / atr, places=5)                  # F5 (features: 6 dp)
        self.assertAlmostEqual(st.feature(f"atr_move_{fw}m"), (close - d.c1[SF][t - fw * MIN]["close"]) / atr, places=5)
        self.assertEqual(st.feature(f"momentum_{fw}m_roc_pct"), st.feature(f"fut_price_chg_{fw}m_pct"))
        self.assertEqual(st.feature("basis"), close - d.c1[SSPOT][t]["close"])                   # F6: paise
        self.assertEqual(st.feature(f"basis_chg_{fw}m"), st.feature("basis") -
                         (d.c1[SF][t - fw * MIN]["close"] - d.c1[SSPOT][t - fw * MIN]["close"]))
        self.assertFalse(any(f.startswith("ABNORMAL_BASIS") for f in st.flags))

    def test_abnormal_basis_flag_and_too_few_samples(self):
        d = session(N)
        for i, e in enumerate(sorted(d.c1[SSPOT])):      # basis wobbles by a few paise (a constant basis has no z)
            d.c1[SSPOT][e]["close"] += i % 3
        d.c1[SSPOT][O + 55 * MIN]["close"] -= 50_000     # spot prints far below the future: basis jumps
        st = at(run(d), "STK", 55)
        self.assertGreater(abs(st.feature("basis_z")), CFG.get("positioning.basis.abnormal_z"))
        self.assertTrue(any(f.startswith("ABNORMAL_BASIS") for f in st.flags))
        early = at(run(session(N)), "STK", 10)          # 9 earlier basis values < min_samples
        self.assertIsNone(early.feature("basis_z"))


class Events(unittest.TestCase):
    def test_confirmation_evidence_and_invalidation(self):
        extra = [0.0] * 20 + [0.0006] * 20 + [-0.003] * 20
        states = run(session(N, extra=extra, near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002)))
        ev = P.track_events(states, CFG)
        stk = [e for e in ev if e["underlying"] == "STK"]
        # the reversal (price down, OI still up) invalidates the event, then confirms a new SHORT_BUILDUP
        self.assertEqual([(e["state"], e["positioning_hypothesis"]) for e in stk],
                         [("CONFIRMED", P.LONG_BUILDUP), ("INVALIDATED", P.LONG_BUILDUP), ("CONFIRMED", P.SHORT_BUILDUP)])
        self.assertRegex(stk[1]["reason"], "^(PRICE_THROUGH_FIRST_OBSERVED|OPPOSITE_HYPOTHESIS)")
        c = stk[0]
        first = next(s for s in sorted(states, key=lambda s: s.ts_ns) if s.underlying == "STK"
                     and s.primary.positioning_hypothesis == P.LONG_BUILDUP)
        self.assertEqual(c["first_observed_ts"], P.iso(first.ts_ns))
        self.assertEqual(c["confirmed_ts"], P.iso(first.ts_ns + (CFG.get("positioning.confirm_count") - 1) * MIN))
        for k in ("event_id", "contracts", "direction", "price_first_observed_paise", "price_confirmed_paise",
                  "oi_baseline", "oi_current", "oi_change_pct", "oi_percentile", "rvol_15m", "vwap",
                  "residual_move_pct", "raw_move_pct", "data_quality", "contradicting_evidence", "invalidation"):
            self.assertIn(k, c)
            self.assertIsNotNone(c[k], k)
        self.assertIsNotNone(c["oi_baseline"]["oi_age_s"])
        self.assertIsNotNone(c["invalidation"][1]["level_paise"])
        self.assertEqual(stk[1]["event_id"], c["event_id"])

    def test_replay_gives_the_same_events_every_run(self):
        d = session(N, extra=steps(N, 20, 0.0006), near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002))
        rows = [("candle", f"{c['token']}:1m", e, json.dumps(c)) for t in d.c1 for e, c in d.c1[t].items()]
        rows += [("candle", f"{c['token']}:5m", e, json.dumps(c)) for t in d.c5 for e, c in d.c5[t].items()]
        rows += [("combined_oi", f"{u}:1m", e, json.dumps(x)) for u in d.comb for e, x in d.comb[u].items()]
        outs = []
        for seed in (1, 2, 3):
            random.Random(seed).shuffle(rows)
            ev = P.track_events(run(P.day_from_snapshots(sorted(rows) if seed == 1 else rows)), CFG)
            outs.append(json.dumps(P.jsonable(ev), sort_keys=True))
        self.assertTrue(json.loads(outs[0]))
        self.assertEqual(len(set(outs)), 1)
        with tempfile.TemporaryDirectory() as tmp:  # append-only store: a second write adds nothing
            ev = json.loads(outs[0])
            self.assertEqual(P.write_events(Path(tmp), ev), len(ev))
            self.assertEqual(P.write_events(Path(tmp), ev), 0)


class Language(unittest.TestCase):
    RX = re.compile("institution", re.I)

    def test_no_output_text_says_institution_except_the_disclaimer(self):
        src = Path(P.__file__).read_text()
        lines = [ln for ln in src.splitlines() if self.RX.search(ln)]
        self.assertEqual(len(lines), 1, lines)                      # the DISCLAIMER constant only
        self.assertIn("not evidence of institutional", P.DISCLAIMER)
        states = run(session(N, extra=steps(N, 20, 0.0006), near_oi=steps(N, 20, 0.002), next_oi=steps(N, 20, 0.002)))
        ev = P.track_events(states, CFG)
        with tempfile.TemporaryDirectory() as tmp:
            text = P.report(CFG, {DAY.isoformat(): (states, ev)}, Path(tmp) / "r.md")
        blob = json.dumps(P.jsonable(states)) + json.dumps(P.jsonable(ev)) + text.replace(P.DISCLAIMER, "")
        self.assertIsNone(self.RX.search(blob))
        self.assertIn("positioning_hypothesis", blob)


class Config(unittest.TestCase):
    def test_v5_loads_and_missing_positioning_key_fails(self):
        self.assertEqual(CFG.version, "v5")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.yaml"
            p.write_text(P.DEFAULT_CONFIG.read_text().replace("confirm_count: 3", "confirm_count:"))
            with self.assertRaises(ConfigError):
                P.load(p)

    def test_cadence_parser_takes_the_max_over_dates(self):
        text = ("| date | instrument | token | OI changes | intervals | median s | p90 s | max s |\n|---|---|---|---|---|---|---|---|\n"
                "| 2026-11-06 | NFO:X | 5 | 10 | 9 | 30 | 60 | 90 |\n| 2026-11-07 | NFO:X | 5 | 10 | 9 | 30 | 120 | 200 |\n"
                "| 2026-11-07 | NFO:Y | 6 | 1 | 0 | None | None | None |\n"
                "| 2026-11-07 | COMBINED:X | combined | 30 | 29 | 20 | 45 | 80 |\n")
        self.assertEqual(P.parse_cadence(text, "p90_s"), {5: 120.0, "COMBINED:X": 45.0})


if __name__ == "__main__":
    unittest.main()
