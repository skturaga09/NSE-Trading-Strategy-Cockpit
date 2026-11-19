#!/usr/bin/env python3
"""MCX commodity desk: calculations, signal framework, exits, risk controls, and isolation from the stock desk.
Fixture-driven, no network: every Kite call goes through an injected fake."""

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard import mcx_desk as D
from dashboard import supertrend_paper, supertrend_trades
from dashboard.supertrend import IST


def candles(closes, start=datetime(2026, 11, 12, 9, 0, tzinfo=IST)):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        t = start + timedelta(minutes=5 * i)
        out.append([t.isoformat(), prev, max(prev, c) + 0.5, min(prev, c) - 0.5, c, 100])
        prev = c
    return out


UP = [100 + i for i in range(120)]


def at(cs, k=-1):
    return datetime.fromisoformat(cs[k][0])


class Isolated(unittest.TestCase):
    """Every test writes into a temp MCX namespace and a temp stock paper file."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        d = self.tmp / "mcx_desk"
        self.stock = self.tmp / "supertrend_paper.json"
        self.patches = [mock.patch.object(D, "DATA", d), mock.patch.object(D, "SETTINGS", d / "settings.json"),
                        mock.patch.object(D, "BOOK", d / "paper.json"), mock.patch.object(D, "STATE", d / "state.json"),
                        mock.patch.object(D, "ALERTS", d / "alerts.jsonl"),
                        mock.patch.object(D, "HOLIDAYS", self.tmp / "holidays.json"),
                        mock.patch.object(supertrend_paper, "STATE", self.stock)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()


# ----------------------------------------------------------------------------- calculations
class Calculations(unittest.TestCase):
    def test_charges_match_the_schedule_by_hand(self):
        # buy ₹10,000 / sell ₹12,000: brokerage 40, MCX 9.196, SEBI 0.022, CTT 6, stamp 0.3, GST 18% of 49.218
        self.assertAlmostEqual(D.charges(10000, 12000), 64.38, places=2)

    def test_pnl_uses_the_contract_multiplier_not_the_kite_lot_size(self):
        # GOLD option quoted per 10 g, 1 kg lot -> 100 units: ₹100 premium move on 1 lot = ₹10,000 gross
        s = D.DEFAULTS
        pos = {"entry": 2000.0, "units": 1 * D.MULTIPLIER["GOLD"], "option_type": "CE", "future": "GOLD26DECFUT"}
        g = D.guide(pos, {"bid": 2100.0, "ltp": 2101.0}, None, datetime(2026, 11, 13, 12, 0, tzinfo=IST),
                    {"minutes_to_close": 300}, s)
        self.assertEqual(g["est_pnl"], round(10000 - D.charges(200000, 210000), 2))
        self.assertEqual(D.MULTIPLIER, {"GOLD": 100, "SILVER": 30, "CRUDEOIL": 100, "NATURALGAS": 1250})

    def test_paper_marks_at_the_bid_not_the_last_price(self):
        pos = {"entry": 10.0, "units": 1250, "option_type": "PE", "future": "NG"}
        g = D.guide(pos, {"bid": 9.0, "ltp": 11.0}, None, datetime(2026, 11, 13, 12, 0, tzinfo=IST),
                    {"minutes_to_close": 300}, D.DEFAULTS)
        self.assertEqual(g["premium"], 9.0)
        self.assertLess(g["est_pnl"], 0)

    def test_one_strike_in_the_money(self):
        exp = date(2026, 11, 27)
        rows = [{"name": "GOLD", "segment": "MCX-OPT", "expiry": exp, "instrument_type": t, "strike": k,
                 "tradingsymbol": f"GOLD{k}{t}", "token": k, "lot_size": 1, "tick_size": 0.5}
                for k in (135000, 136000, 137000) for t in ("CE", "PE")]
        self.assertEqual(D.pick_option("GOLD", "UP", 136390, exp, rows)["strike"], 136000)
        self.assertEqual(D.pick_option("GOLD", "DOWN", 136390, exp, rows)["strike"], 137000)
        self.assertIsNone(D.pick_option("GOLD", "UP", 134000, exp, rows))      # nothing in the money: no pick

    def test_nearest_option_expiry_respects_min_dte(self):
        rows = [{"name": "CRUDEOIL", "segment": "MCX-OPT", "expiry": e, "instrument_type": "CE", "strike": 1}
                for e in (date(2026, 11, 17), date(2026, 12, 16))]
        self.assertEqual(D.option_expiry("CRUDEOIL", rows, date(2026, 11, 13), 5), date(2026, 12, 16))

    def test_account_funds_is_one_pool_never_summed(self):
        # the real shape on an MCX-enabled account: commodity block says disabled / ₹0, profile lists MCX
        f = D.account_funds({"equity": {"enabled": True, "net": 8233.4}, "commodity": {"enabled": False, "net": 0}},
                            ["BSE", "NFO", "MCX", "NSE"])
        self.assertEqual(f["available"], 8233.4)
        self.assertTrue(f["commodity_enabled"])
        self.assertFalse(D.account_funds({}, ["NSE", "NFO"])["commodity_enabled"])
        self.assertIsNone(D.account_funds({}, None)["commodity_enabled"])           # profile unreadable: unknown
        f = D.account_funds({"equity": {"enabled": True, "net": 50000}, "commodity": {"enabled": True, "net": 50000}})
        self.assertEqual(f["available"], 50000)                                   # unified ledger: not 1,00,000
        self.assertIsNone(D.account_funds(None)["available"])


class Sessions(Isolated):
    def test_close_follows_us_daylight_saving(self):
        self.assertTrue(D.us_dst(date(2026, 3, 8)) and not D.us_dst(date(2026, 3, 7)))
        self.assertTrue(D.us_dst(date(2026, 10, 31)) and not D.us_dst(date(2026, 11, 1)))
        self.assertEqual(D.session(datetime(2026, 7, 15, 23, 40, tzinfo=IST))["state"], "CLOSED")    # 23:30 close
        s = D.session(datetime(2026, 11, 13, 23, 40, tzinfo=IST))                                       # 23:55 close
        self.assertEqual((s["state"], s["minutes_to_close"]), ("OPEN", 15))
        self.assertEqual(D.session(datetime(2026, 11, 14, 12, 0, tzinfo=IST))["state"], "WEEKEND")
        self.assertEqual(D.session(datetime(2026, 11, 13, 8, 59, tzinfo=IST))["state"], "CLOSED")

    def test_half_day_holiday(self):
        D.HOLIDAYS.write_text(json.dumps({"verified": True, "holidays": [
            {"date": "2026-11-24", "morning": "closed", "evening": "open"}]}))
        self.assertEqual(D.session(datetime(2026, 11, 24, 10, 0, tzinfo=IST))["state"], "HOLIDAY")
        self.assertTrue(D.session(datetime(2026, 11, 24, 18, 0, tzinfo=IST))["is_open"])


# ----------------------------------------------------------------------------- signal framework
class Signals(unittest.TestCase):
    def test_aligned_up_and_down(self):
        cs = candles(UP)
        self.assertEqual(D.signal_at(cs, at(cs), 10, 3)["signal"], "UP")
        cs = candles([300 - i for i in range(120)])
        self.assertEqual(D.signal_at(cs, at(cs), 10, 3)["signal"], "DOWN")

    def test_conflict_is_wait_until_the_15_minute_candle_completes(self):
        cs = candles(UP + [UP[-1] - 6, UP[-1] - 12, UP[-1] - 18])
        s1 = D.signal_at(cs, at(cs, -2), 10, 3)       # 19:05: 5m DOWN, 15m candle 19:00 not complete -> still UP
        self.assertEqual((s1["dir5"], s1["dir15"], s1["signal"]), (-1, 1, "WAIT"))
        s2 = D.signal_at(cs, at(cs, -1), 10, 3)       # 19:10 closes the 19:00 15m candle -> DOWN aligned
        self.assertEqual(s2["signal"], "DOWN")

    def test_ignores_candles_after_the_closed_bar(self):
        cs = candles(UP + [UP[-1] - 6, UP[-1] - 12])
        self.assertEqual(D.signal_at(cs, at(cs, -3), 10, 3)["signal"], "UP")

    def test_settings_change_the_indicator(self):
        cs = candles(UP + [UP[-1] - 6, UP[-1] - 12])
        self.assertNotEqual(D.signal_at(cs, at(cs), 10, 3)["line5"], D.signal_at(cs, at(cs), 7, 2)["line5"])


# ----------------------------------------------------------------------------- exits
class Exits(unittest.TestCase):
    NOW = datetime(2026, 11, 13, 12, 0, tzinfo=IST)
    POS = {"entry": 100.0, "units": 100, "option_type": "CE", "future": "F", "policy": "INTRADAY", "exit_by": "2026-11-25"}

    def g(self, bid, sig=None, sess=None, pos=None, **kw):
        return D.guide({**self.POS, **(pos or {})}, {"bid": bid, "ltp": bid}, sig, self.NOW,
                       sess or {"minutes_to_close": 300}, D.DEFAULTS, **kw)

    def test_hold(self):
        self.assertEqual(self.g(105, {"dir5": 1, "line5": 99, "dir15": 1, "line15": 98})["action"], "HOLD")

    def test_premium_stop(self):
        r = self.g(69)
        self.assertEqual((r["action"], r["reason"], r["stop_premium"]), ("EXIT", "premium stop hit", 70.0))

    def test_trail_arms_then_exits_on_giveback(self):
        r = self.g(125)
        self.assertEqual((r["action"], r["stop_premium"]), ("TRAIL", 106.25))
        r = self.g(106, pos={"peak": 125})
        self.assertEqual((r["action"], r["reason"]), ("EXIT", "trailing premium stop hit"))

    def test_five_minute_flip_exits_but_fifteen_minute_book_holds(self):
        sig = {"dir5": -1, "line5": 101, "dir15": 1, "line15": 95}
        self.assertEqual(self.g(105, sig)["action"], "EXIT")
        self.assertEqual(self.g(105, sig, tf="15m")["action"], "HOLD")

    def test_intraday_policy_squares_off_before_close_overnight_does_not(self):
        sess = {"minutes_to_close": 10}
        self.assertEqual(self.g(105, sess=sess)["action"], "EXIT")
        self.assertEqual(self.g(105, sess=sess, pos={"policy": "OVERNIGHT"})["action"], "HOLD")

    def test_expiry_cutoff_applies_to_every_policy(self):
        r = self.g(105, pos={"policy": "OVERNIGHT", "exit_by": "2026-11-13"})
        self.assertIn("devolvement", r["reason"])

    def test_daily_loss_lock(self):
        self.assertEqual(self.g(105, day_locked=True)["reason"], "daily loss limit reached")


# ----------------------------------------------------------------------------- the minute loop, end to end
NOW = datetime(2026, 11, 13, 19, 6, 5, tzinfo=IST)       # bar 19:00 just closed
BAR = datetime(2026, 11, 13, 19, 0, tzinfo=IST)
OPT_EXP, FUT_EXP = date(2026, 11, 27), date(2026, 12, 4)
ROWS = [{"token": 1, "tradingsymbol": "GOLD26DECFUT", "name": "GOLD", "segment": "MCX-FUT", "exchange": "MCX",
         "instrument_type": "FUT", "strike": None, "expiry": FUT_EXP, "lot_size": 1, "tick_size": 1.0}] + \
       [{"token": 10 + i, "tradingsymbol": f"GOLD26NOV{k}{t}", "name": "GOLD", "segment": "MCX-OPT", "exchange": "MCX",
         "instrument_type": t, "strike": k, "expiry": OPT_EXP, "lot_size": 1, "tick_size": 0.5}
        for i, (k, t) in enumerate((k, t) for k in (135000, 136000, 137000) for t in ("CE", "PE"))]


def quote(bid, ask, qty=5):
    return {"last_price": (bid + ask) / 2, "depth": {"buy": [{"price": bid, "quantity": qty}],
                                                    "sell": [{"price": ask, "quantity": qty}]}}


class Loop(Isolated):
    def setUp(self):
        super().setUp()
        D.save_settings({"roots": ["GOLD"], "capital": 500000, "max_premium_per_trade": 300000})   # 1 GOLD lot ≈ ₹2 L

    def test_per_trade_cap_blocks(self):
        D.save_settings({"max_premium_per_trade": 50000})
        self.assertTrue(any("per-trade cap" in b for b in self.run_tick()["blocked"]["GOLD"]))

    def test_default_budget_fits_one_gold_lot(self):
        D.save_settings({"capital": D.DEFAULTS["capital"], "max_premium_per_trade": D.DEFAULTS["max_premium_per_trade"]})
        self.assertEqual(self.run_tick()["bought"], ["GOLD26NOV136000CE"])

    def io(self, net=1_000_000.0, positions=(), quotes=None):
        self.sent = []
        q = {"MCX:GOLD26DECFUT": {"last_price": 136400}, "MCX:GOLD26NOV136000CE": quote(1990, 2000)}
        q.update(quotes or {})
        return {"rows": lambda: ROWS, "connected": lambda: True,
                "candles": lambda tok, now: [[BAR.isoformat(), 1, 1, 1, 136400, 1]],
                "quote": lambda syms: {k: v for k, v in q.items() if k.split(":")[1] in syms},
                "margins": lambda: {"equity": {"enabled": True, "net": net}, "commodity": {"enabled": True, "net": net}},
                "exchanges": lambda: ["NSE", "NFO", "MCX"],
                "positions": lambda: list(positions),
                "notify": lambda t, b: self.sent.append(t)}

    def run_tick(self, prev="WAIT", cur="UP", **kw):
        def fake_signal(cs, closed_through, p, m):
            s = cur if closed_through == BAR else prev
            d5 = {"UP": 1, "DOWN": -1, "WAIT": -1}[s]
            d15 = {"UP": 1, "DOWN": -1, "WAIT": 1}[s]
            return {"dir5": d5, "line5": 136000, "dir15": d15, "line15": 135800, "close": 136400,
                    "bar": BAR.isoformat(), "signal": s}
        with mock.patch.object(D, "signal_at", fake_signal):
            return D.tick(NOW, self.io(**kw))

    def test_fresh_alignment_alerts_and_buys_on_paper_at_the_ask(self):
        r = self.run_tick()
        self.assertEqual(r["bought"], ["GOLD26NOV136000CE"])
        p = D.book()["open"][0]
        self.assertEqual((p["entry"], p["units"], p["desk"], p["exchange"], p["policy"]), (2000, 100, "MCX", "MCX", "INTRADAY"))
        self.assertEqual(p["exit_by"], "2026-11-25")
        kinds = [a["kind"] for a in D.alerts()]
        self.assertIn("ALIGNED", kinds)
        self.assertIn("ENTRY", kinds)
        self.assertTrue(all(t.startswith(("GOLD", "PAPER")) for t in self.sent))   # _notify adds the "MCX ·" prefix

    def test_same_bar_twice_does_not_buy_twice(self):
        self.run_tick()
        r = self.run_tick()
        self.assertEqual((r["bought"], len(D.book()["open"])), ([], 1))

    def test_conflict_alerts_and_never_buys(self):
        r = self.run_tick(prev="UP", cur="WAIT")
        self.assertEqual(r["bought"], [])
        self.assertEqual([a["kind"] for a in D.alerts()], ["CONFLICT"])

    def test_already_aligned_still_enters_when_nothing_is_held(self):
        # owner 2026-11-13: buy whenever both agree and nothing is held, not only when they start agreeing
        self.assertEqual(self.run_tick(prev="UP", cur="UP")["bought"], ["GOLD26NOV136000CE"])
        self.assertEqual([a["kind"] for a in D.alerts()], ["ENTRY"])          # no ALIGNED alert: state didn't change

    def test_holding_blocks_the_next_candle(self):
        self.run_tick(prev="UP", cur="UP")
        nxt = NOW + timedelta(minutes=5)
        sig = {"dir5": 1, "line5": 1, "dir15": 1, "line15": 1, "close": 136400, "signal": "UP"}
        io = self.io()
        io["candles"] = lambda tok, now: [[(BAR + timedelta(minutes=5)).isoformat(), 1, 1, 1, 136400, 1]]
        with mock.patch.object(D, "signal_at", lambda cs, ct, p, m: {**sig, "bar": ct.isoformat()}):
            r = D.tick(nxt, io)
        self.assertEqual(r["bought"], [])
        self.assertIn("already holding a GOLD position", r["blocked"]["GOLD"])

    def test_real_account_shortfall_is_flagged_on_the_paper_trade(self):
        r = self.run_tick(net=8233.4)                    # ₹2,00,000 premium vs ₹8,233 in the account
        self.assertEqual(r["bought"], ["GOLD26NOV136000CE"])          # owner 2026-11-13: paper is not blocked...
        self.assertIn("real account short", D.book()["open"][0]["real_funds"])   # ...but the trade says so

    def test_real_account_ok_is_recorded(self):
        self.run_tick(net=1_000_000.0)
        self.assertEqual(D.book()["open"][0]["real_funds"], "ok")

    def test_stock_paper_positions_use_up_the_same_account(self):
        self.stock.write_text(json.dumps({"open": [{"qty": 500, "entry": 1700.0}]}))     # ₹8,50,000 held by stocks
        self.run_tick(net=1_000_000.0)                                                   # leaves ₹1,50,000 < ₹2,00,000
        self.assertIn("stocks ₹850,000", D.book()["open"][0]["real_funds"])

    def test_unknown_real_funds_is_flagged(self):
        self.assertIn("unknown", D.account_shortfall(1.0, D.account_funds(None), 0.0, D.book()))

    def test_wide_spread_blocks_entry(self):
        r = self.run_tick(quotes={"MCX:GOLD26NOV136000CE": quote(1800, 2000)})
        self.assertTrue(any("spread" in b for b in r["blocked"]["GOLD"]))

    def test_daily_loss_limit_locks_and_exits(self):
        self.run_tick()
        crash = {"MCX:GOLD26NOV136000CE": quote(1940, 1950)}                 # -₹6,000 on 100 units > ₹5,000 limit
        with mock.patch.object(D, "signal_at", lambda *a: {"dir5": 1, "line5": 1, "dir15": 1, "line15": 1,
                                                          "close": 136400, "bar": BAR.isoformat(), "signal": "UP"}):
            r = D.tick(NOW + timedelta(minutes=1), self.io(quotes=crash))
        self.assertEqual(r["sold"], ["GOLD26NOV136000CE"])
        self.assertTrue(D.state()["day_locked"])
        self.assertEqual(D.book()["closed"][0]["exit_why"], "daily loss limit reached")
        self.assertEqual(D.book()["closed"][0]["exit"], 1940)                # sold at the bid

    def test_broker_positions_are_separate_and_never_traded(self):
        real = [{"exchange": "MCX", "tradingsymbol": "GOLD26NOV136000CE", "quantity": 1, "average_price": 1500.0,
                 "multiplier": 100, "pnl": 0, "product": "NRML"},
                {"exchange": "NFO", "tradingsymbol": "RELIANCE26NOV1400CE", "quantity": 500, "average_price": 20.0}]
        self.run_tick(prev="WAIT", cur="WAIT", positions=real)            # no paper entry this candle
        st = D.state()
        self.assertEqual([b["option"] for b in st["broker"]], ["GOLD26NOV136000CE"])   # the NFO stock row is ignored
        self.assertEqual(st["broker"][0]["source"], "BROKER")
        self.assertEqual(D.book()["open"], [])                                          # not copied into paper


# ----------------------------------------------------------------------------- isolation from the stock desk
class NoMixing(Isolated):
    def test_storage_namespaces_are_disjoint(self):
        from dashboard import supertrend
        mcx_files = {p.resolve() for p in (D.SETTINGS, D.BOOK, D.STATE, D.ALERTS)}
        stock_files = {p.resolve() for p in (self.stock, supertrend._STATE, supertrend_trades._DAY,
                                             supertrend_trades._PEAKS, supertrend_trades._ALERTED)}
        self.assertFalse(mcx_files & stock_files)
        self.assertTrue(all("mcx_desk" in str(p) for p in mcx_files))
        real = D.Path(D.__file__).resolve().parents[1] / "data" / "mcx_desk"           # the unpatched location
        self.assertNotIn(real, {p.parent for p in stock_files})

    def test_settings_only_touch_the_mcx_file_and_reject_stock_or_live(self):
        before = dict(supertrend_trades.LIMITS), supertrend_paper.MAX_LOTS
        D.save_settings({"max_open_positions": 1, "daily_loss_limit": 1000})
        self.assertEqual((dict(supertrend_trades.LIMITS), supertrend_paper.MAX_LOTS), before)
        self.assertEqual([p.name for p in D.DATA.iterdir()], ["settings.json"])
        self.assertFalse(self.stock.exists())
        for bad in ({"mode": "LIVE"}, {"roots": ["NIFTY"]}, {"roots": ["RELIANCE", "GOLD"]}, {"nonsense": 1}):
            with self.assertRaises(ValueError):
                D.save_settings(bad)

    def test_mcx_alerts_carry_the_desk_and_never_reach_stock_state(self):
        Loop.io(self)                                               # reuse the fake for its notify capture
        st = {}
        D._alert(st, "k", "ALIGNED", "GOLD UP", "body", lambda t, b: self.sent.append(t), True)
        D._alert(st, "k", "ALIGNED", "GOLD UP", "body", lambda t, b: self.sent.append(t), True)   # deduped
        self.assertEqual(self.sent, ["GOLD UP"])
        self.assertEqual([a["desk"] for a in D.alerts()], ["MCX"])
        self.assertFalse(self.stock.exists())
        with mock.patch("dashboard.exit_monitor.notify") as n:
            D._notify("GOLD UP", "x")
        self.assertTrue(n.call_args[0][0].startswith("MCX · "))

    def test_mcx_daily_lock_does_not_block_the_stock_desk(self):
        D._write(D.STATE, {"day": "2026-11-13", "day_locked": True})
        self.assertIsNone(supertrend_paper._day_blocked({"closed": []}, "2026-11-13"))

    def test_stock_ticket_logic_ignores_mcx_positions_and_orders(self):
        mcx_pos = {"exchange": "MCX", "tradingsymbol": "GOLD26NOV136000CE", "quantity": 1, "average_price": 2000.0}
        mcx_buy = {"exchange": "MCX", "transaction_type": "BUY", "status": "COMPLETE", "tradingsymbol": "GOLD26NOV136000CE"}
        fake_master = [{"tradingsymbol": "GOLD26NOV136000CE", "instrument_type": "CE", "name": "GOLD"}]
        with mock.patch.object(supertrend_trades, "board", lambda: {"rows": []}), \
                mock.patch("dashboard.option_chain._instruments", lambda: fake_master), \
                mock.patch("dashboard.option_chain.ensure_fresh_config", lambda: None):
            v = supertrend_trades.view(datetime(2026, 11, 13, 12, 0, tzinfo=IST),
                                       account=(100000.0, [mcx_pos], [mcx_buy], 100000.0))
        self.assertEqual((v["account"]["open"], v["account"]["orders_today"], v["positions"]), (0, 0, []))

    def test_mcx_book_rows_are_tagged_and_desk_ignores_non_mcx_positions(self):
        self.assertEqual(D.DESK, "MCX")
        rows = [{"exchange": "NFO", "tradingsymbol": "X", "quantity": 1}, {"exchange": "NSE", "tradingsymbol": "Y", "quantity": 1}]
        loop = Loop("test_conflict_alerts_and_never_buys")
        loop.tmp, loop.stock = self.tmp, self.stock
        with mock.patch.object(D, "signal_at", lambda *a: None):
            D.tick(NOW, loop.io(positions=rows))
        self.assertEqual(D.state()["broker"], [])


if __name__ == "__main__":
    unittest.main()
