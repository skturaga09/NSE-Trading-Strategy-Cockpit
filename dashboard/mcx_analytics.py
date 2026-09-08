#!/usr/bin/env python3
"""
MCX option analytics (C3) — Black-76 IV confidence bands, expected move, and probability,
with hard gates: a precise probability is NEVER published for a stale, absent, or one-sided
quote (it degrades to low/unavailable confidence with no point estimate).
"""

from datetime import date
from typing import Any, Dict, Optional

from dashboard import black76


def iv_band(F: float, K: float, T: float, is_call: bool,
            bid: Optional[float], ask: Optional[float], ltp: Optional[float]) -> Dict[str, Any]:
    """IV from bid/ask/mid/ltp with an explicit source + confidence. Two-sided → a real band."""
    two_sided = bool(bid and ask and ask >= bid)
    iv_bid = black76.implied_vol(bid, F, K, T, is_call) if bid else None
    iv_ask = black76.implied_vol(ask, F, K, T, is_call) if ask else None
    mid = (bid + ask) / 2 if two_sided else None
    iv_mid = black76.implied_vol(mid, F, K, T, is_call) if mid else None
    iv_ltp = black76.implied_vol(ltp, F, K, T, is_call) if ltp else None
    if two_sided and iv_bid and iv_ask:
        return {"iv_bid": iv_bid, "iv_ask": iv_ask, "iv_mid": iv_mid,
                "iv_source": "bid_ask", "iv_confidence": "high"}
    if iv_mid:
        return {"iv_bid": iv_bid, "iv_ask": iv_ask, "iv_mid": iv_mid,
                "iv_source": "mid", "iv_confidence": "medium"}
    if iv_ltp:
        return {"iv_bid": None, "iv_ask": None, "iv_mid": iv_ltp,
                "iv_source": "ltp", "iv_confidence": "low"}
    return {"iv_bid": None, "iv_ask": None, "iv_mid": None,
            "iv_source": "unavailable", "iv_confidence": "unavailable"}


def _band_probs(fn, band: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Map a two-sided IV band to a probability range (min/max of the two IV endpoints).
    Returns None,None unless the band is two-sided (iv_confidence high) — no false precision."""
    if band["iv_confidence"] != "high" or not (band["iv_bid"] and band["iv_ask"]):
        return {"low": None, "high": None}
    ps = [fn(band["iv_bid"] / 100.0), fn(band["iv_ask"] / 100.0)]
    ps = [p for p in ps if p is not None]
    if not ps:
        return {"low": None, "high": None}
    return {"low": round(min(ps) * 100, 1), "high": round(max(ps) * 100, 1)}


def option_analytics(F: Optional[float], K: float, opt_expiry: date, is_call: bool,
                     bid: Optional[float], ask: Optional[float], ltp: Optional[float],
                     lot_size: Optional[int], entry_premium: Optional[float] = None,
                     today: Optional[date] = None) -> Dict[str, Any]:
    """Full Black-76 analytics for one option leg/position. Probabilities are published only
    when the quote is two-sided (else None + low/unavailable confidence)."""
    today = today or date.today()
    T = max((opt_expiry - today).days, 0) / 365.0
    out: Dict[str, Any] = {"model": "black76", "future_price": F, "strike": K,
                           "days_to_expiry": (opt_expiry - today).days, "T_years": round(T, 4),
                           "assumptions": ["Black-76 on the future", "option expiry for T",
                                           "future is a martingale (no drift)"]}
    if not F or T <= 0:
        out.update({"iv_source": "unavailable", "iv_confidence": "unavailable",
                    "note": "no future price or expired — analytics suppressed"})
        return out
    band = iv_band(F, K, T, is_call, bid, ask, ltp)
    out.update(band)
    sigma = (band["iv_mid"] / 100.0) if band["iv_mid"] else None
    em = black76.expected_move(F, sigma, T) if sigma else None
    if em is not None:
        out["expected_move_pts"] = round(em, 2)
        out["expected_move_pct"] = round(em / F * 100, 2)
        out["expected_range"] = [round(F - em, 2), round(F + em, 2)]
        out["expected_move_rupees_per_lot"] = round(em * lot_size, 0) if lot_size else None
    # P(ITM) and P(profit) — ONLY as a band from a two-sided quote
    out["p_itm"] = _band_probs(lambda s: black76.prob_itm(F, K, T, s, is_call), band)
    if entry_premium is not None:
        be = (K + entry_premium) if is_call else (K - entry_premium)
        out["breakeven"] = round(be, 2)
        out["p_profit"] = _band_probs(
            lambda s: (black76.prob_above(F, be, T, s) if is_call else
                       (1.0 - black76.prob_above(F, be, T, s)) if black76.prob_above(F, be, T, s) is not None else None),
            band)
    if band["iv_confidence"] in ("low", "unavailable"):
        out["note"] = "quote one-sided/stale — probabilities suppressed (low-confidence model output only)"
    return out
