"""Supertrend board (dashboard/supertrend.py): the indicator, the board row, and the once-per-candle alert."""

import random
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import supertrend as ST  # noqa: E402

IST = ST.IST


def bars(closes, start=datetime(2026, 11, 13, 9, 15, tzinfo=IST), spread=1.0):
    """5-minute candles from closes: open = previous close, high/low = max/min(open, close) +/- spread."""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append([(start + timedelta(minutes=5 * i)).isoformat(), o, max(o, c) + spread, min(o, c) - spread, c, 100])
        prev = c
    return out


def pine_reference(cs, period=10, mult=3.0):
    """TradingView's ta.supertrend written out as in its Pine source (direction -1 = up there): an independent copy."""
    res, atr, pu, pl, pst, pdir = [], None, None, None, None, None
    for i, (_, _, h, l, c, _) in enumerate(cs):
        pc = cs[i - 1][4] if i else None
        tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
        if i < period - 1:
            res.append(None)
            continue
        atr = sum(max(x[2] - x[3], abs(x[2] - cs[j - 1][4]) if j else 0, abs(x[3] - cs[j - 1][4]) if j else 0)
                  for j, x in enumerate(cs[:period])) / period if atr is None else (atr * (period - 1) + tr) / period
        src = (h + l) / 2
        upper, lower = src + mult * atr, src - mult * atr
        if pl is not None:
            lower = lower if (lower > pl or pc < pl) else pl
            upper = upper if (upper < pu or pc > pu) else pu
        if pst is None:
            direction = 1
        elif pst == pu:
            direction = -1 if c > upper else 1
        else:
            direction = 1 if c < lower else -1
        st = lower if direction == -1 else upper
        res.append((1 if direction == -1 else -1, st))
        pu, pl, pst, pdir = upper, lower, st, direction
    return res


class Indicator(unittest.TestCase):
    def test_matches_tradingview_formula_on_a_random_walk(self):
        rnd = random.Random(7)
        closes = [1000.0]
        for _ in range(499):
            closes.append(round(closes[-1] + rnd.gauss(0, 3), 2))
        cs = bars(closes)
        ours, ref = ST.supertrend(cs), pine_reference(cs)
        self.assertEqual([x and x[0] for x in ours], [x and x[0] for x in ref])
        for a, b in zip(ours, ref):
            if a:
                self.assertAlmostEqual(a[1], b[1], places=6)
        self.assertGreater(sum(1 for a, b in zip(ours, ours[1:]) if a and b and a[0] != b[0]), 5)   # it does flip

    def test_uptrend_then_a_sharp_drop_flips_down_on_that_candle(self):
        cs = bars([100 + i for i in range(30)] + [90])
        st = ST.supertrend(cs)
        self.assertEqual(st[29][0], 1)
        self.assertEqual(st[30][0], -1)
        self.assertGreater(st[30][1], 90)   # the DOWN line sits above price


class Row(unittest.TestCase):
    def test_flip_time_and_the_forming_candle_is_ignored(self):
        cs = bars([100 + i for i in range(30)] + [90, 89, 200])          # last candle (09:15 + 32*5) still forming
        closed = datetime.fromisoformat(cs[-2][0])
        r = ST.row("ABC", cs, closed)
        self.assertEqual((r["trend"], r["since"], r["since_close"], r["close"]), ("DOWN", cs[30][0], 90.0, 89.0))
        # flip candle body 129 -> 90 = 39; the 14 candles before it each range 3 (prev close inside), so 13x a normal candle
        self.assertEqual(r["since_strength"], 13.0)
        self.assertTrue(r["since_strong"])                 # 13x a normal candle is above STRONG_MIN

    def test_no_flip_in_history_says_so(self):
        cs = bars([100 + i for i in range(30)])
        r = ST.row("ABC", cs, datetime.fromisoformat(cs[-1][0]))
        self.assertEqual((r["trend"], r["since"], r["since_strength"]), ("UP", None, None))   # the only "flip" is away from the starting assumption
        self.assertEqual(r["since_at_least"], cs[ST.supertrend(cs).index(next(x for x in ST.supertrend(cs) if x and x[0] == 1))][0])


