import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from supertrend_research import trades_for  # noqa: E402

from engine.candles import IST  # noqa: E402


def day(closes, d=13):
    t0, out, prev = datetime(2026, 11, d, 9, 15, tzinfo=IST), [], closes[0]
    for i, c in enumerate(closes):
        out.append((t0 + timedelta(minutes=5 * i), prev, max(prev, c) + 1, min(prev, c) - 1, c, 100))
        prev = c
    return out


class Trades(unittest.TestCase):
    def test_flip_is_held_until_the_opposite_flip_and_labelled(self):
        # day 1 sets a down trend; day 2 rises (UP flip), then collapses (DOWN flip)
        cs = day([300 - i for i in range(75)], 12) + day([226 + 3 * i for i in range(30)] + [300 - 6 * i for i in range(20)])
        rows = trades_for("ABC", cs, {}, {}, lot=100, cost=300)
        up = next(r for r in rows if r["side"] == "UP" and r["day"] == "2026-11-13")
        self.assertEqual(up["why"], "OPPOSITE_FLIP")
        self.assertAlmostEqual(up["net"], 0.5 * up["move_pct"] / 100 * next(c[4] for c in cs if c[0] == up["t"]) * 100 - 300)
        self.assertIn(up["agree15"], ("agree", "conflict"))
        self.assertEqual((up["nifty"], up["oi"]), (None, None))          # no NIFTY / OI data given
        down = next(r for r in rows if r["side"] == "DOWN" and r["t"] > up["t"])
        self.assertIn(down["why"], ("OPPOSITE_FLIP", "TIME_15:10"))
        self.assertEqual(down["dayside"], "already moving that way" if down["move_pct"] is not None and
                         next(c[4] for c in cs if c[0] == down["t"]) < 225 else "against the day")


class OptionsTest(unittest.TestCase):
    def test_one_strike_itm_of_the_nearest_expiry(self):
        from datetime import date
        from supertrend_options_test import pick_itm
        chain = [(date(2026, 11, 24), k, t, 1, 50) for k in (90.0, 95.0, 100.0, 105.0) for t in ("CE", "PE")] + \
                [(date(2026, 12, 29), 100.0, "CE", 2, 50)]
        self.assertEqual(pick_itm(chain, "CE", 101.0, date(2026, 11, 2))[1], 95.0)   # ATM 100 -> one below
        self.assertEqual(pick_itm(chain, "PE", 101.0, date(2026, 11, 2))[1], 105.0)  # ATM 100 -> one above
        self.assertIsNone(pick_itm(chain, "PE", 104.0, date(2026, 11, 2)))           # no strike above 105

    def test_line_stop_comes_first_and_intraday_cuts_at_1515(self):
        from supertrend_options_test import exits
        from dashboard.supertrend import supertrend
        cs5 = day([300 - i for i in range(75)], 12) + day([226 + 3 * i for i in range(30)] + [316 - 6 * i for i in range(20)])
        st = supertrend(cs5)
        k = next(i for i in range(76, len(cs5)) if st[i][0] == 1 and st[i - 1][0] == -1)
        entry = cs5[k][0] + timedelta(minutes=5)
        m1 = [(c[0] + timedelta(minutes=j), c[4], c[2], c[3], c[4]) for c in cs5 for j in range(5)]   # crude 1-minute path
        ex = exits(1, entry, st, cs5, m1, overnight=False)
        self.assertEqual(ex["LINE"][1], "LINE_STOP")
        self.assertLessEqual(ex["LINE"][0], ex["CLOSE"][0])                          # touching comes no later than closing
        flat = day([300 - i for i in range(75)], 12) + day([226 + 3 * i for i in range(30)] + [316] * 45)
        stf = supertrend(flat)
        kf = next(i for i in range(76, len(flat)) if stf[i][0] == 1 and stf[i - 1][0] == -1)
        m1f = [(c[0] + timedelta(minutes=j), c[4], c[2], c[3], c[4]) for c in flat for j in range(5)]
        exf = exits(1, flat[kf][0] + timedelta(minutes=5), stf, flat, m1f, overnight=False)
        self.assertEqual({w for _, w in exf.values()}, {"TIME_15:15"})
        self.assertEqual(exits(1, flat[kf][0] + timedelta(minutes=5), stf, flat, m1f, overnight=True)["CLOSE"], (None, "OPEN"))


