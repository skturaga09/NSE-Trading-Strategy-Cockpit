"""Phase 3: tiered subscription allocator, tier book, executor. No network."""

import random
import unittest
from pathlib import Path

from engine.recorder import TierExecutor
from engine.tiers import MODES, TIER_RANK, Request, TierBook, allocate, assign

from .fixtures import make_config


def req(tok, tier="A", mode="quote", order=0):
    return Request(tok, tier, mode, "FUT", "X", f"r{tok}", order)


class TestAllocate(unittest.TestCase):
    def test_never_exceeds_limits_for_any_input_size_property(self):
        rng = random.Random(20261105)
        for trial in range(300):
            per, most = rng.randint(1, 60), rng.randint(1, 4)
            n = rng.choice([0, 1, per * most - 1, per * most, per * most + 1, rng.randint(0, 5000)])
            reqs = [req(rng.randint(1, max(1, n)), rng.choice("ABC"), rng.choice(list(MODES)), rng.randint(0, 50))
                    for _ in range(n)]
            p = allocate(reqs, per, most)
            self.assertLessEqual(len(p.subs), per * most)
            asked = {r.token for r in reqs}
            self.assertEqual(len(p.subs), min(len(asked), per * most))
            self.assertEqual({t for t, _, _ in p.dropped}, asked - set(p.subs))      # every loss is logged
            for t, m in p.subs.items():                                             # richest mode asked wins
                self.assertEqual(MODES[m], max(MODES[r.mode] for r in reqs if r.token == t))
            prio = lambda r: (TIER_RANK[r.tier], r.order, r.token)  # noqa: E731
            if p.dropped:   # nothing kept ranks below something dropped
                worst_kept = max(min(prio(r) for r in reqs if r.token == t) for t in p.subs) if p.subs else None
                best_drop = min(min(prio(r) for r in reqs if r.token == t) for t in asked - set(p.subs))
                if worst_kept:
                    self.assertLess(worst_kept, best_drop)
            current = {}
            for _ in range(3):  # re-plans keep fitting the connections
                sub = dict(rng.sample(sorted(p.subs.items()), rng.randint(0, len(p.subs))))
                current, ops = assign(sub, current, per, most)
                self.assertLessEqual(len(current), most)
                self.assertTrue(all(len(c) <= per for c in current.values()))
                self.assertEqual({t: m for c in current.values() for t, m in c.items()}, sub)

    def test_priority_upgrade_and_drop_reason(self):
        p = allocate([req(1), req(2), req(3, "B", "full"), req(1, "B", "full"), req(4, "C")], 1, 3)
        self.assertEqual(p.subs, {1: "full", 2: "quote", 3: "full"})
        self.assertEqual(p.meta[1][0], "AB")
        self.assertEqual([(t, tier) for t, tier, _ in p.dropped], [(4, "C")])
        self.assertIn("over the limit of 3 tokens (3 connections x 1, F-WS-2)", p.dropped[0][2])
        self.assertEqual((p.usage["A"], p.usage["B"], p.usage["total"], p.usage["dropped"]), (2, 2, 3, 1))

    def test_assign_keeps_tokens_on_their_connection(self):
        cur, ops = assign({1: "quote", 2: "quote", 3: "full"}, {}, 2, 2)
        self.assertEqual(cur, {0: {1: "quote", 2: "quote"}, 1: {3: "full"}})
        self.assertEqual(ops[0], (0, "open", None, ()))
        cur2, ops = assign({2: "full", 3: "full", 4: "quote"}, cur, 2, 2)
        self.assertEqual(cur2, {0: {2: "full", 4: "quote"}, 1: {3: "full"}})
        self.assertEqual(ops, [(0, "unsubscribe", None, (1,)), (0, "subscribe", None, (4,)),
                               (0, "mode", "full", (2,)), (0, "mode", "quote", (4,))])
        with self.assertRaises(ValueError):
            assign({1: "q", 2: "q", 3: "q"}, {}, 1, 2)


class Clock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


class FakeRec:
    def __init__(self):
        self.events = []

    def on_conn_event(self, conn, kind, detail):
        self.events.append((kind, detail))


class TestBookAndExecutor(unittest.TestCase):
    def test_promote_ttl_demote_and_executor_ops(self):
        cfg = make_config(Path("/tmp"), **{"ws.max_tokens_per_connection": 2, "ws.max_connections": 2})
        clock = Clock()
        book = TierBook(cfg, clock, describe=lambda t: ("CE", "NIFTY"))
        book.set_tier_a([req(1, mode="quote"), req(2, mode="full", order=1)])
        rec, sent, opened, up = FakeRec(), [], [], set()
        ex = TierExecutor(rec, book, cfg, opened.append, lambda *a: sent.append(a), lambda s: s in up)
        ex.step()
        self.assertEqual(opened, [0])
        self.assertEqual(sent, [])                       # not connected yet: ops wait
        up.add(0)
        ex.step()
        self.assertEqual(sent, [(0, "subscribe", None, (1, 2)), (0, "mode", "full", (2,)), (0, "mode", "quote", (1,))])
        book.promote(1, "watch", ttl=60)                 # B: quote -> full, same slot
        book.promote(7, "option pick", ttl=30, tier="C")
        book.promote(8, "option pick", ttl=30, tier="C")
        book.promote(9, "option pick", ttl=30, tier="C")  # 5th token: over 2 x 2
        sent.clear()
        p = ex.step()
        self.assertEqual(p.subs, {1: "full", 2: "full", 7: "quote", 8: "quote"})
        self.assertEqual(p.meta[7], ("C", "CE", "NIFTY"))
        self.assertEqual(opened, [0, 1])
        self.assertIn((0, "mode", "full", (1,)), sent)
        drops = [d for k, d in rec.events if k == "tier_drop"]
        self.assertEqual([(d["token"], d["tier"]) for d in drops], [(9, "C")])
        ex.step()
        self.assertEqual(len([1 for k, _ in rec.events if k == "tier_drop"]), 1)  # logged once
        clock.t = int(31e9)                              # C expires, B (60 s) stays
        self.assertEqual(book.plan().subs, {1: "full", 2: "full"})
        book.demote(1)
        self.assertEqual(book.plan().subs, {1: "quote", 2: "full"})
        plans = [d for k, d in rec.events if k == "tier_plan"]
        self.assertEqual(plans[0]["plan"], {"1": ["quote", "A", "FUT", "X"], "2": ["full", "A", "FUT", "X"]})


if __name__ == "__main__":
    unittest.main()
