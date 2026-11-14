import json
import tempfile
import unittest
from pathlib import Path

from engine.dashboard import track_record, verdict


def rec(status="REJECTED", gates=(), risk=(), **oa):
    return {"status": status, "gates": [{"name": n, "passed": False, "detail": d, "type": "x"} for n, d in gates],
            "risk_reasons": list(risk), "opportunity_age": oa}


class Verdict(unittest.TestCase):
    def test_eligible_is_buy_and_retest_is_wait(self):
        self.assertEqual(verdict(rec("ENTRY_ELIGIBLE"))["action"], "BUY")
        self.assertEqual(verdict(rec("WAIT_FOR_RETEST"))["action"], "WAIT")

    def test_missing_option_data_alone_is_check_not_avoid(self):
        # 2026-11-09: the chosen option was not recorded; the risk check lists every rule it could not evaluate
        v = verdict(rec(gates=[("DATA_QUALITY", "NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE"),
                               ("SPREAD_ACCEPTABLE", "spread None %"),
                               ("COST_MODEL_VERIFIED", "cost estimate UNVERIFIED or missing")],
                        risk=["SPREAD_TOO_WIDE: spread None %, None % of the move to T1", "MIN_NET_RR: net R:R None vs 1.0"],
                        classification="TIMELY", failed_rules=[]))
        self.assertEqual(v["action"], "CHECK")

    def test_missing_option_data_with_a_trade_problem_is_avoid_not_check(self):
        gap = ("DATA_QUALITY", "DATA_NOT_OK:NO_QUOTE")
        cases = {  # each also lacked an option price; CHECK would have said "setup passed"
            "the engine could not judge whether this move is still on time":
                rec(gates=[gap, ("TIMELINESS", "Phase 6 UNKNOWN (INPUT_UNAVAILABLE)")], classification="UNKNOWN"),
            "the signal is too old":
                rec(gates=[gap, ("TIMELINESS", "Phase 6 VALID_BUT_LATE (RULES_FAILED)")], classification="VALID_BUT_LATE",
                    failed_rules=["AGE_VS_HALF_LIFE"]),
            "no clear stop-loss and target for this trade":
                rec(gates=[gap, ("VALID_ENTRY_STOP", "no defensible stop / target / R:R: obstacle: NO_LEVEL_MAP")]),
            "you already have a position in this stock": rec(gates=[gap, ("NO_CONFLICTING_POSITION", "open: TATASTEEL")]),
            "this contract cannot be traded now (e.g. F&O ban): 123: BAN_PERIOD":
                rec(gates=[gap, ("INSTRUMENT_TRADABLE", "123: BAN_PERIOD")]),
        }
        for why, p in cases.items():
            self.assertEqual(verdict(p), {"action": "AVOID", "why": [why]})
        # no contract chosen at all because the chain was missing: still a data gap
        self.assertEqual(verdict(rec(gates=[gap, ("INSTRUMENT_TRADABLE", "no priced candidate")]))["action"], "CHECK")

    def test_trade_problems_are_avoid_in_plain_words(self):
        v = verdict(rec(gates=[("TIMELINESS", "Phase 6 VALID_BUT_LATE (RULES_FAILED)"),
                               ("SPREAD_ACCEPTABLE", "SPREAD_TOO_WIDE (2.098 % > 2.0 %)"),
                               ("LIQUIDITY_MINIMUM", "not sized: EVENT_IV_RISK: board meeting 2026-11-12 (Financial Results)")],
                        risk=["DAILY_LOSS_LIMIT: -31000 vs -30000"],
                        classification="VALID_BUT_LATE", failed_rules=["EXTENDED", "RR_BELOW_MIN", "STOP_TOO_WIDE"],
                        extension_atr=1.84, current_rr=0.42, stop_distance_atr=2.5))
        self.assertEqual(v["action"], "AVOID")
        self.assertEqual(v["why"], [
            "too late: price already ran 1.8x its normal move since the signal",
            "too little left to gain: reward is 0.4x the risk from here",
            "stop-loss too far away (2.5x the normal move): a loss would be large",
            "company results/board meeting within days: option prices often drop after the event",
            "the option's buy/sell gap is too wide for the expected move",
            "your daily limits (loss, open trades or loss streak) are reached"])

    def test_track_record_sums_each_days_closed_option_trades(self):
        with tempfile.TemporaryDirectory() as t:
            for day, rows in {"2026-11-06": [{"result": "CLOSED", "contract": "A 1 CE", "dir": "LONG", "net": 100.4},
                                             {"result": "CLOSED", "contract": "B 1 PE", "dir": "SHORT", "net": -300.0},
                                             {"result": "NO FILL", "dir": "LONG"}],
                              "2026-11-09": [{"result": "CLOSED", "contract": "C 1 CE", "dir": "LONG", "net": 50.0}]}.items():
                (Path(t) / day).mkdir()
                (Path(t) / day / "trader_test.json").write_text(json.dumps(rows))
            self.assertEqual(track_record(t, "2026-11-06"), [
                {"day": "2026-11-06", "trades": 2, "wins": 1, "net_inr": -200, "calls_net_inr": 100, "puts_net_inr": -300}])
            self.assertEqual([d["day"] for d in track_record(t, "2026-11-09")], ["2026-11-06", "2026-11-09"])


if __name__ == "__main__":
    unittest.main()
