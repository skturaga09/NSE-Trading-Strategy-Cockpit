#!/usr/bin/env python3
"""
Commodity setup radar (C6a) — MCX idea generation. Direction from PRICE STRUCTURE (trend +
breakout) on the front future; events are a GATE, never a forecast. Observation / review only
— never an auto or blind buy/sell. Gated by the existing data / liquidity / roll / event
safety layer; a firing setup only becomes ELIGIBLE_FOR_REVIEW when it also passes those.

C6a scope: the INTRADAY evening lane (default 15-min) — where crude/natgas event-momentum
lives during the US overlap — with trend + breakout detectors and an ATM option leg. Pullback
detector, the daily lane, and edge-validation are later phases (see docs/mcx-setup-radar-spec.md).
Detectors are pure over an OHLC list so they are unit-testable and backtestable.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from dashboard import structure_exit  # _atr / last_confirmed_pivot reused


def _ema(vals: List[float], n: int) -> Optional[float]:
    if len(vals) < n:
        return None
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def trend_signal(candles: List[List[Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """EMA(fast) vs EMA(slow) alignment + price side. Direction LONG/SHORT/NONE + strength."""
    fast, slow = int(cfg.get("mcx_setup_ema_fast", 9)), int(cfg.get("mcx_setup_ema_slow", 20))
    closes = [c[4] for c in candles]
    ef, es = _ema(closes, fast), _ema(closes, slow)
    atr = structure_exit._atr(candles)
    if ef is None or es is None or not atr:
        return {"direction": "NONE", "kind": "trend", "strength": 0.0}
    price = closes[-1]
    if price > ef > es:
        d = "LONG"
    elif price < ef < es:
        d = "SHORT"
    else:
        return {"direction": "NONE", "kind": "trend", "strength": 0.0}
    strength = max(0.0, min(1.0, abs(ef - es) / atr))
    return {"direction": d, "kind": "trend", "strength": round(strength, 3),
            "ema_fast": round(ef, 2), "ema_slow": round(es, 2)}


def breakout_signal(candles: List[List[Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Close beyond the last confirmed structure pivot WITH range/ATR expansion + volume.
    Direction = breakout side. The commodity analogue of the equity ignition radar."""
    k = int(cfg.get("structure_pivot_k", 2))
    atr = structure_exit._atr(candles)
    if len(candles) < 2 * k + 3 or not atr:
        return {"direction": "NONE", "kind": "breakout", "strength": 0.0}
    last = candles[-1]
    close, hi, lo, vol = last[4], last[2], last[3], (last[5] if len(last) > 5 else 0)
    rng_mult = float(cfg.get("mcx_setup_breakout_atr_mult", 1.0))
    vmult = float(cfg.get("mcx_setup_volume_mult", 1.3))
    vols = [c[5] for c in candles[:-1] if len(c) > 5 and c[5]]
    avgv = (sum(vols[-20:]) / len(vols[-20:])) if vols else 0
    expansion = (hi - lo) / atr
    vol_ok = (not avgv) or vol >= vmult * avgv     # if no volume data, don't block on it
    piv_hi = structure_exit.last_confirmed_pivot(candles, k, "high")
    piv_lo = structure_exit.last_confirmed_pivot(candles, k, "low")
    if piv_hi is not None and close > piv_hi and expansion >= rng_mult and vol_ok:
        return {"direction": "LONG", "kind": "breakout", "level": round(piv_hi, 2),
                "strength": round(min(1.0, expansion / (2 * rng_mult)), 3)}
    if piv_lo is not None and close < piv_lo and expansion >= rng_mult and vol_ok:
        return {"direction": "SHORT", "kind": "breakout", "level": round(piv_lo, 2),
                "strength": round(min(1.0, expansion / (2 * rng_mult)), 3)}
    return {"direction": "NONE", "kind": "breakout", "strength": 0.0}


_ALIGN = {"high": 1.0, "mixed": 0.5, "low": 0.0, "unavailable": 0.5}


