"""Phase 10 dashboard shaping (pure): panel envelopes with provenance and age, radar rows, positioning cells, per-ledger
performance, health summary. Reads no clock, disk or network: the view time `now_ns` is an input (wall clock in live view,
the replay clock in a replayed session). The API (engine.api) does the reads.

Value convention (the engine's `jsonable`): a number/string, or {"UNAVAILABLE": reason}. The frontend shows "—" with the
reason; it computes nothing. Positioning labels are hypotheses about the data (G.DISCLAIMER), never "institutions are buying".
SIMULATED and ACTUAL performance are computed one ledger at a time; there is no function that adds them.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean

from . import signals as G
from .candles import IST, S, Unavailable
from .snapshots import jsonable

OK, STALE, UNAVAILABLE = "OK", "STALE", "UNAVAILABLE"
QUADRANTS = {G.LONG_BUILDUP: ("PRICE_UP", "OI_UP"), G.SHORT_BUILDUP: ("PRICE_DOWN", "OI_UP"),
             G.SHORT_COVERING: ("PRICE_UP", "OI_DOWN"), G.LONG_UNWINDING: ("PRICE_DOWN", "OI_DOWN")}


def U(reason: str) -> dict:
    return {"UNAVAILABLE": reason}


def is_u(v) -> bool:
    return isinstance(v, Unavailable) or (isinstance(v, dict) and "UNAVAILABLE" in v)


def envelope(panel: str, data, *, source: str, observed_ns: int | None, received_ns: int | None,
             processed_ns: int | None, now_ns: int, mode: str, cfg, reason: str | None = None) -> dict:
    """Every panel: provenance (source, exchange observation, receive, processing time), age at the view time, status."""
    if observed_ns is not None and observed_ns > now_ns:          # a replay must never see the future
        reason = (f"look-ahead: the newest {panel} observation ({datetime.fromtimestamp(observed_ns / S, IST):%H:%M:%S} IST) "
                  f"is after the view time; {source} keeps no history before it")
        observed_ns = received_ns = processed_ns = None
        data = None
    age = None if observed_ns is None else round((now_ns - observed_ns) / S, 3)
    lim = cfg.get("dashboard.stale_after_s").get(panel)
    status = UNAVAILABLE if observed_ns is None else (STALE if lim is not None and age > lim else OK)
    return {"panel": panel, "mode": mode, "now_ns": now_ns, "status": status,
            "reason": reason or (f"no observation for {panel}" if observed_ns is None else
                                 f"newest observation {age:.0f} s old > {lim} s" if status == STALE else None),
            "provenance": {"source": source, "observed_ns": observed_ns, "received_ns": received_ns,
                           "processed_ns": processed_ns, "tz": "Asia/Kolkata"},
            "age_s": age, "stale_after_s": lim, "config_version": cfg.version, "data": jsonable(data)}


def hypothesis(hyp: str, reasons) -> str | dict:
    """As signals._hyp: a neutral view whose reasons are not 'evaluated and neutral' could not be evaluated."""
    if hyp == G.NEUTRAL and not set(reasons) <= G.EVALUATED_NEUTRAL:
        return U("POSITIONING_UNAVAILABLE: " + ",".join(reasons))
    return hyp


def timeliness(opp: dict) -> str | dict:
    """Phase 6 classification at the decision → the radar's TIMELY / LATE / RETEST / EXHAUSTED (UNKNOWN stays UNKNOWN)."""
    c = opp.get("classification")
    if c is None:
        return U("no Phase 6 classification at the decision")
    if c == "TIMELY":
        return "RETEST" if opp.get("reason") == "RETEST" else "TIMELY"
    return {"VALID_BUT_LATE": "LATE", "EXHAUSTED": "EXHAUSTED"}.get(c, c)


# Gate details that only say the engine lacked option data (not that the trade is bad) -> CHECK, never AVOID.
_DATA_GAPS = ("NO_QUOTE", "STALE_QUOTE", "NO_PREMIUM_MODEL", "IV_PERCENTILE_UNAVAILABLE", "ATM_IV_UNAVAILABLE", "NO_ATM",
              "spread None", "UNVERIFIED or missing", "NO_TWO_SIDED_BOOK", "price age")


