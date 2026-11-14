"""Phase 3: candles, OI at close, combined OI, depth snapshots, data quality. Fixture events only."""

import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from engine.candles import S, Aggregator, Candle, CombinedOI, DepthSnapshot, LateTick, QualityChange, Unavailable, _ns
from engine.packets import DEPTH_FIELDS, TICK_FIELDS
from engine.store import Event

from .fixtures import make_config

DAY = date(2026, 11, 6)  # Friday, an F&O trading day (F-NSE-5)
O = _ns(DAY, "09:15")
FUT, FUT2, FUT3, EQ, IDX = 101, 102, 103, 201, 301


def at(hms: str) -> int:
    """'09:16:05.5' -> ns."""
    h, m, s = hms.split(":")
    return _ns(DAY, f"{h}:{m}") + int(float(s) * S)


def tick(tok, ex: str | None, ltp, volume=None, oi=None, rns: str | None = None, mode="full", conn=0, seq=0, **kw):
    r = at(rns) if rns else at(ex) + S // 10
    f = dict.fromkeys(TICK_FIELDS)
    f.update(mode=mode, ltp=ltp, volume=volume, atp=ltp if volume is not None else None)
    if volume is not None:  # every quote field present, as in a real packet (F-WS-4)
        f.update(ltq=1, tbq=1, tsq=1, open=ltp, high=ltp, low=ltp, close=ltp)
    if mode == "full":
        f.update(oi=oi, last_trade_ts=at(ex) // S)
    f.update(kw)
    return Event(at(ex) // S if (ex and mode == "full") else None, r, conn, seq, "tick", tok, tuple(f.items()))


def plan(rns: str, **toks):
    """toks: name=(token, mode, tiers, kind, underlying)."""
    detail = json.dumps({"plan": {str(t): [m, tiers, k, u] for t, m, tiers, k, u in toks.values()}})
    return Event(None, at(rns), -1, 0, "conn", -1, (("event", "tier_plan"), ("detail", detail)))


def conn(kind: str, rns: str, c=0):
    return Event(None, at(rns), c, 0, "conn", -1, (("event", kind), ("detail", "{}")))


def gap(start: str, end: str, kind="disconnect", c=0):
    row = dict(start_ns=at(start), end_ns=at(end), conn=c, kind=kind, reason="fixture", count=None)
    return Event(None, at(end), c, 0, "gap", -1, tuple(row.items()))


def depth(tok, rns: str, bid=(10, 100000, 1), ask=(12, 100050, 2)):
    vals = []
    for side in (bid, ask):
        vals += list(side) + [0, 0, 0] * 4
    return Event(at(rns) // S, at(rns), 0, 0, "depth", tok, tuple(zip(DEPTH_FIELDS, vals)))


def run(events, until: str, trading_day=True, **cfg):
    agg = Aggregator(make_config(Path("/tmp"), **cfg), DAY, trading_day)
    out = []
    for e in events:
        out += agg.on_event(e)
    return out + agg.advance(at(until))


def candles(out, tok, interval):
    return {c.start_ns: c for c in out if isinstance(c, Candle) and c.token == tok and c.interval == interval}


FUT_PLAN = dict(f=(FUT, "full", "A", "FUT", "X"))


class TestCandles(unittest.TestCase):
    def test_ohlc_volume_trades_and_rollups(self):
        out = run([plan("09:00:00", **FUT_PLAN),
                   tick(FUT, "09:14:50", 1000, 100, 500),              # pre-open: baseline only, no candle
                   tick(FUT, "09:15:10", 1010, 110, 500),
                   tick(FUT, "09:15:40", 1005, 130, 520),
                   tick(FUT, "09:16:05", 1005, 130, 520, tbq=9),       # no trade: volume unchanged
                   tick(FUT, "09:16:30", 1020, 150, 520)], "09:21:16")
        m = candles(out, FUT, "1m")
        self.assertNotIn(at("09:14:00"), m)
        c = m[at("09:15:00")]
        self.assertEqual((c.open, c.high, c.low, c.close, c.volume, c.trades, c.ticks, c.completeness),
                         (1010, 1010, 1005, 1005, 30, 2, 2, "COMPLETE"))
        self.assertEqual((c.oi_at_close, c.oi_last_change_ns, c.oi_age_seconds), (520, at("09:15:40"), 20.0))
        self.assertEqual((c.vwap, c.time_basis, c.first_tick_ns, c.last_tick_ns), (1005, "exchange", at("09:15:10"), at("09:15:40")))
        c = m[at("09:16:00")]
        self.assertEqual((c.open, c.close, c.volume, c.trades, c.ticks), (1020, 1020, 20, 1, 2))
        e = m[at("09:17:00")]
        self.assertEqual((e.completeness, e.volume, e.open), ("EMPTY", 0, Unavailable("no trade in candle")))
        for iv in ("3m", "5m"):
            r = candles(out, FUT, iv)[at("09:15:00")]
            self.assertEqual((r.open, r.high, r.low, r.close, r.volume, r.trades, r.completeness),
                             (1010, 1020, 1005, 1020, 50, 3, "COMPLETE"), iv)
        self.assertEqual(sorted(candles(out, FUT, "3m")), [at("09:15:00"), at("09:18:00")])
        self.assertEqual(c.quality.processing_ts, at("09:17:15"))   # minute end + finalize_delay_s (15)

    def test_gap_inside_candle_is_partial_with_nothing_interpolated(self):
        ev = [plan("09:00:00", **FUT_PLAN), tick(FUT, "09:14:59", 1000, 100, 500)]
        ev += [tick(FUT, f"09:15:{s:02d}", 1000 + s, 100 + s, 500) for s in range(0, 60, 10)]
        ev += [tick(FUT, "09:16:20", 1080, 180, 500), conn("close", "09:16:25"),
               conn("connect", "09:18:15"), gap("09:16:25", "09:18:15"),
               tick(FUT, "09:18:20", 1200, 900, 500), tick(FUT, "09:18:50", 1210, 950, 500),
               tick(FUT, "09:19:10", 1220, 960, 500)]
        m = candles(run(ev, "09:21:16"), FUT, "1m")
        self.assertEqual(m[at("09:15:00")].completeness, "COMPLETE")
        for t in ("09:16:00", "09:17:00", "09:18:00"):
            c = m[at(t)]
            self.assertEqual(c.completeness, "PARTIAL", t)
            self.assertIsInstance(c.volume, Unavailable, t)
            self.assertIsInstance(c.trades, Unavailable, t)
        self.assertIsInstance(m[at("09:17:00")].open, Unavailable)    # no price invented inside the gap
        self.assertEqual(m[at("09:16:00")].close, 1080)               # observed values stay, flagged PARTIAL
        c = m[at("09:19:00")]
        self.assertEqual((c.completeness, c.volume, c.open), ("COMPLETE", 10, 1220))
        f = candles(run(ev, "09:21:16"), FUT, "5m")[at("09:15:00")]
        self.assertEqual(f.completeness, "PARTIAL")
        self.assertIsInstance(f.volume, Unavailable)

    def test_oi_age_when_oi_unchanged_for_minutes(self):
        ev = [plan("09:00:00", **FUT_PLAN, g=(FUT2, "full", "A", "FUT", "X")),
              tick(FUT, "09:14:50", 1000, 100, 500), tick(FUT, "09:15:10", 1001, 101, 600)]
        ev += [tick(FUT, f"09:{m}:{s:02d}", 1002 + m, 102 + m * 10 + s, 600)
               for m in range(15, 22) for s in (20, 40) if (m, s) != (15, 20)]
        ev.append(tick(FUT, "09:21:59", 1100, 999, 600))              # fresh price at the close: not STALE
        ev += [tick(FUT2, "09:15:05", 2000, 10, 700)] + [tick(FUT2, f"09:{m}:30", 2000 + m, 20 + m, 700) for m in range(15, 22)]
        ev.append(tick(FUT2, "09:21:58", 2100, 99, 700))
        out = run(ev, "09:22:16")
        c = candles(out, FUT, "1m")[at("09:21:00")]
        self.assertEqual((c.oi_at_close, c.oi_last_change_ns, c.oi_age_seconds), (600, at("09:15:10"), 410.0))
        self.assertEqual(c.quality.oi_age, 410.0)
        self.assertEqual(c.quality.status, "DEGRADED")                # older than stale_oi_s=300: not fresh
        self.assertEqual(candles(out, FUT, "1m")[at("09:15:00")].oi_age_seconds, 50.0)
        b = candles(out, FUT2, "1m")[at("09:21:00")]                  # only ever one value: change time unknown
        self.assertEqual((b.oi_at_close, b.oi_last_change_ns, b.oi_age_seconds), (700, None, None))
        self.assertIn("OI_CHANGE_TIME_UNKNOWN", b.quality.warnings)
        self.assertEqual(b.quality.status, "DEGRADED")
        comb = [x for x in out if isinstance(x, CombinedOI) and x.interval == "1m" and x.end_ns == at("09:22:00")][0]
        self.assertEqual((comb.oi, comb.quality.oi_age, comb.quality.status), (1300, None, "DEGRADED"))

    def test_oi_age_by_packet_counts_reconfirmations_and_still_goes_stale_without_packets(self):   # D-67
        ev = [plan("09:00:00", **FUT_PLAN, g=(FUT2, "full", "A", "FUT", "X")),
              tick(FUT, "09:14:50", 1000, 100, 500), tick(FUT, "09:15:10", 1001, 101, 600)]
        ev += [tick(FUT, f"09:{m}:{s:02d}", 1002 + m, 102 + m * 10 + s, 600)
               for m in range(15, 22) for s in (20, 40) if (m, s) != (15, 20)]
        ev.append(tick(FUT, "09:21:59", 1100, 999, 600))
        ev += [tick(FUT2, "09:15:05", 2000, 10, 700)] + [tick(FUT2, f"09:{m}:30", 2000 + m, 20 + m, 700) for m in range(15, 22)]
        ev.append(tick(FUT2, "09:21:58", 2100, 99, 700))
        out = run(ev, "09:28:16", **{"quality.oi_age_basis": "packet"})
        c = candles(out, FUT, "1m")[at("09:21:00")]
        self.assertEqual((c.oi_at_close, c.oi_last_change_ns, c.oi_age_seconds), (600, at("09:15:10"), 1.0))  # change time kept
        self.assertEqual(c.quality.status, "OK")                      # same value re-confirmed 1 s before the close
        b = candles(out, FUT2, "1m")[at("09:21:00")]
        self.assertEqual((b.oi_at_close, b.oi_last_change_ns, b.oi_age_seconds), (700, None, 2.0))
        self.assertIn("OI_CHANGE_TIME_UNKNOWN", b.quality.warnings)   # still said: the change time is not known
        comb = {x.end_ns: x for x in out if isinstance(x, CombinedOI) and x.interval == "1m"}
        self.assertEqual((comb[at("09:22:00")].oi, comb[at("09:22:00")].quality.oi_age, comb[at("09:22:00")].quality.status),
                         (1300, 2.0, "OK"))
        self.assertEqual(comb[at("09:28:00")].quality.status, "DEGRADED")   # no OI packet for 361 s: stale, nothing invented

    def test_disconnect_goes_stale_within_threshold_and_ok_only_on_fresh_data(self):
        eq = dict(e=(EQ, "quote", "A", "EQ", "E"))
        ev = [plan("09:00:00", **eq)]
        ev += [tick(EQ, None, 500 + s, 1000 + s, rns=f"09:15:{s:02d}", mode="quote") for s in range(0, 21)]
        agg = Aggregator(make_config(Path("/tmp")), DAY)
        out = []
        for e in ev + [conn("close", "09:15:20.5")]:
            out += agg.on_event(e)
        out += agg.advance(at("09:15:45"))
        changes = [x for x in out if isinstance(x, QualityChange)]
        self.assertEqual([(c.at_ns, c.quality.status) for c in changes], [(at("09:15:00"), "OK"), (at("09:15:30"), "STALE")])
        agg.on_event(conn("connect", "09:15:50"))
        self.assertEqual([x for x in agg.advance(at("09:15:55")) if isinstance(x, QualityChange)], [])  # still STALE
        back = agg.on_event(tick(EQ, None, 530, 1030, rns="09:15:56", mode="quote"))
        self.assertEqual([(c.at_ns, c.quality.status) for c in back if isinstance(c, QualityChange)], [(at("09:15:56"), "OK")])

    def test_rollover_combined_oi_is_continuous(self):
        p = plan("09:00:00", a=(FUT, "full", "A", "FUT", "NIFTY"), b=(FUT2, "full", "A", "FUT", "NIFTY"),
                 c=(FUT3, "full", "A", "FUT", "NIFTY"))
        ev = [p] + [tick(t, "09:14:55", 1000, 1, oi) for t, oi in ((FUT, 5000), (FUT2, 1000), (FUT3, 50))]
        ev.append(tick(FUT3, "09:15:05", 1000, 2, 51))
        for i, m in enumerate(range(15, 25)):
            ev += [tick(FUT, f"09:{m}:30", 1000 + i, 10 + i, 4900 - 100 * i, seq=1),
                   tick(FUT2, f"09:{m}:30", 1000 + i, 10 + i, 1100 + 100 * i, seq=2)]
        out = run(ev, "09:25:16")
        comb = sorted((x for x in out if isinstance(x, CombinedOI) and x.interval == "1m"), key=lambda x: x.end_ns)
        vals = [x.oi for x in comb]
        near = [dict((t, oi) for t, oi, _ in x.components)[FUT] for x in comb]
        self.assertEqual(set(vals), {6051})                           # 4900-100i + 1100+100i + 51
        self.assertEqual({a - b for a, b in zip(near, near[1:])}, {100})
        last = comb[-1]
        self.assertEqual(last.quality.oi_age, dict((t, a) for t, _, a in last.components)[FUT3])  # max component age
        self.assertEqual(last.quality.oi_age, 595.0)
        self.assertEqual(last.quality.status, "DEGRADED")             # the far month is older than 300 s

    def test_out_of_order_late_duplicate_and_backwards(self):
        ev = [plan("09:00:00", **FUT_PLAN), tick(FUT, "09:14:59", 1000, 100, 1),
              tick(FUT, "09:15:30", 1030, 110, 1, rns="09:15:30.2"),
              tick(FUT, "09:15:20", 1020, 105, 1, rns="09:15:31"),          # out of order, inside the window
              tick(FUT, "09:15:20", 1020, 105, 1, rns="09:15:31.5", conn=1),  # exact duplicate via another connection
              tick(FUT, "09:15:50", 1050, 120, 1, rns="09:16:02"),          # late: received at minute end + 2 s
              tick(FUT, "09:16:10", 1060, 125, 1), tick(FUT, "09:16:20", 1061, 90, 1),   # volume goes backwards
              tick(FUT, "09:17:10", 1070, 95, 1)]
        out = run(ev, "09:18:16")
        m = candles(out, FUT, "1m")
        c = m[at("09:15:00")]
        self.assertEqual((c.open, c.close, c.volume, c.trades, c.ticks, c.duplicate_ticks), (1020, 1030, 10, 2, 2, 1))
        late = [x for x in out if isinstance(x, LateTick)]
        self.assertEqual([(x.token, x.bucket_ns, x.late_by_s) for x in late], [(FUT, at("09:15:00"), 2.0)])
        b = m[at("09:16:00")]
        self.assertIsInstance(b.volume, Unavailable)
        self.assertIn("VOLUME_BACKWARDS", b.quality.warnings)
        self.assertEqual(b.completeness, "COMPLETE")
        self.assertEqual(m[at("09:17:00")].volume, 5)                 # baseline restarted from the lower value

    def test_session_edges_holiday_and_non_trading_instrument(self):
        p = plan("09:00:00", **FUT_PLAN, q=(FUT2, "full", "A", "FUT", "X"))
        ev = [p, tick(FUT, "15:38:59", 1000, 100, 1), tick(FUT, "15:39:10", 1001, 110, 1),
              tick(FUT, "15:41:00", 1002, 120, 1)]                    # post-close
        out = run(ev, "15:45:00")
        m = candles(out, FUT, "1m")
        self.assertEqual(max(m), at("15:39:00"))
        day = candles(out, FUT, "day")[O]
        self.assertEqual((day.end_ns, day.volume, day.open, day.close), (_ns(DAY, "15:40"), 110, 1001, 1001))
        self.assertEqual(sorted(candles(out, FUT, "15m"))[-1], at("15:30:00"))      # last bucket cut at 15:40
        self.assertEqual(candles(out, FUT, "15m")[at("15:30:00")].end_ns, _ns(DAY, "15:40"))
        idle = candles(out, FUT2, "1m")[at("15:39:00")]                # subscribed, never traded
        self.assertEqual((idle.completeness, idle.quality.status), ("EMPTY", "UNAVAILABLE"))
        hol = run(ev, "15:45:00", trading_day=False)
        self.assertEqual([x for x in hol if isinstance(x, (Candle, CombinedOI))], [])

    def test_depth_snapshots_for_tier_b_only(self):
        ev = [plan("09:00:00", **FUT_PLAN, b=(FUT2, "full", "AB", "FUT", "X")),
              depth(FUT, "09:15:01"), depth(FUT2, "09:15:01"), depth(FUT2, "09:15:02", bid=(0, 0, 0))]
        snaps = [x for x in run(ev, "09:15:03") if isinstance(x, DepthSnapshot)]
        self.assertEqual([s.token for s in snaps], [FUT2, FUT2])
        self.assertEqual((snaps[0].best_bid, snaps[0].best_ask, snaps[0].spread, snaps[0].mid),
                         (100000, 100050, 50, Decimal("100025")))
        self.assertEqual(snaps[0].bids[0], (10, 100000, 1))
        self.assertIsInstance(snaps[1].spread, Unavailable)

    def test_window_must_exceed_flush_interval(self):
        with self.assertRaises(ValueError):
            Aggregator(make_config(Path("/tmp"), **{"candles.out_of_order_window_s": 1.0}), DAY)


if __name__ == "__main__":
    unittest.main()