class FifteenMinute(unittest.TestCase):
    def test_three_5m_candles_make_one_15m_candle_and_the_open_one_is_left_out(self):
        cs = bars([10, 12, 11, 13, 14])                       # 09:15 .. 09:35
        c15 = ST.to_15m(cs, datetime.fromisoformat(cs[-1][0]))   # 09:30 candle has only 2 of its 3 slots closed
        self.assertEqual(len(c15), 1)
        self.assertEqual(c15[0][:5], [cs[0][0], cs[0][1], max(c[2] for c in cs[:3]), min(c[3] for c in cs[:3]), 11])
        self.assertEqual(len(ST.to_15m(cs + bars([15], start=datetime(2026, 11, 13, 9, 40, tzinfo=IST)),
                                       datetime(2026, 11, 13, 9, 40, tzinfo=IST))), 2)

    def test_agree_and_since_when_both_timeframes_turned(self):
        trend = [80 + 2 * i for i in range(60)] + [200 - i for i in range(60)]    # up, then 5 hours falling,
        cs = bars(trend + [141 + 4 * i for i in range(30)])                         # then a sharp, lasting rise
        r = ST.row("ABC", cs, datetime.fromisoformat(cs[-1][0]))
        self.assertEqual((r["trend"], r["trend_15m"], r["agree"]), ("UP", "UP", True))
        later = max(datetime.fromisoformat(r["since"]) + timedelta(minutes=5),
                    datetime.fromisoformat(r["since_15m"]) + timedelta(minutes=15))
        self.assertEqual(r["agree_since"], later.isoformat())
        self.assertEqual(r["open"], float(next(c for c in cs if c[0][:10] == cs[-1][0][:10])[1]))   # the board day's open
        monday = [["2026-11-16T09:15:00+05:30", 999.0, 1000.0, 990.0, 995.0, 0]]   # a new day: its own first candle
        self.assertEqual(ST.row("ABC", cs + monday, datetime.fromisoformat(monday[0][0]))["open"], 999.0)
        k = next(k for k in range(120, len(cs)) if ST.row("ABC", cs[:k + 1], datetime.fromisoformat(cs[k][0]))["trend"] == "UP")
        r = ST.row("ABC", cs[:k + 1], datetime.fromisoformat(cs[k][0]))   # the candle 5m turns, 15m not yet
        self.assertEqual((r["trend"], r["trend_15m"], r["agree"], r["agree_since"]), ("UP", "DOWN", False, None))


