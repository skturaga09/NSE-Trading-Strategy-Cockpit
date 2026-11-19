"""One-click Kite order tickets for the Supertrend rules: entries, exits, limits. Every Kite call is mocked (reads only)."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import supertrend_trades as T  # noqa: E402

IST = T.IST
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=IST)


def nfo(name, kind, strikes, lot=500, tick=0.05, expiry="2026-11-24"):
    return [{"tradingsymbol": f"{name}26NOV{k:g}{kind}", "name": name, "instrument_type": kind, "strike": str(k),
             "expiry": expiry, "lot_size": str(lot), "tick_size": str(tick)} for k in strikes]


MASTER = nfo("PNB", "CE", [122, 124, 126, 128]) + nfo("PNB", "PE", [122, 124, 126, 128]) + \
    nfo("PNB", "CE", [126], expiry="2026-12-29") + nfo("ABB", "CE", [6800, 6900, 7000], lot=125) + \
    nfo("TCS", "PE", [2400, 2450, 2500], lot=175)


def full_quote(ltp, ask=None, bid=None, qty=1_000_000):
    """A /quote entry: by default the ask is the last price and the bid 1 % under it, with plenty offered."""
    ask = ltp if ask is None else ask
    bid = round(ask * 0.99, 2) if bid is None else bid
    return {"last_price": ltp, "depth": {"sell": [{"price": ask, "quantity": qty, "orders": 1}],
                                         "buy": [{"price": bid, "quantity": qty, "orders": 1}]}}


def quote_get(q, depth, data=None):
    """Mocked Kite GETs: /quote/ltp and /quote from last prices `q`, depth overrides `depth`, account paths from `data`."""
    def get(path, params=None):
        if path == "/quote/ltp":
            return {s: {"last_price": q[s]} for _, s in params if s in q}
        if path == "/quote":
            return {s: depth.get(s) or full_quote(q[s]) for _, s in params if s in q or s in depth}
        return data[path]
    return get


def row(sym, trend, since, line, t15=None, close=100.0):
    return {"symbol": sym, "trend": trend, "since": since, "line": line, "trend_15m": t15 or trend, "close": close}


class Pieces(unittest.TestCase):
    def test_tick_rounding(self):
        self.assertEqual((T._tick(3.6, 0.05, True), T._tick(3.6, 0.05, False)), (3.6, 3.6))
        self.assertEqual((T._tick(3.61, 0.05, True), T._tick(3.61, 0.05, False)), (3.65, 3.6))

    def test_one_strike_otm_current_month(self):
        self.assertEqual(T.pick_option(MASTER, "PNB", "CE", 126.3, "2026-11-16")["tradingsymbol"], "PNB26NOV128CE")
        self.assertEqual(T.pick_option(MASTER, "PNB", "PE", 126.3, "2026-11-16")["tradingsymbol"], "PNB26NOV124PE")
        self.assertIsNone(T.pick_option(MASTER, "PNB", "PE", 122.0, "2026-11-16"))   # no strike below 122

    def test_delta_from_the_option_price(self):
        ce = {"strike": "124", "instrument_type": "CE", "expiry": "2026-11-24"}
        d = T.option_delta(126.3, ce, 3.6, NOW)                          # 1 strike ITM, 8 days left
        self.assertTrue(0.5 < d < 1.0, d)
        self.assertLess(T.option_delta(126.3, {**ce, "strike": "128"}, 1.2, NOW), 0.5)   # OTM: under 0.5
        self.assertIsNone(T.option_delta(126.3, ce, 1.0, NOW))           # price under intrinsic: no delta
        self.assertIsNone(T.option_delta(None, ce, 3.6, NOW))

    def test_exit_rules(self):
        up = row("PNB", "UP", "2026-11-16T09:15:00+05:30", 124.1)
        self.assertEqual(T.exit_decision("CE", 125.0, up, "2026-11-24", NOW)["action"], "HOLD")
        self.assertIn("crossed the Supertrend line ₹124.10", T.exit_decision("CE", 124.05, up, "2026-11-24", NOW)["why"])
        self.assertEqual(T.exit_decision("CE", 130, row("PNB", "DOWN", None, 131), "2026-11-24", NOW)["action"], "SELL")
        at1516 = NOW.replace(hour=15, minute=16)
        self.assertEqual(T.exit_decision("CE", 125, row("PNB", "UP", None, 124, t15="DOWN"), "2026-11-24", at1516)["action"], "SELL")
        self.assertEqual(T.exit_decision("CE", 125, up, "2026-11-24", at1516)["action"], "HOLD")    # both agree: hold overnight
        self.assertEqual(T.exit_decision("CE", 125, up, "2026-11-16", NOW.replace(hour=15, minute=1))["action"], "SELL")
        self.assertEqual(T.exit_decision("PE", 125, None, "2026-11-24", NOW)["action"], "UNKNOWN")


class View(unittest.TestCase):
    def setUp(self):
        self.peaks = Path(tempfile.mkdtemp()) / "peaks.json"            # the real account's highs, kept between calls
        for name in ("SWITCH", "ENTRY_SWITCH"):                          # never the live auto switches
            p = mock.patch(f"dashboard.supertrend_auto.{name}", self.peaks.parent / f"{name}.json")
            p.start()
            self.addCleanup(p.stop)

    def run_view(self, rows, positions=(), orders=(), cash=50_000, quotes=None, depth=None, gtts=(), blocked=0, **kw):
        data = {"/user/margins": {"equity": {"available": {"live_balance": cash}, "utilised": {"delivery": blocked}}},
                "/portfolio/positions": {"net": list(positions)}, "/orders": list(orders), "/gtt/triggers": list(gtts)}
        get = quote_get(quotes or {}, depth or {}, data)
        with mock.patch.object(T, "_get", side_effect=get), mock.patch.object(T, "board", return_value={"rows": rows, "bar": "x"}), \
                mock.patch("dashboard.option_chain._instruments", return_value=MASTER), \
                mock.patch("dashboard.option_chain.ensure_fresh_config"), \
                mock.patch("dashboard.app.KITE_CONFIG", {"api_key": "k"}), \
                mock.patch.object(T, "_DAY", Path(tempfile.mkdtemp()) / "day.json"), \
                mock.patch.object(T, "_PEAKS", self.peaks), \
                mock.patch("dashboard.supertrend_auto.REG", self.peaks.parent / "reg.json"):
            return T.view(NOW, **kw)

    def test_fresh_signal_gets_a_buy_ticket_and_limits_decide(self):
        rows = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3),       # closed 09:55: fresh
                row("ABB", "UP", "2026-11-16T09:15:00+05:30", 6850, close=6910),          # closed 09:20: missed
                row("TCS", "DOWN", "2026-11-16T09:45:00+05:30", 2470, close=2455)]        # fresh, but cash
        v = self.run_view(rows, quotes={"NFO:PNB26NOV128CE": 3.6, "NFO:ABB26NOV7000CE": 280, "NFO:TCS26NOV2400PE": 300})
        s = {x["symbol"]: x for x in v["signals"]}
        self.assertEqual(s["PNB"]["verdict"], "TAKE")
        self.assertEqual(s["PNB"]["orders"], [{"variety": "regular", "exchange": "NFO", "tradingsymbol": "PNB26NOV128CE",
                                               "transaction_type": "BUY", "quantity": 4500, "order_type": "LIMIT", "price": 3.6,
                                               "product": "NRML", "readonly": False, "tag": "STREND"}])
        self.assertEqual(s["PNB"]["lots"], 9)     # cash fits 27 lots of ₹1,800; the ₹5,000 day budget fits 9 (₹540 risk each)
        self.assertTrue(s["ABB"]["why"].startswith("missed"))
        self.assertTrue(s["TCS"]["why"].startswith("not enough cash"))                  # 52,500 premium > 50,000 - 1,800
        self.assertEqual(v["api_key"], "k")
        # phone: only the TAKE signal is alerted, once; the SKIPs (missed, no cash) stay on the dashboard
        with tempfile.TemporaryDirectory() as td, mock.patch.object(T, "_ALERTED", Path(td) / "a.json"):
            sent = []
            send = lambda title, body, **k: sent.append((title, body))   # noqa: E731
            self.assertEqual(T.check_entries(send, NOW, v), {"take": 1, "alerts": 1})
            self.assertEqual(T.check_entries(send, NOW, v), {"take": 1, "alerts": 0})   # not again next minute
            self.assertEqual(T.check_positions(send, NOW, v)["alerts"], 0)                # shares the file, keeps the key
            self.assertEqual(T.check_entries(send, NOW, v)["alerts"], 0)
        self.assertEqual(sent[0][0], "Supertrend BUY: PNB26NOV128CE")
        self.assertIn("Buy 9 lots = 4500 qty, LIMIT ₹3.60", sent[0][1])
        self.assertIn("sell if PNB trades below ₹124.10", sent[0][1])
        self.assertIn("before 10:10", sent[0][1])                       # signal closed 09:55 + 15 minutes

    def test_lots_fit_the_day_loss_budget_which_grows_with_the_balance(self):
        rows = [row("TCS", "DOWN", "2026-11-16T09:45:00+05:30", 2470, close=2455)]
        q = {"NFO:TCS26NOV2400PE": 100}                                  # 175 qty -> ₹17,500 a lot, ₹5,250 at risk
        s = self.run_view(rows, cash=50_000, quotes=q)["signals"][0]     # budget 10 % of ₹50,000 = ₹5,000
        self.assertEqual(s["why"], "day loss limit: ₹5,000 of budget left, 1 lot can lose ₹5,250")
        self.assertEqual(self.run_view(rows, cash=60_000, quotes=q)["signals"][0]["lots"], 1)     # ₹6,000 budget
        self.assertEqual(self.run_view(rows, cash=120_000, quotes=q)["signals"][0]["lots"], 2)    # ₹12,000 budget
        held = [{"exchange": "NFO", "tradingsymbol": "PNB26NOV124CE", "quantity": 500, "average_price": 20.0, "pnl": 0}]
        v = self.run_view(rows, positions=held, cash=50_000, quotes=q)   # ₹10,000 paid counts, and its ₹3,000 risk too
        self.assertEqual((v["account"]["balance"], v["account"]["budget"]), (60_000, 3_000))
        self.assertEqual(v["signals"][0]["verdict"], "SKIP")

    def test_delivery_margin_counts_in_the_balance_but_cannot_be_spent(self):
        rows = [row("TCS", "DOWN", "2026-11-16T09:45:00+05:30", 2470, close=2455)]
        q = {"NFO:TCS26NOV2400PE": 100}                                  # ₹17,500 a lot
        v = self.run_view(rows, cash=10_000, blocked=50_000, quotes=q)   # 17-Nov RELIANCE case: Zerodha held cash back
        self.assertEqual((v["account"]["blocked"], v["account"]["balance"]), (50_000, 60_000))
        self.assertTrue(v["signals"][0]["why"].startswith("not enough cash"))   # blocked money is not free to buy with

    def test_twenty_filled_orders_a_day_buys_and_sells_cancelled_not_counted(self):
        rows = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        q = {"NFO:PNB26NOV128CE": 3.6}
        o = lambda side, st="COMPLETE": {"exchange": "NFO", "transaction_type": side, "status": st}   # noqa: E731
        nine_trips = [o("BUY"), o("SELL")] * 9
        junk = [o("BUY", "CANCELLED"), o("BUY", "REJECTED"), {**o("BUY"), "exchange": "MCX"}] * 5
        v = self.run_view(rows, orders=nine_trips + junk, quotes=q)          # 18 done: this buy + its sell make 20
        self.assertEqual((v["account"]["orders_today"], v["signals"][0]["verdict"]), (18, "TAKE"))
        s = self.run_view(rows, orders=nine_trips + [o("BUY")], quotes=q)["signals"][0]      # 19 done: no room for both
        self.assertEqual(s["why"], "20 orders a day: 19 done, 0 sells kept for open positions")
        held = [{"exchange": "NFO", "tradingsymbol": "TCS26NOV2400PE", "quantity": 175, "average_price": 50.0}]
        s = self.run_view(rows, positions=held, orders=nine_trips, quotes=q)["signals"][0]   # 18 + 1 sell due on TCS
        self.assertEqual(s["why"], "20 orders a day: 18 done, 1 sells kept for open positions")

    def test_strong_min_skips_weak_flips_before_they_take_a_slot(self):
        weak = {**row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3), "since_strength": 1.2}   # newer
        strong = {**row("TCS", "DOWN", "2026-11-16T09:45:00+05:30", 2470, close=2455), "since_strength": 2.4}
        held = [{"exchange": "NFO", "tradingsymbol": f"ABB26NOV{k}CE", "quantity": 125, "average_price": 10.0}
                for k in (6800, 6900, 7000)]                                                 # 3 of 4 slots used
        q = {"NFO:PNB26NOV128CE": 3.6, "NFO:TCS26NOV2400PE": 100, "NFO:ABB26NOV6800CE": 10, "NFO:ABB26NOV6900CE": 10,
             "NFO:ABB26NOV7000CE": 10, "NSE:ABB": 6900}
        by = lambda v: {s["symbol"]: (s["verdict"], s["why"]) for s in v["signals"]}   # noqa: E731
        plain = by(self.run_view([weak, strong], positions=held, quotes=q, cash=500_000))
        self.assertEqual((plain["PNB"][0], plain["TCS"][1]), ("TAKE", "4 positions already open"))   # newest takes the slot
        v = by(self.run_view([weak, strong], positions=held, quotes=q, cash=500_000, strong_min=1.9))
        self.assertEqual(v["PNB"], ("SKIP", "weak flip candle: 1.20x a normal candle, under 1.9x"))
        self.assertEqual(v["TCS"][0], "TAKE")                                              # the slot goes to the strong flip

    def test_buy_is_priced_at_the_ask_and_thin_or_wide_books_are_skipped(self):
        rows = [row("PNB", "UP", "2026-11-16T09:50:00+05:30", 124.1, close=126.3)]
        k = "NFO:PNB26NOV128CE"
        s = self.run_view(rows, depth={k: full_quote(3.0, ask=3.6, bid=3.55)})["signals"][0]   # stale last trade ₹3.00
        self.assertEqual((s["verdict"], s["orders"][0]["price"], s["ask"]), ("TAKE", 3.6, 3.6))
        one = lambda **kw: self.run_view(rows, depth={k: full_quote(3.6, **kw)})["signals"][0]   # noqa: E731
        self.assertEqual(one(ask=0)["why"], "no seller in the market for this option")
        self.assertEqual(one(ask=3.6, bid=3.4)["why"], "bid-ask gap 5.6% is wider than 3%")
        self.assertEqual(one(ask=3.6, bid=0)["why"], "bid-ask gap 100.0% is wider than 3%")              # no buyer
        self.assertEqual(one(qty=400)["why"], "only 400 qty offered at the ask, less than 1 lot (500)")
        self.assertEqual(one(qty=1_500)["lots"], 3)          # 9 fit cash and budget; only 3 lots are offered at the ask

    def test_an_active_sell_gtt_counts_as_the_stop_in_zerodha(self):
        held = [{"exchange": "NFO", "tradingsymbol": "PNB26NOV124CE", "quantity": 500, "average_price": 3.6, "pnl": 0}]
        g = {"status": "active", "condition": {"tradingsymbol": "PNB26NOV124CE"}, "orders": [{"transaction_type": "SELL"}]}
        q = {"NFO:PNB26NOV124CE": 3.7, "NSE:PNB": 126.0}
        rows = [row("PNB", "UP", "2026-11-16T09:15:00+05:30", 124.1)]
        self.assertFalse(self.run_view(rows, positions=held, quotes=q)["positions"][0]["sl_in_zerodha"])
        self.assertTrue(self.run_view(rows, positions=held, quotes=q, gtts=[g])["positions"][0]["sl_in_zerodha"])
        self.assertFalse(self.run_view(rows, positions=held, quotes=q, gtts=[{**g, "status": "triggered"}])["positions"][0]["sl_in_zerodha"])

    def test_the_premium_stop_trails_25_percent_under_the_high_kept_between_readings(self):
        held = [{"exchange": "NFO", "tradingsymbol": "PNB26NOV124CE", "quantity": 500, "average_price": 3.6, "pnl": 0}]
        rows = [row("PNB", "UP", "2026-11-16T09:15:00+05:30", 124.1)]
        v = self.run_view(rows, positions=held, quotes={"NFO:PNB26NOV124CE": 6.0, "NSE:PNB": 130.0})
        self.assertEqual((v["positions"][0]["action"], v["positions"][0]["backstop"][0]["trigger_price"]), ("HOLD", 2.7))
        self.assertEqual(json.loads(self.peaks.read_text()), {"PNB26NOV124CE": 6.0})
        v = self.run_view(rows, positions=held, quotes={"NFO:PNB26NOV124CE": 4.6, "NSE:PNB": 128.0})
        self.assertEqual((v["positions"][0]["action"], v["positions"][0]["backstop"][0]["trigger_price"]), ("HOLD", 4.5))
        v = self.run_view(rows, positions=held, quotes={"NFO:PNB26NOV124CE": 4.5, "NSE:PNB": 127.5})
        self.assertEqual(v["positions"][0]["action"], "SELL")
        self.assertIn("25 % below its high ₹6.00 since your buy (trailing stop)", v["positions"][0]["why"])
        self.run_view(rows, positions=[], quotes={})                      # sold: its high is forgotten
        self.assertEqual(json.loads(self.peaks.read_text()), {})

    def test_positions_show_whether_auto_exits_manages_them(self):
        held = [{"exchange": "NFO", "tradingsymbol": "PNB26NOV124CE", "quantity": 500, "average_price": 3.6, "pnl": 0}]
        q, rows = {"NFO:PNB26NOV124CE": 3.7, "NSE:PNB": 126.0}, [row("PNB", "UP", "2026-11-16T09:15:00+05:30", 124.1)]
        self.assertFalse(self.run_view(rows, positions=held, quotes=q)["positions"][0]["managed"])
        (self.peaks.parent / "reg.json").write_text(json.dumps({"PNB26NOV124CE": {"adopted": True}}))
        self.assertTrue(self.run_view(rows, positions=held, quotes=q)["positions"][0]["managed"])

    def test_premium_stop_sells_25_percent_below_the_buy(self):
        up = row("PNB", "UP", "2026-11-16T09:15:00+05:30", 124.1)
        self.assertIn("premium stop", T.exit_decision("CE", 125.0, up, "2026-11-24", NOW, 2.7, 3.6)["why"])
        self.assertEqual(T.exit_decision("CE", 125.0, up, "2026-11-24", NOW, 2.8, 3.6)["action"], "HOLD")
        self.assertEqual(T.exit_decision("CE", 125.0, None, "2026-11-24", NOW, 2.7, 3.6)["action"], "SELL")   # even unread

    def test_held_option_gets_sell_and_backstop_tickets_never_a_buy_side_stop(self):
        rows = [row("PNB", "UP", "2026-11-16T09:15:00+05:30", 124.1)]
        pos = [{"exchange": "NFO", "tradingsymbol": "PNB26NOV124CE", "quantity": 500, "average_price": 3.6, "pnl": 250}]
        v = self.run_view(rows, positions=pos, quotes={"NFO:PNB26NOV124CE": 4.1, "NSE:PNB": 124.0})
        p = v["positions"][0]
        self.assertEqual((p["action"], p["sl_in_zerodha"]), ("SELL", False))
        self.assertEqual((p["sell"][0]["transaction_type"], p["sell"][0]["quantity"], p["sell"][0]["price"]), ("SELL", 500, 4.1))
        self.assertEqual((p["backstop"][0]["order_type"], p["backstop"][0]["trigger_price"], p["backstop"][0]["price"]), ("SL", 2.7, 2.55))
        self.assertTrue(all(x.get("orders") is None for x in v["signals"]))           # already holding PNB: no new buy
        with tempfile.TemporaryDirectory() as td, mock.patch.object(T, "_ALERTED", Path(td) / "a.json"), \
                mock.patch.object(T, "view", return_value=v):
            sent = []
            send = lambda *a, **k: sent.append(a[0])   # noqa: E731
            self.assertEqual(T.check_positions(send, NOW)["alerts"], 1)
            self.assertEqual(T.check_positions(send, NOW)["alerts"], 0)                # once per reason per day
            self.assertEqual(sent, ["Supertrend EXIT: sell PNB26NOV124CE"])


if __name__ == "__main__":
    unittest.main()