class OwnerRules(unittest.TestCase):
    def setUp(self):
        from dashboard.supertrend import supertrend
        from supertrend_research import to15
        self.supertrend, self.to15 = supertrend, to15

    def parts(self, cs5):
        st = self.supertrend(cs5)
        c15 = self.to15(cs5)
        m1 = [(c[0] + timedelta(minutes=j), c[4], c[2], c[3], c[4]) for c in cs5 for j in range(5)]
        return st, [c[0] + timedelta(minutes=5) for c in cs5], self.supertrend(c15), [c[0] + timedelta(minutes=15) for c in c15], m1

    def test_held_overnight_while_both_agree_then_sold_when_it_flips_next_day(self):
        from supertrend_options_test import exit_depends
        up = [100 + 0.4 * i for i in range(75)]
        cs5 = day([175 - i for i in range(75)], 10) + day(up, 11) + day([130 + 0.4 * i for i in range(20)] + [138 - 3 * i for i in range(20)], 12)
        st, e5, s15, e15, m1 = self.parts(cs5)
        k = next(i for i in range(75, len(cs5)) if st[i][0] == 1 and st[i - 1][0] == -1)
        t, why = exit_depends(1, cs5[k][0] + timedelta(minutes=5), st, e5, s15, e15, m1)
        self.assertEqual((why, t.date().day), ("LINE_STOP", 12))      # held through the 11th's 15:15, stopped on the 12th

    def test_sold_at_1515_when_15m_does_not_agree(self):
        from supertrend_options_test import _trend_at, exit_depends
        cs5 = day([175 - i for i in range(75)], 10) + day([100 - 0.3 * i for i in range(63)] + [81.1 + 1.0 * i for i in range(12)], 11)
        st, e5, s15, e15, m1 = self.parts(cs5)
        k = next(i for i in range(75, len(cs5)) if st[i][0] == 1 and st[i - 1][0] == -1)   # the late 5m flip UP
        chk = datetime(2026, 11, 11, 15, 15, tzinfo=IST)
        self.assertEqual((_trend_at(st, e5, chk), _trend_at(s15, e15, chk)), (1, -1))    # 5m UP, 15m still DOWN
        t, why = exit_depends(1, cs5[k][0] + timedelta(minutes=5), st, e5, s15, e15, m1)
        self.assertEqual((t, why), (chk, "15:15 (5m/15m not both agreeing)"))

    def test_account_limits_and_volume_order(self):
        from supertrend_options_test import account
        t0 = datetime(2026, 11, 2, 10, 0, tzinfo=IST)
        mk = lambda s, mins, rvol, prem=20_000, net=-100, out=60: {   # noqa: E731
            "sym": s, "t": t0 + timedelta(minutes=mins), "rvol": rvol, "premium": prem,
            "x": {"out_t": t0 + timedelta(minutes=mins + out), "why": "LINE_STOP", "net": net, "nights": 0}}
        cands = [mk("A", 0, 1.0), mk("B", 0, 3.0), mk("C", 0, 2.0), mk("D", 0, 0.5), mk("E", 0, 0.1), mk("F", 5, 1, prem=60_000),
                 mk("B", 10, 1), mk("G", 70, 1), mk("H", 75, 1), mk("I", 80, 1)]
        taken, skipped = account(cands, "x")
        self.assertEqual([o["sym"] for o in taken], ["B", "C", "A", "D", "G"])   # volume order; 4 open; then the 5th trade
        self.assertEqual(skipped, {"4 positions already open": 1, "premium above ₹50,000 for 1 lot": 1, "already holding this stock": 1,
                                   "5 trades already today": 2})
        cash = [mk("A", 0, 2, prem=30_000, net=5_000, out=5), mk("B", 0, 1, prem=30_000), mk("C", 10, 1, prem=30_000),
                mk("D", 12, 1, prem=30_000)]
        taken, skipped = account(cash, "x", capital=50_000)
        self.assertEqual([o["sym"] for o in taken], ["A", "C"])     # B: 20k left; C: A closed +5k -> 55k free; D: 25k left
        self.assertEqual(skipped, {"not enough cash": 2})
        two_losses = [mk("A", 0, 1, out=5), mk("B", 6, 1, out=5), mk("C", 20, 1), mk("D", 24 * 60, 1)]
        taken, skipped = account(two_losses, "x", rules={"cooldown": 2})
        self.assertEqual([o["sym"] for o in taken], ["A", "B", "D"])    # C waits for the next day
        self.assertEqual(skipped, {"2 losses in a row today": 1})
        big_loss = [mk("A", 0, 1, net=-31_000, out=5), mk("B", 10, 1)]
        self.assertEqual(account(big_loss, "x")[1], {"daily loss stop (−₹30,000) hit": 1})


if __name__ == "__main__":
    unittest.main()
