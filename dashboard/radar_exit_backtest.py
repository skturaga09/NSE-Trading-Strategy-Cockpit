#!/usr/bin/env python3
"""
Can a target/stop rule capture the ignition radar's follow-through? OOS test on the ledger.

The ledger shows radar calls held to the close are a coin-flip (51% hit, +0.07%), yet price
typically runs ~+1.1% in the called direction at some point after the flag (avg MFE) and
~-1.0% against (avg MAE). Whether that MFE is capturable depends on ORDER: does the target
come before the stop? This replays every resolved radar call on its 5-min path AFTER the call.

Rule: exit at +T% (target) or -S% (stop), else at the session's last bar. Conservative:
if one 5-min bar touches both, the STOP is assumed first. Net of COST_PCT round trip.
T/S are chosen on the first half of the dates (train) and reported on the second (test) —
the full test grid is printed too, so a lucky cell can't hide a dead surface.

Reuses rec_ledger (calls, tokens, 5-min fetch). Self-check: `selfcheck`.
"""

import sys
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

TARGETS = (0.5, 0.75, 1.0, 1.5, 2.0)
STOPS = (0.5, 0.75, 1.0, 1.5)
COST_PCT = 0.10          # round trip on the underlying move; stops can also slip — not modelled
MIN_SAMPLE = 30


def _simulate(path: List[List[Any]], ref: float, d: int, tgt: float, stp: float) -> Optional[float]:
    """Directional % exit for one call. path = 5-min bars after the call. Stop wins a tie."""
    if not path or not ref:
        return None
    for bar in path:
        hi, lo = bar[2], bar[3]
        fav = (hi / ref - 1) * 100 if d == 1 else (1 - lo / ref) * 100
        adv = (1 - lo / ref) * 100 if d == 1 else (hi / ref - 1) * 100
        if adv >= stp:
            return -stp
        if fav >= tgt:
            return tgt
    return (path[-1][4] / ref - 1) * 100 * d


def _hold(path: List[List[Any]], ref: float, d: int) -> Optional[float]:
    return (path[-1][4] / ref - 1) * 100 * d if path and ref else None


def _load_paths() -> List[Tuple[str, int, float, List[List[Any]]]]:
    """(date, direction, ref, path-after-call) for every resolved radar call."""
    from dashboard import rec_ledger
    with rec_ledger._conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT symbol, date, ts, bias, ref_price FROM rec_ledger WHERE source='radar' AND resolved=1")]
    by_sym: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    out = []
    for i, (sym, rs) in enumerate(sorted(by_sym.items())):
        tok = rec_ledger._token(sym)
        if not tok:
            continue
        frm = min(r["date"] for r in rs) + " 09:15:00"
        to = max(r["date"] for r in rs) + " 15:30:00"
        cs = rec_ledger._candles_5m(tok, frm, to)
        time.sleep(0.35)
        for r in rs:
            call_t = r["ts"][:16].replace(" ", "T")
            path = [k for k in cs if k[0][:10] == r["date"] and k[0][:16] >= call_t]
            if path:
                out.append((r["date"], 1 if r["bias"] == "LONG" else -1, r["ref_price"], path))
        if (i + 1) % 50 == 0:
            print(f"  …{i + 1}/{len(by_sym)} symbols", file=sys.stderr)
    return out


def _stats(xs: List[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0, "net": 0.0, "win": 0.0}
    net = [x - COST_PCT for x in xs]
    return {"n": len(xs), "net": round(sum(net) / len(net), 3),
            "win": round(sum(1 for x in net if x > 0) / len(net) * 100, 1)}


def run() -> None:
    calls = _load_paths()
    if not calls:
        print("no resolved radar calls — run `python3 -m dashboard.rec_ledger backfill` first")
        return
    dates = sorted({c[0] for c in calls})
    split = dates[len(dates) // 2]
    train = [c for c in calls if c[0] < split]
    test = [c for c in calls if c[0] >= split]

    def grid(cs):
        return {(t, s): _stats([x for x in (_simulate(p, ref, d, t, s) for _, d, ref, p in cs) if x is not None])
                for t in TARGETS for s in STOPS}

    g_tr, g_te = grid(train), grid(test)
    hold_tr = _stats([x for x in (_hold(p, ref, d) for _, d, ref, p in train) if x is not None])
    hold_te = _stats([x for x in (_hold(p, ref, d) for _, d, ref, p in test) if x is not None])
    best = max(g_tr, key=lambda k: g_tr[k]["net"])

    print(f"\nRadar exit-rule OOS · {len(calls)} calls · {len(dates)} days · split {split} · cost {COST_PCT}% · stop wins ties")
    print(f"  hold-to-close   train net {hold_tr['net']:+}% win {hold_tr['win']}% (n {hold_tr['n']})"
          f" | test net {hold_te['net']:+}% win {hold_te['win']}% (n {hold_te['n']})")
    print(f"  best on TRAIN   T +{best[0]}% / S -{best[1]}%  → train net {g_tr[best]['net']:+}% win {g_tr[best]['win']}%")
    print(f"  same rule TEST  net {g_te[best]['net']:+}% win {g_te[best]['win']}% (n {g_te[best]['n']})")
    print("\n  TEST grid — avg net % per call (rows = target, cols = stop):")
    print("        " + "".join(f"  S-{s:<5}" for s in STOPS))
    for t in TARGETS:
        print(f"  T+{t:<4}" + "".join(f"{g_te[(t, s)]['net']:>+8.3f}" for s in STOPS))
    pos = sum(1 for k in g_te if g_te[k]["net"] > 0)
    te = g_te[best]
    if te["n"] < MIN_SAMPLE:
        verdict = f"inconclusive (test n={te['n']})"
    elif te["net"] > 0 and pos >= len(g_te) // 2:
        verdict = "EDGE — a target/stop rule captures the follow-through out-of-sample"
    elif te["net"] > 0:
        verdict = "fragile — the chosen cell is positive but most of the test grid is not (likely luck)"
    else:
        verdict = "no edge — the follow-through isn't capturable net of cost"
    print(f"\n  {pos}/{len(g_te)} test cells positive · verdict: {verdict}")


def _selfcheck() -> None:
    long_path = [["a", 100, 101.2, 99.8, 101, 0], ["b", 101, 101.5, 100.5, 101, 0]]
    assert _simulate(long_path, 100.0, 1, 1.0, 1.0) == 1.0          # target hit in bar 1
    tie = [["a", 100, 101.5, 98.5, 100, 0]]
    assert _simulate(tie, 100.0, 1, 1.0, 1.0) == -1.0                # both touched → stop wins
    drift = [["a", 100, 100.4, 99.7, 100.2, 0]]
    assert round(_simulate(drift, 100.0, 1, 1.0, 1.0), 2) == 0.2     # neither → exit at last close
    short = [["a", 100, 100.3, 98.9, 99, 0]]
    assert _simulate(short, 100.0, -1, 1.0, 1.0) == 1.0              # short target on the low
    print("selfcheck ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        _selfcheck()
    else:
        run()