def evaluate_setup(candles: List[List[Any]], cfg: Dict[str, Any],
                   alignment: str = "unavailable") -> Dict[str, Any]:
    """Combine detectors → {direction, kind, score, components}. Conflicting detectors → NONE.
    Score is a SCREEN RANK (0..100), not a probability or an edge."""
    t = trend_signal(candles, cfg)
    b = breakout_signal(candles, cfg)
    firing = [s for s in (t, b) if s["direction"] != "NONE"]
    if not firing:
        return {"direction": "NONE", "kind": None, "score": 0, "trend": t, "breakout": b}
    dirs = {s["direction"] for s in firing}
    if len(dirs) > 1:                       # trend vs breakout disagree → stand aside
        return {"direction": "NONE", "kind": "conflict", "score": 0, "trend": t, "breakout": b}
    direction = firing[0]["direction"]
    kind = "+".join(s["kind"] for s in firing)
    # volume component from the breakout bar
    vols = [c[5] for c in candles[:-1] if len(c) > 5 and c[5]]
    avgv = (sum(vols[-20:]) / len(vols[-20:])) if vols else 0
    vlast = candles[-1][5] if len(candles[-1]) > 5 else 0
    vol_norm = min(1.0, (vlast / avgv) / 2.0) if avgv else 0.0
    w_trend, w_break, w_vol, w_ctx = 0.35, 0.35, 0.15, 0.15
    score = 100.0 * (
        w_trend * (t["strength"] if t["direction"] == direction else 0.0) +
        w_break * (b["strength"] if b["direction"] == direction else 0.0) +
        w_vol * vol_norm +
        w_ctx * _ALIGN.get(alignment, 0.5)
    )
    return {"direction": direction, "kind": kind, "score": round(score, 1),
            "trend": t, "breakout": b, "components": {"vol_norm": round(vol_norm, 3), "alignment": alignment}}


# ---------------------------------------------------------------------------
# Live radar
# ---------------------------------------------------------------------------
def _trade_state(setup: Dict[str, Any], liq_grade: str, roll: str, data_conf: str,
                 event_guarded: bool, min_score: float, min_grade: str) -> Dict[str, str]:
    grade_rank = {"A": 3, "B": 2, "C": 1, "D": 0, "UNKNOWN": 0}
    if data_conf == "low":
        return {"state": "STALE_DATA", "why": "intraday quote stale/unavailable"}
    if roll in ("expiry_risk", "contract_dislocated"):
        return {"state": "ROLL_GUARD", "why": f"front future in {roll}"}
    if setup["direction"] == "NONE":
        return {"state": "WATCH", "why": "no trend/breakout setup firing" if setup.get("kind") != "conflict" else "trend & breakout disagree"}
    if grade_rank.get(liq_grade, 0) < grade_rank.get(min_grade, 2):
        return {"state": "ILLIQUID", "why": f"option liquidity {liq_grade} < {min_grade}"}
    if event_guarded:
        return {"state": "EVENT_GUARD", "why": "high-severity event within the guard window — new entries flagged"}
    if setup["score"] < min_score:
        return {"state": "WATCH", "why": f"setup score {setup['score']} < {min_score}"}
    return {"state": "ELIGIBLE_FOR_REVIEW", "why": f"{setup['kind']} {setup['direction']} · score {setup['score']} — review & size, not a signal"}


