"""Phase 7 cost model: Zerodha NSE F&O charges from versioned config, and slippage from the book at decision time.

Pure: inputs are explicit (config, prices, quantity, trade date, book levels); no clock, disk or network.

Charges: config `costs.entries` (product FUT|OPT, component, side, rate / cap_inr / flat_inr, effective_from, verified,
fact = docs/verified-facts.md ID). The entry in force is the latest effective_from <= trade date. A component with no
entry in force, or an entry with verified: false, makes the estimate UNVERIFIED with the component named. The
backtest-expert model (`skills/backtest-expert/scripts/evaluate_backtest.calculate_india_costs`) is NOT reused: its
F&O STT (0.0125 %) and options exchange rate (0.05 %) disagree with the verified current rates (F-COST-2/3).
Exercise STT is not modelled: V1 candidates are exited before expiry. Rupee amounts are not rounded (contract-note
rounding is uncalibrated).

Slippage: walk the executable side of the 5-level book for the order quantity. Depth is PENDING orders at 5 levels only,
not a full order book and not executed volume (F-QUOTE-7, F-WS-5). Without depth: costs.slippage.no_depth_spread_multiple
x the full spread per side, labelled ESTIMATED.
"""

from dataclasses import dataclass

from .config import REPO, ConfigError, load_config

DEFAULT_CONFIG = REPO / "config" / "engine" / "v9.yaml"
COMPONENTS = ("brokerage", "stt", "exchange", "sebi", "stamp", "ipft", "gst")
VERIFIED, UNVERIFIED = "VERIFIED", "UNVERIFIED"
DEPTH, ESTIMATED = "DEPTH_5_LEVELS", "ESTIMATED_SPREAD_MULTIPLE"


def require(cfg, keys, path):
    for key in keys:
        try:
            v = cfg.get(key)
        except (KeyError, TypeError):
            v = None
        if v is None or v == "":
            raise ConfigError(f"config {path}: required key '{key}' is missing or empty")
    return cfg


REQUIRED = ["costs.schedule_version", "costs.gst_on", "costs.entries", "costs.slippage.no_depth_spread_multiple"]


def load(path=DEFAULT_CONFIG):
    return require(load_config(path), REQUIRED, path)


@dataclass(frozen=True)
class CostEstimate:
    total_inr: float
    breakdown: tuple            # ((leg BUY|SELL, component, inr), ...)
    status: str                 # VERIFIED | UNVERIFIED
    unverified: tuple           # why, per component
    schedule_version: str


def _in_force(entries, product: str, component: str, day):
    hits = [e for e in entries if e["product"] == product and e["component"] == component and e["effective_from"] <= day]
    return max(hits, key=lambda e: e["effective_from"]) if hits else None


def leg_costs(cfg, product: str, side: str, price_inr: float, qty: int, day) -> tuple[dict, list]:
    """One executed order (one leg). -> ({component: inr}, [unverified reasons])."""
    entries, out, bad = cfg.get("costs.entries"), {}, []
    for comp in COMPONENTS:
        e = _in_force(entries, product, comp, day)
        if e is None:
            bad.append(f"{comp}: no {product} rate in force on {day}")
            continue
        if not e["verified"]:
            bad.append(f"{comp}: {product} rate not verified ({e['fact']})")
        if e["side"] not in ("BOTH", side):
            out[comp] = 0.0
        elif comp == "gst":
            out[comp] = e["rate"] * sum(out.get(c, 0.0) for c in cfg.get("costs.gst_on"))
        elif "flat_inr" in e:
            out[comp] = float(e["flat_inr"])
        else:
            v = price_inr * qty * e["rate"]
            out[comp] = min(v, e["cap_inr"]) if "cap_inr" in e else v
    return out, bad


def round_trip(cfg, product: str, position_side: str, entry_inr: float, exit_inr: float, qty: int, day) -> CostEstimate:
    """Entry leg on `position_side` (BUY for a long), exit leg on the other side, both on `day`."""
    exit_side = "SELL" if position_side == "BUY" else "BUY"
    rows, bad = [], []
    for side, px in ((position_side, entry_inr), (exit_side, exit_inr)):
        comps, why = leg_costs(cfg, product, side, px, qty, day)
        rows += [(side, c, v) for c, v in comps.items()]
        bad += [f"{side} {w}" for w in why]
    return CostEstimate(sum(v for _, _, v in rows), tuple(rows), UNVERIFIED if bad else VERIFIED, tuple(bad),
                        cfg.get("costs.schedule_version"))


@dataclass(frozen=True)
class Fill:
    side: str                   # BUY walks the asks, SELL walks the bids
    qty: int
    avg_price: float | None     # paise per unit; None = the visible levels do not hold qty
    mid: float
    half_spread: float          # paise per unit
    impact: float | None        # avg_price beyond the touch, paise per unit
    per_unit: float | None      # half_spread + impact: cost vs mid, paise per unit
    method: str                 # DEPTH_5_LEVELS | ESTIMATED_SPREAD_MULTIPLE
    covered: bool | None        # None = unknown (no depth)


def fill(bids, asks, depth: bool, side: str, qty: int, cfg) -> Fill:
    """bids/asks: ((price_paise, qty, orders), ...) best first; depth False = only the touch is known."""
    bid, ask = bids[0][0], asks[0][0]
    mid, sign = (bid + ask) / 2, 1 if side == "BUY" else -1
    touch, half = (ask if side == "BUY" else bid), (ask - bid) / 2
    if not depth:
        per = cfg.get("costs.slippage.no_depth_spread_multiple") * (ask - bid)
        return Fill(side, qty, mid + sign * per, mid, half, per - half, per, ESTIMATED, None)
    left, paid = qty, 0
    for price, q, _ in (asks if side == "BUY" else bids):
        take = min(q, left)
        paid, left = paid + take * price, left - take
        if not left:
            break
    if left:
        return Fill(side, qty, None, mid, half, None, None, DEPTH, False)
    avg = paid / qty
    impact = sign * (avg - touch)
    return Fill(side, qty, avg, mid, half, impact, half + impact, DEPTH, True)
