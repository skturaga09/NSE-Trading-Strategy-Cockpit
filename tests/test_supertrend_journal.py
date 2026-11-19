import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import supertrend_journal as J  # noqa: E402

from engine.candles import IST  # noqa: E402

T0 = datetime(2026, 11, 2, 9, 20, tzinfo=IST)


def cand(sym, mins, net, prem=20_000, out_min=60, open_=False, key_nets=None):
    t = T0 + timedelta(minutes=mins)
    x = lambda n: {"out_t": None if open_ else t + timedelta(minutes=out_min), "why": "LINE_STOP", "net": n, "nights": 0, "mark": 1.0}  # noqa: E731
    return {"id": f"{t.isoformat()}|{sym}", "sym": sym, "t": t, "side": 1, "kind": "CE", "contract": f"{sym} 100 CE",
            "token": 1, "lot": 50, "expiry": "2026-11-24", "rvol": 1.0, "entry_t": t.isoformat(), "entry_px": prem / 50 / 1.01,
            "premium": prem, **{k: x((key_nets or {}).get(k, net)) for k in J.EXIT_KEYS}}


class Journal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = J.connect(Path(self.tmp.name) / "j.sqlite")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_saved_trades_survive_and_open_ones_stay_open(self):
        J.save(self.db, cand("A", 0, 500))
        J.save(self.db, cand("B", 5, 0, open_=True))
        self.assertEqual([r[0] for r in self.db.execute("SELECT final FROM cands ORDER BY id")], [1, 0])
        back = J.load(self.db)
        self.assertEqual((back[0]["sym"], back[0]["depends"]["net"], back[0]["t"]), ("A", 500, T0))

    def replay(self, *cands, versions=("MAIN",)):
        for c in cands:
            J.save(self.db, c)
        self.db.execute("INSERT OR REPLACE INTO days VALUES ('2026-11-02', '{}')")
        v = {x["id"]: x for x in J.replay(self.db)["versions"]}
        return [v[k] for k in versions] if len(versions) > 1 else v[versions[0]]

    def test_whole_balance_usable_and_profit_reused_without_day_limits(self):
        # 1L: A (90k premium) fits alone; B must wait; after A closes +10k, C (1.05L) fits in the 1.1L balance
        v = self.replay(cand("A", 0, 10_000, prem=90_000, out_min=30), cand("B", 5, 4_000, prem=20_000),
                        cand("C", 40, -1_000, prem=105_000), versions=("NO_DAY_LIMITS",))
        self.assertEqual(J.CAPITAL, 100_000)                                   # the paper account's start
        self.assertEqual([t["sym"] for t in v["trades"]], ["C", "A"])
        self.assertEqual((v["summary"]["balance"], v["summary"]["trades"]), (109_000, 2))
        self.assertEqual(v["skipped"], [{"reason": "not enough cash", "count": 1, "would_have_made": 4_000}])

    def test_main_uses_the_live_day_loss_budget_as_at_0921_on_16_nov(self):
        # the 09:20 signals the paper account saw, in its order; 10% of 1L = 10k, each lot counts 30% of its premium
        sigs = [("VEDL", 10_500), ("UNIONBANK", 26_506), ("TATASTEEL", 12_733), ("PIIND", 8_479), ("BANKBARODA", 16_965)]
        cs = []
        for i, (sym, prem) in enumerate(sigs):
            c = cand(sym, 0, 100, prem=prem)
            c["rvol"] = 10 - i
            cs.append(c)
        main = self.replay(*cs)
        self.assertEqual(sorted(t["sym"] for t in main["trades"]), ["PIIND", "TATASTEEL", "VEDL"])   # what paper bought
        self.assertEqual(main["skipped"], [{"reason": "day loss budget (10% of the balance) used up", "count": 2,
                                            "would_have_made": 200}])

    def test_closed_losses_shrink_the_budget(self):
        # A loses 9k -> 10k - 9k = 1k left; B's lot counts 6k -> skipped. Without day limits both trade.
        main, free = self.replay(cand("A", 0, -9_000, out_min=5), cand("B", 10, 1_000), versions=("MAIN", "NO_DAY_LIMITS"))
        self.assertEqual([s["reason"] for s in main["skipped"]], ["day loss budget (10% of the balance) used up"])
        self.assertEqual(len(free["trades"]), 2)

    def test_universe_is_the_live_board_with_todays_option_chain(self):
        nfo = [{"name": "PIIND", "instrument_type": "PE", "expiry": "2026-11-24", "strike": "1720", "instrument_token": "7",
                "lot_size": "175"}, {"name": "PIIND", "instrument_type": "FUT", "expiry": "2026-11-24", "strike": "0",
                "instrument_token": "8", "lot_size": "175"}]
        with mock.patch.object(J, "_tokens", return_value={"PIIND": "123", "NIFTY": "256265"}), \
                mock.patch.object(J, "_instruments", return_value=nfo):
            uni, chains = J.universe()
        from datetime import date
        self.assertEqual(uni, {"PIIND": 123, "NIFTY": 256265})
        self.assertEqual(dict(chains), {"PIIND": [(date(2026, 11, 24), 1720.0, "PE", 7, 175)]})

    def test_expiry_day_forces_the_exit(self):
        from datetime import date
        c = cand("A", 0, 0)
        c["expiry"] = "2026-11-03"
        exp_cut = datetime(2026, 11, 3, 15, 15, tzinfo=IST)
        ob = [(exp_cut - timedelta(minutes=1), 400, 400, 400, 400), (exp_cut, 410, 410, 410, 410)]
        with mock.patch.object(J, "exit_depends", return_value=(None, "OPEN")), \
             mock.patch.object(J, "exits", return_value={"LINE": (None, "OPEN")}), \
             mock.patch.object(J, "round_trip", return_value=mock.Mock(total_inr=0.0)):
            out = J.price_exits(c, [], [], [], [], [], [], ob, cfg=None)
        self.assertEqual({k: (v["out_t"], v["why"]) for k, v in out.items()},
                         {k: (exp_cut, "EXPIRY_DAY 15:15") for k in J.EXIT_KEYS})
        self.assertEqual(date.fromisoformat(c["expiry"]), exp_cut.date())


if __name__ == "__main__":
    unittest.main()