def setups(roots: Optional[List[str]] = None) -> Dict[str, Any]:
    from dashboard import mcx, mcx_config, mcx_context, mcx_events, mcx_analytics
    cfg = {**mcx_config.get(), "structure_pivot_k": 2}
    if not cfg.get("mcx_setups_enabled", True):
        return {**mcx.envelope(mcx.market_state(), {}), "rows": [], "note": "setups disabled"}
    roots = roots or cfg.get("mcx_watchlist_default", mcx.MCX_LIQUID_ROOTS)
    interval = cfg.get("mcx_setup_intraday_interval", "15minute")
    min_score = float(cfg.get("mcx_setup_min_score", 55))
    min_grade = cfg.get("mcx_setup_min_liquidity_grade", "B")
    rows_master = mcx.instruments()
    mkt = mcx.market_state()
    out: List[Dict[str, Any]] = []
    for root in roots:
        row: Dict[str, Any] = {"root": root.upper(), "economic_root": mcx.economic_root(root)}
        try:
            fn = mcx.front_next_future(root, rows_master)
            front = fn["front"]
            if not front:
                row["trade_state"] = {"state": "NO_DATA", "why": "no live MCX future"}; out.append(row); continue
            row["future"] = front["tradingsymbol"]
            if mkt != "OPEN":
                row["trade_state"] = {"state": "MARKET_CLOSED", "why": "MCX not in session (intraday lane needs live bars)"}
                out.append(row); continue
            candles = structure_exit.fetch_intraday(front["token"], interval)
            if not candles or len(candles) < 24:
                row["trade_state"] = {"state": "NO_DATA", "why": "insufficient intraday candles"}; out.append(row); continue
            align = mcx_context.mcx_global_attribution(root).get("alignment", "unavailable")
            setup = evaluate_setup(candles, cfg, align)
            row.update({"direction": setup["direction"], "kind": setup["kind"], "score": setup["score"],
                        "interval": interval, "last": candles[-1][4]})
            # gates
            roll = mcx.roll_state(root, mcx.quote([front["tradingsymbol"]]), rows_master).roll_state
            fq = mcx.quote([front["tradingsymbol"]]).get(f"MCX:{front['tradingsymbol']}") or {}
            fprice = fq.get("last_price")
            data_conf = "low" if not fprice else "high"
            # ATM option leg (CE for LONG, PE for SHORT)
            liq_grade = "UNKNOWN"
            if setup["direction"] in ("LONG", "SHORT") and fprice:
                is_call = setup["direction"] == "LONG"
                opts = [o for o in mcx._opts(rows_master) if o["name"] == root.upper()
                        and o["instrument_type"] == ("CE" if is_call else "PE")
                        and o["expiry"] and o["expiry"] >= date.today()]
                if opts:
                    exp0 = min(o["expiry"] for o in opts)
                    atm = min([o for o in opts if o["expiry"] == exp0], key=lambda o: abs((o["strike"] or 0) - fprice))
                    oq = mcx.quote([atm["tradingsymbol"]]).get(f"MCX:{atm['tradingsymbol']}") or {}
                    depth = oq.get("depth") or {}
                    bid = (depth.get("buy") or [{}])[0].get("price"); ask = (depth.get("sell") or [{}])[0].get("price")
                    mx = cfg.get("mcx_max_option_spread_pct", {}).get(root.upper(), 8.0)
                    liq = mcx.liquidity_grade(bid, ask, oq.get("last_price"), oi=oq.get("oi"), volume=oq.get("volume"), max_spread_pct=mx)
                    liq_grade = liq["grade"]
                    an = mcx_analytics.option_analytics(fprice, atm["strike"], exp0, is_call, bid, ask, oq.get("last_price"), atm["lot_size"])
                    row["option_leg"] = {"side": "CE" if is_call else "PE", "strike": atm["strike"], "expiry": exp0.isoformat(),
                                         "liquidity": liq, "iv_mid": an.get("iv_mid"), "iv_confidence": an.get("iv_confidence"),
                                         "expected_move_pct": an.get("expected_move_pct"), "p_itm": an.get("p_itm")}
            eg = mcx_events.new_entry_blocked(mcx.economic_root(root)).get("blocked", False)
            row["event_guarded"] = eg
            row["roll"] = roll
            row["trade_state"] = _trade_state(setup, liq_grade, roll, data_conf, eg, min_score, min_grade)
        except Exception as e:
            row["trade_state"] = {"state": "NO_DATA", "why": f"error: {e}"}
        out.append(row)
    out.sort(key=lambda r: r.get("score", 0), reverse=True)
    return {**mcx.envelope(mkt, {}), "rows": out,
            "note": "screen, not an edge — direction is a technical read, not an event forecast; review & size yourself"}
