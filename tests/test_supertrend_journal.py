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

    def test_replay_uses_the_whole_balance_reuses_profit_and_reports_skips(self):
        # 50k: A (45k premium) fits alone; B must wait; after A closes +10k, C (55k) fits in the 60k balance
        for c in (cand("A", 0, 10_000, prem=45_000, out_min=30), cand("B", 5, 4_000, prem=20_000),
                  cand("C", 40, -1_000, prem=55_000)):
            J.save(self.db, c)
        self.db.execute("INSERT INTO days VALUES ('2026-11-02', '{}')")
        main = next(v for v in J.replay(self.db)["versions"] if v["id"] == "MAIN")
        self.assertEqual([t["sym"] for t in main["trades"]], ["C", "A"])
        self.assertEqual((main["summary"]["balance"], main["summary"]["trades"]), (59_000, 2))
        self.assertEqual(main["skipped"], [{"reason": "not enough cash", "count": 1, "would_have_made": 4_000}])
        self.assertEqual(main["curve"], [{"day": "2026-11-02", "pnl": 9_000, "balance": 59_000}])

    def test_daily_stop_is_ten_percent_of_the_balance(self):
        for c in (cand("A", 0, -5_000, out_min=5), cand("B", 10, 1_000)):
            J.save(self.db, c)
        v = {x["id"]: x for x in J.replay(self.db)["versions"]}
        self.assertEqual([s["reason"] for s in v["MAIN"]["skipped"]], ["daily loss stop (10% of the balance) hit"])
        self.assertEqual(len(v["NO_DAY_LIMITS"]["trades"]), 2)

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
