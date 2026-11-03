#!/usr/bin/env python3
"""
Does the Swing tab's overnight OI-buildup board predict the next day? OOS test.

The board (swing_scan.scan) lists, at the close:
  LONG  — Long buildup  (close ≥ prev close AND futures OI up) with OI change ≥ 10%
  SHORT — Short buildup (close <  prev close AND futures OI up) with OI change ≥ 10%
It was never scored. This replays the exact rule on Kite's CONTINUOUS futures daily series
(with OI, ~2 years) for the whole F&O universe, and measures, in the called direction:
  gap  = close → next open   (the overnight hold the board is for)
  1d   = close → next close
  3d   = close → close 3 sessions later
Net of COST_PCT; also "excess" = minus the universe's average move that day, so a rule
that only rides the market's drift (or a RISK_OFF tape) can't pass as skill.

Expiry roll: the continuous series switches contract at each expiry and OI jumps (e.g.
POLICYBZR 1.2M → 16M on 2026-10-28). Those days are found from the DATA — the universe's
median OI change spikes on a roll — and dropped, with the 3 sessions before (roll week).

Variants: the board as-is; strong tier (OI ≥ 20%); + close in the bottom/top 40% of the
range; + relative volume ≥ 1.5 (the ignition footprint); and the same move WITHOUT any OI
condition (does OI add anything over "follow the mover"?). Dates split in half: train/test.

Run: python3 -m dashboard.swing_backtest   (needs a live Kite token; ~3 min)
"""

import statistics
import sys
import time
from collections import defaultdict
from datetime import date
from typing import Any, Callable, Dict, List, Tuple

import requests

COST_PCT = 0.10
MIN_SAMPLE = 30
WINDOWS = (("2025-01-01", "2025-12-31"), ("2026-01-01", None))
ROLL_MEDIAN_OI = 30.0     # universe-median |OI change| above this on a day = an expiry roll


def _fetch(token: str) -> List[List[Any]]:
    from dashboard.swing_scan import _headers
    out: List[List[Any]] = []
    for frm, to in WINDOWS:
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": to or date.today().isoformat(), "oi": 1, "continuous": 1},
                         headers=_headers(), timeout=20).json()
        if j.get("status") == "success":
            out += [c for c in j["data"]["candles"] if len(c) > 6 and c[6]]
        time.sleep(0.35)
    return out


def _features(cs: List[List[Any]]) -> List[Dict[str, Any]]:
    """Per day i (with i-1 behind and i+3 ahead): the board's inputs and the outcomes."""
    rows = []
    for i in range(20, len(cs) - 3):
        p, c, n1, n3 = cs[i - 1], cs[i], cs[i + 1], cs[i + 3]
        if not (p[4] and p[6] and c[4]):
            continue
        rng = c[2] - c[3]
        vols = [x[5] for x in cs[i - 20:i] if x[5]]
        rows.append({
            "date": c[0][:10],
            "move": (c[4] / p[4] - 1) * 100,
            "oi_chg": (c[6] / p[6] - 1) * 100,
            "range_pos": (c[4] - c[3]) / rng if rng > 0 else 0.5,
            "rel_vol": c[5] / (sum(vols) / len(vols)) if vols and c[5] else None,
            "gap": (n1[1] / c[4] - 1) * 100,
            "d1": (n1[4] / c[4] - 1) * 100,
            "d3": (n3[4] / c[4] - 1) * 100,
        })
    return rows


def _direction(r: Dict[str, Any]) -> int:
    return 1 if r["move"] >= 0 else -1


RULES: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    "board (buildup, OI ≥10%)": lambda r: r["oi_chg"] >= 10,
    "strong (OI ≥20%)": lambda r: r["oi_chg"] >= 20,
    "board + close at extreme": lambda r: r["oi_chg"] >= 10 and
        (r["range_pos"] >= 0.6 if r["move"] >= 0 else r["range_pos"] <= 0.4),
    "board + rel vol ≥1.5": lambda r: r["oi_chg"] >= 10 and (r["rel_vol"] or 0) >= 1.5,
    "NO OI: mover |move|≥2% only": lambda r: abs(r["move"]) >= 2,
}


def _stats(xs: List[float]) -> Dict[str, Any]:
    if not xs:
        return {"n": 0, "mean": 0.0, "win": 0.0}
    return {"n": len(xs), "mean": round(statistics.fmean(xs), 3),
            "win": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1)}


