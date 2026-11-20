"""Stage 2 auto exits: which orders are sent, in what order, and when nothing may be sent. Kite is simulated."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import supertrend_auto as A  # noqa: E402
from dashboard import supertrend_trades as T  # noqa: E402

IST = A.IST
NOW = datetime(2026, 11, 16, 11, 0, tzinfo=IST)
OPT = "PNB26NOV124CE"


def pos(action, why="the 5-minute Supertrend turned DOWN", qty=500, ltp=4.0, trig=2.7, option=OPT):
    return {"option": option, "qty": qty, "ltp": ltp, "action": action, "why": why,
            "backstop": [{"price": 2.55, "trigger_price": trig}]}


def buy(tag="STREND", option=OPT):
    return {"order_id": "B1", "tradingsymbol": option, "transaction_type": "BUY", "status": "COMPLETE", "tag": tag,
            "order_type": "LIMIT", "order_timestamp": "2026-11-16 09:56:00"}


def sl(status="TRIGGER PENDING"):
    return {"order_id": "S1", "tradingsymbol": OPT, "transaction_type": "SELL", "status": status, "order_type": "SL",
            "price": 2.55, "order_timestamp": "2026-11-16 09:57:00"}


def gtt(qty=500, gid=77, option=OPT, status="active"):
    return {"id": gid, "status": status, "type": "single",
            "condition": {"exchange": "NFO", "tradingsymbol": option, "trigger_values": [2.7]},
            "orders": [{"transaction_type": "SELL", "quantity": qty, "order_type": "LIMIT", "product": "NRML", "price": 2.55}]}


def selling(at="2026-11-16 11:00:00", price=3.9):
    return {"order_id": "X1", "tradingsymbol": OPT, "transaction_type": "SELL", "status": "OPEN", "order_type": "LIMIT",
            "price": price, "tag": "STRENDX", "order_timestamp": at}


class Auto(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(A, "SWITCH", d / "sw.json"), mock.patch.object(A, "REG", d / "reg.json"),
                  mock.patch.object(A, "LOG", d / "log.jsonl"), mock.patch.object(A, "DATA", d),
                  mock.patch.object(A, "ENTRY_SWITCH", d / "en.json"), mock.patch.object(A, "BOUGHT", d / "buys.json"),
                  mock.patch.object(A, "STRATEGY", d / "strategy.json"),
                  mock.patch.object(A, "_ORPHANS_SAID", set())]
        for x in self.p:
            x.start()
        self.calls, self.alerts, self.fail = [], [], set()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def send(self, method, path, data=None):
        self.calls.append((method, path, data))
        if method in self.fail:
            raise RuntimeError(f"{method} refused")
        return {"order_id": "N1", "trigger_id": 88}

    def run_min(self, positions, orders, now=NOW, b=3.9, account=True, gtts=(), net=None):
        v = {"positions": positions, "errors": [], **({"account": {}} if account else {})}
        net = [{"tradingsymbol": p["option"], "quantity": p["qty"]} for p in positions] if net is None else net
        book = {"/orders": orders, "/gtt/triggers": list(gtts), "/portfolio/positions": {"net": net}}

        def get(path, *a):
            if isinstance(book[path], Exception):
                raise book[path]
            return book[path]
        if net == "error":
            book["/portfolio/positions"] = RuntimeError("Kite down")
        with mock.patch.object(T, "_get", side_effect=get):
            return A.step(now, v=v, notify=lambda t, *a, **k: self.alerts.append(t), send=self.send, bid=lambda s: b)

    def test_switched_off_sends_nothing_and_logs_once(self):
        out = self.run_min([pos("SELL")], [buy(), sl()], gtts=[gtt()])
        self.assertEqual(self.calls, [])
        self.assertEqual(out["actions"][0]["action"], "WOULD SELL")
        self.assertEqual((out["actions"][0]["cancel"], out["actions"][0]["delete_gtt"]), (["S1"], [77]))
        self.assertEqual(self.run_min([pos("SELL")], [buy(), sl()], NOW + timedelta(minutes=1))["actions"], [])
        self.assertEqual(self.alerts, [])

    def test_sell_removes_every_stop_first_then_sells_all_at_the_bid(self):
        A.set_armed(True)
        self.run_min([pos("SELL")], [buy(), sl()], gtts=[gtt(), gtt(gid=78, status="triggered"), gtt(gid=79, option="X")],
                     net=[{"tradingsymbol": OPT, "quantity": 500}, {"tradingsymbol": "X", "quantity": 75}])   # X held: kept
        self.assertEqual(self.calls[0], ("DELETE", "/gtt/triggers/77", None))      # only the active GTT on this option
        self.assertEqual(self.calls[1], ("DELETE", "/orders/regular/S1", None))
        self.assertEqual(self.calls[2], ("POST", "/orders/regular", {
            "tradingsymbol": OPT, "exchange": "NFO", "transaction_type": "SELL", "order_type": "LIMIT", "quantity": 500,
            "product": "NRML", "price": 3.9, "validity": "DAY", "tag": "STRENDX"}))
        self.assertEqual(self.alerts, [f"AUTO SELL: {OPT}"])

    def test_never_a_second_sell_while_one_is_live_and_reprice_then_give_up(self):
        A.set_armed(True)
        live = [buy(), selling()]
        self.run_min([pos("SELL")], live, NOW + timedelta(seconds=30), b=3.8)
        self.assertEqual(self.calls, [])                                            # too fresh to touch
        self.run_min([pos("SELL")], live, NOW + timedelta(seconds=61), b=3.8)
        self.assertEqual(self.calls, [("PUT", "/orders/regular/X1", {"price": 3.8})])
        for k in (2, 3):
            self.run_min([pos("SELL")], live, NOW + timedelta(seconds=61 * k), b=3.8 - k / 10)
        self.run_min([pos("SELL")], live, NOW + timedelta(minutes=10), b=3.0)
        self.run_min([pos("SELL")], live, NOW + timedelta(minutes=11), b=3.0)
        self.assertEqual([c[0] for c in self.calls], ["PUT"] * 3)                   # max 3 re-prices, never a POST
        self.assertEqual(self.alerts.count(f"AUTO ALERT: {OPT}"), 1)

    def test_stop_loss_not_cancelled_means_no_sell_and_a_wait(self):
        A.set_armed(True)
        self.fail = {"DELETE"}
        self.run_min([pos("SELL")], [buy(), sl()])
        self.assertEqual([c[0] for c in self.calls], ["DELETE"])                    # no POST after a failed cancel
        self.fail = set()
        self.run_min([pos("SELL")], [buy(), sl()], NOW + timedelta(minutes=1))
        self.assertEqual(len(self.calls), 1)                                         # waits 3 minutes
        self.run_min([pos("SELL")], [buy(), sl()], NOW + timedelta(minutes=4))
        self.assertEqual([c[0] for c in self.calls], ["DELETE", "DELETE", "POST"])

    def test_failed_sell_is_not_resent_for_3_minutes(self):
        A.set_armed(True)
        self.fail = {"POST"}
        self.run_min([pos("SELL")], [buy()])
        self.run_min([pos("SELL")], [buy()], NOW + timedelta(minutes=2))
        self.assertEqual(len(self.calls), 1)
        self.assertIn(f"AUTO SELL FAILED: {OPT}", self.alerts)

    def test_positions_not_bought_through_the_ticket_are_never_touched(self):
        A.set_armed(True)
        self.run_min([pos("SELL")], [buy(tag="MANUAL")])
        self.run_min([pos("SELL")], [])
        self.assertEqual(self.calls, [])

    def test_hold_gets_one_gtt_stop_that_lives_to_expiry_and_follows_the_quantity(self):
        A.set_armed(True)
        self.run_min([pos("HOLD")], [buy()])
        method, path, data = self.calls[0]
        self.assertEqual((method, path, data["type"]), ("POST", "/gtt/triggers", "single"))
        self.assertEqual(json.loads(data["condition"]), {"exchange": "NFO", "tradingsymbol": OPT, "trigger_values": [2.7],
                                                         "last_price": 4.0})
        self.assertEqual(json.loads(data["orders"]), [{"exchange": "NFO", "tradingsymbol": OPT, "transaction_type": "SELL",
                                                       "quantity": 500, "order_type": "LIMIT", "product": "NRML",
                                                       "price": 2.55}])
        self.run_min([pos("HOLD")], [buy()], NOW + timedelta(minutes=1), gtts=[gtt()])
        self.run_min([pos("HOLD")], [buy(), sl()], NOW + timedelta(minutes=2))       # a stop order sits there instead
        self.assertEqual(len(self.calls), 1)
        self.run_min([pos("HOLD", qty=1000)], [buy()], NOW + timedelta(minutes=3), gtts=[gtt()])   # lots added by hand
        self.assertEqual((self.calls[1][0], self.calls[1][1]), ("PUT", "/gtt/triggers/77"))
        self.assertEqual(json.loads(self.calls[1][2]["orders"])[0]["quantity"], 1000)
        self.calls.clear()
        self.run_min([pos("HOLD", ltp=2.6)], [buy()], NOW + timedelta(minutes=2))    # trigger 2.7 >= price 2.6
        self.assertEqual(self.calls, [])

    def test_press_sell_alert_is_silenced_only_for_positions_auto_exits_is_selling(self):
        v = {"positions": [{**pos("SELL"), "qty": 500, "sl_in_zerodha": False},
                           {**pos("SELL", option="ITC26NOV280CE"), "sl_in_zerodha": False}], "errors": []}
        A.REG.write_text(json.dumps({OPT: {}}))
        alerted = Path(tempfile.mkdtemp()) / "alerted.json"
        for armed, expect in ((False, 2), (True, 1)):
            A.set_armed(armed)
            alerted.unlink(missing_ok=True)
            with mock.patch.object(T, "_ALERTED", alerted):
                self.assertEqual(T.check_positions(send=lambda *a, **k: None, now=NOW, v=v)["alerts"], expect)

    def test_gtt_trigger_trails_up_in_2_percent_steps_and_never_down(self):
        A.set_armed(True)
        def held(trig, ltp=6.0):
            return [{**pos("HOLD", ltp=ltp), "backstop": [{"price": round(trig * 0.95, 2), "trigger_price": trig}]}]
        self.run_min(held(2.75), [buy()], gtts=[gtt()])                               # 2.70 -> 2.75 is under 2 %
        self.run_min(held(2.5), [buy()], gtts=[gtt()])                                # lower: never
        self.run_min(held(6.1, ltp=6.0), [buy()], gtts=[gtt()])                       # would fire at once: never
        self.assertEqual(self.calls, [])
        self.run_min(held(4.5), [buy()], gtts=[gtt()])
        method, path, data = self.calls[0]
        self.assertEqual((method, path, json.loads(data["condition"])["trigger_values"]), ("PUT", "/gtt/triggers/77", [4.5]))
        self.assertEqual(json.loads(data["orders"])[0]["price"], round(4.5 * 0.95, 2))   # the backstop limit, as given
        self.assertEqual(self.alerts, [f"AUTO STOP-LOSS RAISED: {OPT}"])

    def test_a_handed_over_position_is_managed_like_a_ticket_buy(self):
        with self.assertRaises(ValueError):
            A.manage(OPT, True, held=set())                                          # not held: refused
        A.manage(OPT, True, held={OPT})
        A.set_armed(True)
        self.run_min([pos("SELL")], [buy(tag="MANUAL")])                             # bought by hand
        self.assertEqual([c[0] for c in self.calls], ["POST"])
        A.manage(OPT, False, held={OPT})
        self.calls.clear()
        self.run_min([pos("SELL")], [buy(tag="MANUAL")], NOW + timedelta(minutes=5))
        self.assertEqual(self.calls, [])                                             # taken back: untouched

    def test_your_two_leg_gtt_is_never_modified_but_is_removed_before_a_sell(self):
        A.manage(OPT, True, held={OPT})
        A.set_armed(True)
        oco = {**gtt(), "type": "two-leg", "condition": {"tradingsymbol": OPT, "trigger_values": [2.7, 8.0]},
               "orders": [{"transaction_type": "SELL", "quantity": 500, "price": 2.7},
                          {"transaction_type": "SELL", "quantity": 500, "price": 7.9}]}
        hold = [{**pos("HOLD", ltp=6.0), "backstop": [{"price": 4.28, "trigger_price": 4.5}]}]
        out = self.run_min(hold, [], gtts=[oco])
        self.assertEqual((self.calls, out["actions"][0]["action"]), ([], "KEEPING YOUR GTT"))
        self.run_min(hold, [], NOW + timedelta(minutes=1), gtts=[oco])
        self.assertEqual(len(self.alerts), 1)                                        # said once, not every minute
        self.run_min([pos("SELL")], [], NOW + timedelta(minutes=2), gtts=[oco])
        self.assertEqual([c[:2] for c in self.calls], [("DELETE", "/gtt/triggers/77"), ("POST", "/orders/regular")])

    def test_leftover_stop_on_an_option_no_longer_held_is_deleted_once(self):
        A.set_armed(True)
        held_idx = gtt(gid=1, option="NIFTY26NOV24000CE")                            # held index option: keep
        oco = {**gtt(gid=2, option="SBIN26NOV900CE"), "type": "two-leg"}             # your two-leg GTT: keep
        cash = {**gtt(gid=3, option="SBIN"), "condition": {"exchange": "NSE", "tradingsymbol": "SBIN"}}  # not NFO: keep
        net = [{"tradingsymbol": "NIFTY26NOV24000CE", "quantity": 65}, {"tradingsymbol": OPT, "quantity": 0}]
        out = self.run_min([], [], gtts=[gtt(gid=9), held_idx, oco, cash], net=net)
        self.assertEqual(self.calls, [("DELETE", "/gtt/triggers/9", None)])
        self.assertEqual(out["actions"][0]["action"], "LEFTOVER STOP DELETED")
        self.assertEqual(len(self.alerts), 1)

    def test_leftover_stop_not_deleted_alerts_once_and_unreadable_positions_touch_nothing(self):
        A.set_armed(True)
        self.fail.add("DELETE")
        for m in range(3):
            self.run_min([], [], NOW + timedelta(minutes=m), gtts=[gtt(gid=9)])
        self.assertEqual((len(self.calls), self.alerts), (3, ["AUTO LEFTOVER STOP DELETE FAILED: " + OPT]))
        self.calls.clear()
        out = self.run_min([], [], gtts=[gtt(gid=10)], net="error")
        self.assertEqual(self.calls, [])
        self.assertIn("leftover stops not checked", out["errors"][0])

    def test_leftover_stop_switched_off_is_only_logged_once(self):
        for m in range(2):
            out = self.run_min([], [], NOW + timedelta(minutes=m), gtts=[gtt(gid=9)])
        self.assertEqual((self.calls, out["actions"]), ([], []))
        self.assertIn("WOULD DELETE LEFTOVER STOP", A.LOG.read_text())

    def test_blank_account_view_changes_nothing_and_overnight_positions_stay_managed(self):
        A.set_armed(True)
        self.run_min([pos("HOLD")], [buy(), sl()])
        self.run_min([], [], NOW + timedelta(minutes=1), account=False)              # Kite unreadable
        self.assertIn(OPT, json.loads(A.REG.read_text()))
        self.run_min([pos("SELL")], [], NOW + timedelta(days=1))                     # next day: no BUY in today's book
        self.assertEqual(self.calls[-1][0], "POST")
        self.run_min([], [], NOW + timedelta(days=1, minutes=5))                     # sold: forgotten
        self.assertEqual(json.loads(A.REG.read_text()), {})


def take(sym="PNB", at="10:55", option=OPT, verdict="TAKE"):
    return {"symbol": sym, "trend": "UP", "signal_at": at, "option": option, "lot": 8000, "lots": 3, "ask": 4.1,
            "verdict": verdict}


class Entries(Auto):
    def run_buy(self, signals, orders=(), now=NOW, errors=()):
        v = {"signals": signals, "positions": [], "errors": list(errors), "account": {}}
        with mock.patch.object(T, "_get", side_effect=lambda path, *a: list(orders)):
            return A.enter(now, v=v, notify=lambda t, *a, **k: self.alerts.append(t), send=self.send)

    def test_off_or_exits_off_only_logs_would_buy_once(self):
        A.set_entries(True)                      # auto exits still off: an entry would have no stop
        out = self.run_buy([take(), take("SBIN", option="SBIN26NOV800CE", verdict="SKIP")])
        self.assertEqual((self.calls, [a["action"] for a in out["actions"]]), ([], ["WOULD BUY"]))
        self.assertEqual(self.run_buy([take()], now=NOW + timedelta(minutes=1))["actions"], [])

    def test_buys_one_lot_at_the_ask_once_per_signal_with_the_strend_tag(self):
        A.set_armed(True), A.set_entries(True)
        self.run_buy([take()])
        (m, path, d), = self.calls
        self.assertEqual((m, path, d["quantity"], d["price"], d["tag"], d["order_type"]), ("POST", "/orders/regular", 8000, 4.1, "STREND", "LIMIT"))
        self.run_buy([take()], now=NOW + timedelta(minutes=1))
        self.assertEqual(len(self.calls), 1)

    def test_never_buys_an_option_already_ordered_today_or_on_a_read_error(self):
        A.set_armed(True), A.set_entries(True)
        self.run_buy([take()], orders=[buy(tag="")])
        self.run_buy([take()], errors=["GTTs not readable"])
        self.assertEqual(self.calls, [])

    def test_one_pending_buy_at_a_time_and_cancel_after_5_minutes(self):
        A.set_armed(True), A.set_entries(True)
        self.run_buy([take(), take("SBIN", option="SBIN26NOV800CE")])
        self.assertEqual(len(self.calls), 1)
        live = {"order_id": "N1", "tradingsymbol": OPT, "transaction_type": "BUY", "status": "OPEN", "price": 4.1,
                "order_timestamp": "2026-11-16 11:00:00"}
        self.run_buy([take("SBIN", option="SBIN26NOV800CE")], orders=[live], now=NOW + timedelta(minutes=2))
        self.assertEqual(len(self.calls), 1)     # still waiting on the first buy
        self.run_buy([], orders=[live], now=NOW + timedelta(minutes=5))
        self.assertEqual(self.calls[-1][:2], ("DELETE", "/orders/regular/N1"))
        self.run_buy([], orders=[live], now=NOW + timedelta(minutes=6))
        self.assertEqual(len(self.calls), 2)     # cancel sent once only

    def test_failed_buy_switches_entries_off_and_alerts(self):
        A.set_armed(True), A.set_entries(True)
        self.fail.add("POST")
        self.run_buy([take()])
        self.assertFalse(A.entries_armed())
        self.assertTrue(any("FAILED" in a for a in self.alerts))
        self.run_buy([take("SBIN", option="SBIN26NOV800CE")], now=NOW + timedelta(minutes=1))
        self.assertEqual(len(self.calls), 1)

    def test_physical_delivery_refusal_stops_stock_buys_today_not_index_buys_and_keeps_entries_on(self):
        A.set_armed(True), A.set_entries(True)
        refused = RuntimeError("Fresh buy orders are not allowed for OTM stock options due to compulsory physical delivery.")
        self.send = lambda m, p, d=None: (self.calls.append((m, p, d)), (_ for _ in ()).throw(refused)) if m == "POST" and \
            d["tradingsymbol"] == OPT else (self.calls.append((m, p, d)) or {"order_id": "N2"})
        out = self.run_buy([take()])
        self.assertTrue(A.entries_armed())                                    # not a fault: entries stay on
        self.assertEqual(out["actions"][0]["action"], "BUY REFUSED")
        self.run_buy([take("SBIN", option="SBIN26NOV800CE")], now=NOW + timedelta(minutes=1))
        self.assertEqual(len(self.calls), 1)                                  # stock: skipped for the day
        self.run_buy([take("NIFTY", option="NIFTY26NOV25550CE")], now=NOW + timedelta(minutes=2))
        self.assertEqual(self.calls[-1][2]["tradingsymbol"], "NIFTY26NOV25550CE")   # index: still bought

    def test_press_buy_alert_is_silenced_when_auto_entries_buys(self):
        A.set_armed(True), A.set_entries(True)
        self.assertEqual(T.check_entries(send=lambda *a, **k: self.alerts.append(a), now=NOW, v={"signals": [take()]})["alerts"], 0)


if __name__ == "__main__":
    unittest.main()