def verdict(p: dict) -> dict:
    """One Phase 8 recommendation -> {action: BUY | WAIT | CHECK | AVOID, why: [plain-English reasons]} for a trader.
    AVOID = something about the trade itself is wrong; CHECK = the setup passed but the engine had no live option data,
    so the trader must look at the option's bid/ask before acting. Presentation only: the stored status is unchanged."""
    if p["status"] == "ENTRY_ELIGIBLE":
        return {"action": "BUY", "why": ["every check passed"]}
    if p["status"] == "WAIT_FOR_RETEST":
        return {"action": "WAIT", "why": ["good setup, but price has run; wait for it to come back to the entry level"]}
    oa, bad = p.get("opportunity_age") or {}, []
    rules = oa.get("failed_rules") or []
    if oa.get("classification") == "EXHAUSTED":
        bad.append("the move looks spent: buying is fading while price stretches")
    if "EXTENDED" in rules and isinstance(oa.get("extension_atr"), (int, float)):
        bad.append(f"too late: price already ran {oa['extension_atr']:.1f}x its normal move since the signal")
    if "RR_BELOW_MIN" in rules and isinstance(oa.get("current_rr"), (int, float)):
        bad.append(f"too little left to gain: reward is {oa['current_rr']:.1f}x the risk from here")
    if "STOP_TOO_WIDE" in rules and isinstance(oa.get("stop_distance_atr"), (int, float)):
        bad.append(f"stop-loss too far away ({oa['stop_distance_atr']:.1f}x the normal move): a loss would be large")
    details = " ".join(g["detail"] for g in p["gates"] if not g["passed"])
    if "EVENT_IV_RISK" in details:
        bad.append("company results/board meeting within days: option prices often drop after the event")
    if "TOO_WIDE (" in details:   # a measured spread; risk_reasons also lists 'SPREAD_TOO_WIDE: spread None' when unmeasured
        bad.append("the option's buy/sell gap is too wide for the expected move")
    if "BAD_GEOMETRY" in details:
        bad.append("stop and target don't fit the option's current price")
    caps = ("DAILY_LOSS_LIMIT", "MAX_OPEN_POSITIONS", "MAX_DAILY_TRADES", "CONSECUTIVE_LOSSES_COOLDOWN")
    if any(r.startswith(caps) for r in p.get("risk_reasons") or []):
        bad.append("your daily limits (loss, open trades or loss streak) are reached")
    # gates that fail for a reason about the trade, not missing option data: never CHECK
    failed = {g["name"]: g["detail"] for g in p["gates"] if not g["passed"]}
    if "TIMELINESS" in failed and not bad:
        bad.append("the signal is too old" if "AGE_VS_HALF_LIFE" in rules else
                   "the engine could not judge whether this move is still on time")
    if "VALID_ENTRY_STOP" in failed and "BAD_GEOMETRY" not in details:
        bad.append("no clear stop-loss and target for this trade")
    if failed.get("INSTRUMENT_TRADABLE", "no priced candidate") != "no priced candidate":
        bad.append("this contract cannot be traded now (e.g. F&O ban): " + failed["INSTRUMENT_TRADABLE"])
    if "NO_CONFLICTING_POSITION" in failed:
        bad.append("you already have a position in this stock")
    if bad:
        return {"action": "AVOID", "why": bad}
    if any(k in details for k in _DATA_GAPS):
        return {"action": "CHECK", "why": ["setup passed, but the engine had no live price for this option: check its "
                                           "bid/ask on Kite; buy only if the gap is under 2% of the price"]}
    return {"action": "AVOID", "why": [g["name"].replace("_", " ").lower() + ": " + g["detail"]
                                       for g in p["gates"] if not g["passed"] and g["name"] != "RISK_CHECK_APPROVED"][:2]
            or ["rejected"]}


def track_record(root, upto: str) -> list[dict]:
    """Each recorded day's <day>/trader_test.json (scripts/options_trader_test.py: every signal taken as a long option, one
    lot, on Kite's real 1-minute option candles, after charges; APPROXIMATE spread) -> one rupee summary per day <= upto."""
    out = []
    for f in sorted(Path(root).glob("????-??-??/trader_test.json")):
        if f.parent.name > upto:
            continue
        try:
            rows = [r for r in json.loads(f.read_text()) if r.get("result") == "CLOSED" and "contract" in r]
        except (OSError, ValueError):
            continue
        if rows:
            net = lambda rs: round(sum(r["net"] for r in rs))  # noqa: E731
            out.append({"day": f.parent.name, "trades": len(rows), "wins": sum(r["net"] > 0 for r in rows),
                        "net_inr": net(rows), "calls_net_inr": net([r for r in rows if r["dir"] == "LONG"]),
                        "puts_net_inr": net([r for r in rows if r["dir"] == "SHORT"])})
    return out