class Alerts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = [mock.patch.object(ST, "_STATE", Path(self.tmp.name) / "s.json"),
             mock.patch.object(ST, "_connected", return_value=True)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def board(self, bar, flips):
        rows = [{"symbol": s, "trend": t, "since": since, "close": 1.0} for s, t, since in flips]
        return {"bar": bar.isoformat(), "scanned_at": "", "rows": rows, "errors": {}}

    def test_scan_counts_only_new_flips_and_sends_no_phone_alert(self):
        t = lambda h, m: datetime(2026, 11, 13, h, m, 20, tzinfo=IST)   # noqa: E731
        b = lambda h, m: datetime(2026, 11, 13, h, m, tzinfo=IST).isoformat()   # noqa: E731
        with mock.patch("dashboard.exit_monitor.notify") as notify:   # owner 2026-11-14: alerts come only from TAKE signals
            # first scan of the day (10:21 -> candle 10:15): older flips are not counted
            with mock.patch.object(ST, "scan", return_value=self.board(ST._bar_start(t(10, 21)),
                                                                         [("A", "UP", b(10, 15)), ("B", "DOWN", b(9, 40))])):
                self.assertEqual(ST.check_and_alert(t(10, 21), market_open=True)["flips"], 1)
                self.assertEqual(ST.check_and_alert(t(10, 22), market_open=True), {"skipped": "candle 10:15 already scanned"})
            with mock.patch.object(ST, "scan", return_value=self.board(ST._bar_start(t(10, 26)),
                                                                         [("C", "DOWN", b(10, 20)), ("A", "UP", b(10, 15))])):
                self.assertEqual(ST.check_and_alert(t(10, 26), market_open=True)["flips"], 1)   # only C is new
            # a flip whose candle closes at 14:00 or later is on the board but not counted
            with mock.patch.object(ST, "scan", return_value=self.board(ST._bar_start(t(14, 1)),
                                                                         [("D", "UP", b(13, 55)), ("E", "DOWN", b(13, 50))])):
                self.assertEqual(ST.check_and_alert(t(14, 1), market_open=True)["flips"], 1)
        notify.assert_not_called()
        self.assertEqual(len(ST._load()["rows"]), 2)

    def test_closing_candle_is_scanned_just_after_the_bell(self):
        at = lambda d, h, m, s=20: datetime(2026, 11, d, h, m, s, tzinfo=IST)   # noqa: E731
        seen = []
        fake = lambda now: seen.append(now) or self.board(ST._bar_start(now), [])   # noqa: E731
        with mock.patch.object(ST, "scan", side_effect=fake):
            self.assertEqual(ST.check_and_alert(at(13, 15, 31))["bar"], at(13, 15, 25, 0).isoformat())  # Friday
            self.assertEqual(seen, [at(13, 15, 30, 0)])            # scanned as of the bell: no 15:30 candle exists
            self.assertEqual(ST.check_and_alert(at(13, 15, 32)), {"skipped": "candle 15:25 already scanned"})
            self.assertEqual(ST.check_and_alert(at(13, 15, 46)), {"skipped": "market closed"})   # window over
            self.assertEqual(ST.check_and_alert(at(14, 15, 31)), {"skipped": "market closed"})   # Saturday
            self.assertEqual(ST.check_and_alert(at(13, 8, 59)), {"skipped": "market closed"})    # before the open
            # Muhurat session (dashboard/special_sessions.json) closes at 15:40: its last candle is 15:35
            self.assertEqual(ST.check_and_alert(at(8, 15, 41))["bar"], at(8, 15, 35, 0).isoformat())
        self.assertEqual(len(seen), 2)

    def test_preopen_flags_stocks_opening_across_their_line_once_after_0908(self):
        rows = [{"symbol": "UPX", "trend": "UP", "line": 100.0}, {"symbol": "UPOK", "trend": "UP", "line": 100.0},
                {"symbol": "DNX", "trend": "DOWN", "line": 50.0}, {"symbol": "NOQ", "trend": "DOWN", "line": 50.0}]
        opens = {"UPX": 97.0, "UPOK": 101.0, "DNX": 51.0}   # NOQ: no auction match, no open price
        self.assertEqual([(r["symbol"], r["may_turn"], r["gap_pct"]) for r in ST.preopen_crossings(rows, opens)],
                         [("UPX", "DOWN", -3.0), ("DNX", "UP", 2.0)])   # biggest move first
        ST._STATE.write_text(ST.json.dumps({"bar": "2026-11-12T15:25:00+05:30", "rows": rows, "errors": {}}))
        at = lambda m: datetime(2026, 11, 13, 9, m, 20, tzinfo=IST)   # noqa: E731
        with mock.patch.object(ST, "_opening_prices", return_value=opens) as q:
            self.assertIn("still matching", ST.check_and_alert(at(8))["skipped"])     # auction can run to 09:08
            self.assertEqual(ST.check_and_alert(at(9)), {"preopen": 2, "priced": 3})
            self.assertEqual(ST.check_and_alert(at(12)), {"skipped": "pre-open already checked"})
        self.assertEqual(q.call_count, 1)
        self.assertEqual(ST._load()["preopen"]["opens"], opens)   # every opening price, for the board's Open column
        saved = ST._load()
        self.assertEqual((saved["bar"], saved["preopen"]["day"], len(saved["rows"])), ("2026-11-12T15:25:00+05:30", "2026-11-13", 4))
        with mock.patch.object(ST, "_opening_prices", side_effect=RuntimeError("TokenException")):
            ST._STATE.write_text(ST.json.dumps({"rows": rows}))
            self.assertIn("TokenException", ST.check_and_alert(at(10))["error"])
            self.assertNotIn("preopen", ST._load())                                # nothing saved: retried next minute

    def test_closed_market_failed_scan_and_pre_first_candle_do_nothing(self):
        self.assertEqual(ST.check_and_alert(datetime(2026, 11, 13, 9, 17, tzinfo=IST), market_open=True),
                         {"skipped": "today's first 5-minute candle has not closed yet"})
        self.assertEqual(ST.check_and_alert(datetime(2026, 11, 14, 11, 0, tzinfo=IST), market_open=False),
                         {"skipped": "market closed"})
        bad = {"bar": "x", "rows": [], "errors": {"A": "Incorrect `api_key` or `access_token`."}}
        with mock.patch.object(ST, "scan", return_value=bad):
            out = ST.check_and_alert(datetime(2026, 11, 13, 11, 0, 30, tzinfo=IST), market_open=True)
        self.assertIn("error", out)
        self.assertFalse(ST._STATE.exists())   # the last good board is kept; next minute retries


if __name__ == "__main__":
    unittest.main()