def evaluate(data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Pure: score every rule × side × horizon on train/test halves. data = name → rows."""
    by_day: Dict[str, List[float]] = defaultdict(list)
    oi_by_day: Dict[str, List[float]] = defaultdict(list)
    for rows in data.values():
        for r in rows:
            by_day[r["date"]].append(r)
            oi_by_day[r["date"]].append(abs(r["oi_chg"]))
    days = sorted(by_day)
    rolls = {d for d in days if statistics.median(oi_by_day[d]) > ROLL_MEDIAN_OI}
    drop = set(rolls)
    for d in rolls:                                   # roll week: the 3 sessions before the switch
        i = days.index(d)
        drop.update(days[max(0, i - 3):i])
    mkt = {d: {h: statistics.fmean(r[h] for r in by_day[d]) for h in ("gap", "d1", "d3")} for d in days}
    usable = [d for d in days if d not in drop]
    split = usable[len(usable) // 2]
    out: Dict[str, Any] = {"days": len(usable), "rolls": sorted(rolls), "split": split, "rules": {}}
    for name, rule in RULES.items():
        res: Dict[Tuple[str, str, str, str], List[float]] = defaultdict(list)
        for rows in data.values():
            for r in rows:
                if r["date"] in drop or not rule(r):
                    continue
                if not (name.startswith("NO OI") or r["oi_chg"] > 0):
                    continue                          # buildup = OI UP (long/short buildup only)
                d = _direction(r)
                half = "train" if r["date"] < split else "test"
                side = "LONG" if d == 1 else "SHORT"
                for h in ("gap", "d1", "d3"):
                    net = r[h] * d - COST_PCT
                    res[(half, side, h, "net")].append(net)
                    res[(half, side, h, "excess")].append((r[h] - mkt[r["date"]][h]) * d - COST_PCT)
        out["rules"][name] = {k: _stats(v) for k, v in res.items()}
    return out


def _report(ev: Dict[str, Any]) -> None:
    print(f"\nSwing OI-buildup board · OOS · {ev['days']} usable sessions · split {ev['split']}"
          f" · {len(ev['rolls'])} roll-week days dropped · cost {COST_PCT}%")
    print("  cells = mean % per call net of cost (win %) [n]; 'excess' = vs the universe that day\n")
    for name, cells in ev["rules"].items():
        print(f"  ── {name}")
        for side in ("LONG", "SHORT"):
            for h, lab in (("gap", "close→open "), ("d1", "close→close"), ("d3", "3-day      ")):
                line = f"     {side:<5} {lab}"
                for half in ("train", "test"):
                    s, e = cells.get((half, side, h, "net"), {"n": 0}), cells.get((half, side, h, "excess"), {"n": 0})
                    if s["n"]:
                        line += f" | {half} {s['mean']:+.3f}% ({s['win']}%) xs {e['mean']:+.3f}% [n {s['n']}]"
                print(line)
    verdicts = []
    for name, cells in ev["rules"].items():
        for side in ("LONG", "SHORT"):
            for h in ("gap", "d1", "d3"):
                tr, te = cells.get(("train", side, h, "excess")), cells.get(("test", side, h, "excess"))
                if tr and te and te["n"] >= MIN_SAMPLE and tr["mean"] > 0 and te["mean"] > 0:
                    verdicts.append(f"{name} · {side} · {h}: train {tr['mean']:+.3f}% → test {te['mean']:+.3f}%")
    print("\n  Positive excess in BOTH halves (n ≥ 30):" if verdicts else
          "\n  verdict: no rule/side/horizon beats the universe in both halves — the board has no OOS edge")
    for v in verdicts:
        print("   ", v)


def run() -> None:
    from dashboard.swing_scan import _futures_map
    fm = _futures_map()
    data = {}
    for i, (name, f) in enumerate(sorted(fm.items())):
        cs = _fetch(f["token"])
        if len(cs) > 30:
            data[name] = _features(cs)
        if (i + 1) % 40 == 0:
            print(f"  …{i + 1}/{len(fm)} names", file=sys.stderr)
    _report(evaluate(data))


def _selfcheck() -> None:
    # 26 flat days, then a short buildup (−3%, OI +25%), then a −2% next day.
    cs = [[f"2026-01-{i + 1:02d}T", 100, 101, 99, 100, 1000, 1000] for i in range(21)]
    cs += [["2026-01-22T", 100, 100, 96, 97, 3000, 1250], ["2026-01-23T", 96, 96, 94, 95.06, 1000, 1300],
           ["2026-01-24T", 95, 95, 95, 95, 1000, 1300], ["2026-01-25T", 95, 95, 95, 95, 1000, 1300]]
    rows = _features(cs)
    r = next(x for x in rows if x["date"] == "2026-01-22")
    assert round(r["move"], 2) == -3.0 and round(r["oi_chg"], 1) == 25.0 and r["range_pos"] == 0.25
    assert round(r["d1"], 1) == -2.0 and round(r["rel_vol"], 1) == 3.0
    assert _direction(r) == -1 and RULES["board + close at extreme"](r)
    print("selfcheck ok")


if __name__ == "__main__":
    _selfcheck() if len(sys.argv) > 1 and sys.argv[1] == "selfcheck" else run()