def radar_row(p: dict, inputs, fw: int, lifecycle_state: str | None) -> dict:
    """One Phase 8 recommendation payload (+ its stored inputs for the OI / price / RVOL features) → a radar row."""
    st = inputs.evidence.positioning if inputs is not None else None
    f = lambda name: U(f"NO_POSITIONING_STATE at the decision") if st is None else jsonable(  # noqa: E731
        next((x.value for x in st.features if x.name == name), Unavailable(f"FEATURE_MISSING: {name}")))
    sc = p["score"]["headline"]
    return {"recommendation_id": p["recommendation_id"], "signal_id": p["signal_id"], "as_of": p["as_of"],
            "symbol": p["underlying"], "contract": p["contract"], "direction": p["direction"],
            "signal": p["classification"], "family": p["setup_family"], "kind": p["setup_kind"],
            "oi_pct": f(f"combined_oi_chg_{fw}m_pct"), "price_pct": f(f"fut_price_chg_{fw}m_pct"), "rvol": f(f"rvol_{fw}m"),
            "score": sc["points"], "score_available_max": sc["available_max"], "band": sc["band"],
            "timeliness": timeliness(p["opportunity_age"]),
            "entry": p["entry_trigger"], "sl": p["underlying_invalidation"], "target": p["t1"],
            "status": p["status"], "verdict": verdict(p), "lifecycle_state": lifecycle_state or U("no lifecycle row"),
            "rejected_reasons": [g["name"] + ": " + g["detail"] for g in p["gates"] if not g["passed"]],
            "risk_reasons": p["risk_reasons"], "warnings": p["warnings"], "labels": p["labels"]}


def positioning_cell(und: str, row: dict) -> dict:
    h = hypothesis(row["hypothesis"], row["reasons"])
    q = QUADRANTS.get(h) if isinstance(h, str) else None
    return {"underlying": und, "ts_ns": row["ts_ns"], "hypothesis": h,
            "price_axis": q[0] if q else U("no quadrant: " + (h["UNAVAILABLE"] if is_u(h) else str(h))),
            "oi_axis": q[1] if q else U("no quadrant"), "suppressed": row["suppressed"],
            "price_chg_pct": row["price_chg_pct"], "oi_chg_pct": row["oi_chg_pct"], "rvol": row["rvol"]}


# ---------------------------------------------------------------- performance (ONE ledger)
def _bucket(ns: int) -> str:
    t = datetime.fromtimestamp(ns / S, IST)
    return f"{t.hour:02d}:00–{t.hour:02d}:59"


def performance(ledger: str, closed: list[dict]) -> dict:
    """closed: one ledger's closed trades {net, gross, charges, slippage_inr, exit_ns, entry_ns, family, underlying,
    score_band, timeliness}. Every metric is UNAVAILABLE when it cannot be computed; nothing is borrowed from the other ledger."""
    if any(t.get("ledger") not in (None, ledger) for t in closed):
        raise ValueError(f"performance({ledger}) received a trade of another ledger")
    none = U(f"no closed {ledger} trades")
    if not closed:
        return {"ledger": ledger, "trades": 0, "win_rate": none, "expectancy_inr": none, "profit_factor": none,
                "max_drawdown_inr": none, "net_inr": none, "gross_inr": none, "charges_inr": none, "slippage_inr": none,
                "daily": [], "cumulative": [], "by": {}}
    trades = sorted(closed, key=lambda t: t["exit_ns"])
    nets = [t["net"] for t in trades]
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x < 0]
    cum, peak, dd, curve = 0.0, 0.0, 0.0, []
    for t in trades:
        cum += t["net"]
        peak, dd = max(peak, cum), max(dd, peak - cum)
        curve.append({"ts_ns": t["exit_ns"], "cumulative_net_inr": round(cum, 2)})
    daily = defaultdict(float)
    for t in trades:
        daily[datetime.fromtimestamp(t["exit_ns"] / S, IST).date().isoformat()] += t["net"]
    slip = [t["slippage_inr"] for t in trades]

    def group(key):
        g = defaultdict(list)
        for t in trades:
            k = t.get(key)
            g["UNAVAILABLE: " + k["UNAVAILABLE"] if is_u(k) else str(k)].append(t["net"])
        return {k: {"trades": len(v), "net_inr": round(sum(v), 2), "win_rate": round(sum(x > 0 for x in v) / len(v), 4),
                    "expectancy_inr": round(fmean(v), 2)} for k, v in sorted(g.items())}

    by = {k: group(k) for k in ("family", "underlying", "score_band", "timeliness")}
    by["time_of_day"] = group_by_hour(trades)
    by["regime"] = U("no regime classifier exists in the engine")
    return {"ledger": ledger, "trades": len(trades), "win_rate": round(len(wins) / len(nets), 4),
            "expectancy_inr": round(fmean(nets), 2),
            "profit_factor": round(sum(wins) / -sum(losses), 4) if losses else U("no losing trade: profit factor undefined"),
            "max_drawdown_inr": round(dd, 2), "net_inr": round(sum(nets), 2), "gross_inr": round(sum(t["gross"] for t in trades), 2),
            "charges_inr": round(sum(t["charges"] for t in trades), 2),
            "slippage_inr": U("slippage unknown for " + ", ".join(t["id"] for t in trades if is_u(t["slippage_inr"])))
            if any(map(is_u, slip)) else round(sum(slip), 2),
            "daily": [{"date": d, "net_inr": round(v, 2)} for d, v in sorted(daily.items())], "cumulative": curve, "by": by}


