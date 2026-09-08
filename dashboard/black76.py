#!/usr/bin/env python3
"""
Black-76 — options on FUTURES (the correct model for MCX commodity options). Pure and
unit-testable. Reuses the normal CDF from option_chain; a future is a martingale under the
risk-neutral measure, so probabilities need no drift assumption.

Conventions: sigma is a DECIMAL here (0.30 = 30%); implied_vol() returns PERCENT for display
(matching option_chain._iv). T is in years.
"""

import math
from typing import Any, Dict, Optional

from dashboard.option_chain import _ncdf

RATE = 0.065   # India risk-free (approx) — only affects discounting in price/IV, not probability


def _d1d2(F: float, K: float, T: float, sigma: float):
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None, None
    v = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / v
    return d1, d1 - v


def price(F: float, K: float, T: float, sigma: float, is_call: bool, r: float = RATE) -> float:
    """Black-76 option price on a future F."""
    disc = math.exp(-r * T)
    if T <= 0 or sigma <= 0:
        return disc * max(0.0, (F - K) if is_call else (K - F))
    d1, d2 = _d1d2(F, K, T, sigma)
    if is_call:
        return disc * (F * _ncdf(d1) - K * _ncdf(d2))
    return disc * (K * _ncdf(-d2) - F * _ncdf(-d1))


def implied_vol(market_price: Optional[float], F: float, K: float, T: float,
                is_call: bool, r: float = RATE) -> Optional[float]:
    """Implied vol (PERCENT) via bisection, or None if the price is absent/below intrinsic."""
    if not market_price or market_price <= 0 or T <= 0 or F <= 0 or K <= 0:
        return None
    intrinsic = math.exp(-r * T) * max(0.0, (F - K) if is_call else (K - F))
    if market_price < intrinsic - 1e-6:
        return None                      # arbitrage / stale — can't imply a vol
    lo, hi, mid = 1e-4, 5.0, 0.5
    for _ in range(100):
        mid = (lo + hi) / 2
        p = price(F, K, T, mid, is_call, r)
        if abs(p - market_price) < max(1e-4, 1e-4 * market_price):
            break
        if p > market_price:
            hi = mid
        else:
            lo = mid
    return round(mid * 100.0, 2)


def prob_above(F: float, X: float, T: float, sigma: float) -> Optional[float]:
    """Risk-neutral P(F_T > X) for a martingale future: N([ln(F/X) − ½σ²T]/(σ√T))."""
    if F <= 0 or X <= 0 or T <= 0 or sigma <= 0:
        return None
    v = sigma * math.sqrt(T)
    d2 = (math.log(F / X) - 0.5 * sigma * sigma * T) / v
    return _ncdf(d2)


def prob_itm(F: float, K: float, T: float, sigma: float, is_call: bool) -> Optional[float]:
    p = prob_above(F, K, T, sigma)
    if p is None:
        return None
    return p if is_call else 1.0 - p


def expected_move(F: float, sigma: float, T: float) -> Optional[float]:
    """±1SD move of the future by expiry (points): F·σ·√T."""
    if not (F and sigma and T) or sigma <= 0 or T <= 0:
        return None
    return F * sigma * math.sqrt(T)


def greeks(F: float, K: float, T: float, sigma: float, is_call: bool, r: float = RATE) -> Dict[str, Any]:
    d1, d2 = _d1d2(F, K, T, sigma)
    if d1 is None:
        return {"delta": None, "gamma": None, "vega": None}
    disc = math.exp(-r * T)
    pdf = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    v = sigma * math.sqrt(T)
    delta = disc * (_ncdf(d1) if is_call else (_ncdf(d1) - 1.0))
    gamma = disc * pdf / (F * v)
    vega = disc * F * pdf * math.sqrt(T) / 100.0   # per 1 vol-point
    return {"delta": round(delta, 4), "gamma": round(gamma, 8), "vega": round(vega, 4)}