def group_by_hour(trades: list[dict]) -> dict:
    g = defaultdict(list)
    for t in trades:
        g[_bucket(t["entry_ns"])].append(t["net"])
    return {k: {"trades": len(v), "net_inr": round(sum(v), 2), "win_rate": round(sum(x > 0 for x in v) / len(v), 4),
                "expectancy_inr": round(fmean(v), 2)} for k, v in sorted(g.items())}


# ---------------------------------------------------------------- system health
def health(status: dict | None, feed: dict | None, now_ns: int, stale_price_s: float) -> dict:
    if status is None:
        return {"feed": U("no recorder status.json for this date")}
    inst = status.get("instruments", {})
    stale = [v.get("symbol", k) for k, v in inst.items()
             if v.get("last_receive_ns") is None or (now_ns - v["last_receive_ns"]) / S > stale_price_s]
    return {"connections": status.get("connections"), "ticks_per_s": status.get("ticks_per_s"),
            "queue": {"depth": status.get("queue_depth"), "max": status.get("queue_max")},
            "dropped_total": status.get("dropped_total"), "gaps_today": status.get("gaps_today"),
            "degraded": status.get("degraded"), "instruments": len(inst),
            "stale_instruments": len(stale), "stale_sample": sorted(stale)[:12],
            "gaps": feed.get("gaps") if feed else U("no feed_report.json (written at EOD)"),
            "allocator": feed.get("allocator") if feed else U("no feed_report.json (written at EOD)"),
            "latency_s": feed.get("latency_s") if feed else U("no feed_report.json (written at EOD)"),
            "staleness": feed.get("staleness") if feed else U("no feed_report.json (written at EOD)")}


def chain_view(snaps: list[dict], rec: dict | None) -> dict:
    """Panel D. snaps: stored ChainSnapshot payloads (one per expiry, latest at or before the view time); rec: the latest
    recommendation payload for the underlying, or None. The comparison lists the selected contract's expiry and type at
    the ITM / ATM / OTM strikes around that snapshot's ATM, plus the selected strike; values are copied, not computed."""
    sel = None if rec is None else {k: rec.get(k) for k in ("contract", "token", "instrument_type", "expiry", "strike",
                                                             "status", "recommendation_id", "as_of")}
    cmp_rows = U("NO_SELECTED_OPTION: " + ("no recommendation" if rec is None else "the selected contract is not an option"))
    tok = None if rec is None else rec.get("token")
    if rec is not None and rec.get("instrument_type") in ("CE", "PE"):
        s = next((x for x in snaps if x["expiry"] == rec.get("expiry")), None)
        if s is None or is_u(s["atm_strike"]):
            cmp_rows = U(f"NO_CHAIN_FOR_EXPIRY {rec.get('expiry')}")
        else:
            ks = sorted({r["strike"] for r in s["rows"]})
            i, sign = ks.index(s["atm_strike"]), (1 if rec["instrument_type"] == "CE" else -1)
            want = {s["atm_strike"]: "ATM"}
            for role, j in (("ITM", i - sign), ("OTM", i + sign)):
                if 0 <= j < len(ks):
                    want[ks[j]] = role
            cmp_rows = [{**{k: r[k] for k in ("strike", "kind", "premium", "spread_pct", "iv", "greeks", "oi", "oi_change",
                                               "volume_day", "depth_bid_qty", "depth_ask_qty", "hypothesis")},
                         "role": want.get(r["strike"], "SELECTED"), "selected": r["token"] == tok}
                        for r in s["rows"] if r["kind"] == rec["instrument_type"] and (r["strike"] in want or r["token"] == tok)]
    return {"expiries": snaps, "selected": sel, "comparison": cmp_rows,
            "labels": ["Hypotheses about the data, not facts; OI is open contracts, not buying",
                       "Depth = pending quantity in 5 visible levels, not a full book and not volume",
                       "IV: Black-76 on the same-expiry future from the mid of a fresh book; never from LTP"]}
