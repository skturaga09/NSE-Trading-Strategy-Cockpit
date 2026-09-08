#!/usr/bin/env python3
"""
MCX commodities plumbing — instrument master, contract-aware option→future mapping,
roll state, quotes, liquidity + data-quality grading. Isolated from the NSE/NFO boards;
everything here routes on exchange == "MCX".

Design notes:
  - The Kite MCX instrument master is authoritative for token/symbol/root/strike/type/
    expiry/lot/tick. Settlement / devolvement / tender semantics are NOT in the master —
    those live in the verified contract-profile registry (mcx_contract_profiles.py).
  - Pure functions take an optional instrument list so mapping/roll logic is unit-testable
    from fixtures with no network.
  - MCX options are options on the commodity FUTURE. The option's own expiry drives T; the
    linked future's expiry is stored separately (roll / tender / devolvement awareness).
  - Main vs mini are SEPARATE tradable instruments under a shared economic root — never
    project one's lot/tick/premium/liquidity onto the other.
"""

import csv
import io
import threading
import time as _time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import requests

from dashboard import app as core

# --- Universe (config can widen this later) ---
MCX_LIQUID_ROOTS = ["CRUDEOIL", "NATURALGAS", "GOLD", "SILVER"]
MCX_SUPPORTED_ROOTS = [
    "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM",
    "SILVER", "SILVERM", "COPPER", "ZINC", "LEAD", "ALUMINIUM", "NICKEL",
]

# tradable_root -> economic_root. Only explicit entries alias; unknown roots map to themselves.
MCX_ROOT_ALIASES = {
    "ALUMINI": "ALUMINIUM", "ALUMINIUM": "ALUMINIUM",
    "ZINC": "ZINC", "ZINCMINI": "ZINC",
    "LEAD": "LEAD", "LEADMINI": "LEAD",
    "NATURALGAS": "NATURALGAS", "NATGASMINI": "NATURALGAS",
    "CRUDEOIL": "CRUDEOIL", "CRUDEOILM": "CRUDEOIL",
    "GOLD": "GOLD", "GOLDM": "GOLD", "GOLDGUINEA": "GOLD", "GOLDPETAL": "GOLD", "GOLDTEN": "GOLD",
    "SILVER": "SILVER", "SILVERM": "SILVER", "SILVERMIC": "SILVER", "SILVER100": "SILVER",
}

_INSTR: Dict[str, Any] = {"ts": 0.0, "rows": None}
_LOCK = threading.Lock()
_QUOTE_CACHE: Dict[str, Any] = {}


def economic_root(tradable_root: str) -> str:
    r = (tradable_root or "").upper()
    return MCX_ROOT_ALIASES.get(r, r)


def _cfg() -> Dict[str, Any]:
    """MCX config block (isolated). Falls back to safe defaults if not configured."""
    try:
        from dashboard import mcx_config
        return mcx_config.get()
    except Exception:
        return {"mcx_instrument_master_ttl_seconds": 21600,
                "mcx_quote_stale_seconds": {"future": 10, "option": 30, "context": 900}}


def _headers() -> Dict[str, str]:
    from dashboard.option_chain import ensure_fresh_config
    ensure_fresh_config()
    kc = core.KITE_CONFIG
    return {"Authorization": f"token {kc.get('api_key','')}:{kc.get('access_token','')}",
            "X-Kite-Version": "3"}


def _parse_row(r: Dict[str, str]) -> Dict[str, Any]:
    """Normalize a raw Kite MCX master row (all strings) into typed fields."""
    def num(v, cast=float):
        try:
            return cast(float(v))
        except Exception:
            return None
    exp = None
    if r.get("expiry"):
        try:
            exp = datetime.strptime(r["expiry"][:10], "%Y-%m-%d").date()
        except Exception:
            exp = None
    return {
        "token": num(r.get("instrument_token"), int),
        "tradingsymbol": r.get("tradingsymbol"),
        "name": (r.get("name") or "").upper(),
        "segment": r.get("segment"),
        "exchange": r.get("exchange"),
        "instrument_type": r.get("instrument_type"),   # FUT | CE | PE
        "strike": num(r.get("strike")),
        "expiry": exp,
        "lot_size": num(r.get("lot_size"), int),
        "tick_size": num(r.get("tick_size")),
    }


def instruments(force: bool = False) -> List[Dict[str, Any]]:
    """Cached, parsed MCX instrument master. TTL from config (default 6h). Never raises —
    returns [] on failure (callers degrade to a controlled error state)."""
    ttl = float(_cfg().get("mcx_instrument_master_ttl_seconds", 21600))
    with _LOCK:
        if not force and _INSTR["rows"] is not None and (_time.time() - _INSTR["ts"]) < ttl:
            return _INSTR["rows"]
    try:
        r = requests.get("https://api.kite.trade/instruments/MCX", headers=_headers(), timeout=30)
        raw = list(csv.DictReader(io.StringIO(r.text)))
        rows = [_parse_row(x) for x in raw if x.get("segment", "").startswith("MCX")]
    except Exception:
        rows = _INSTR["rows"] or []      # keep the last good master on a fetch error
    with _LOCK:
        if rows:
            _INSTR.update({"ts": _time.time(), "rows": rows})
    return rows


def _futs(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    rows = rows if rows is not None else instruments()
    return [x for x in rows if x["segment"] == "MCX-FUT" and x["expiry"]]


def _opts(rows: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    rows = rows if rows is not None else instruments()
    return [x for x in rows if x["segment"] == "MCX-OPT" and x["expiry"] and x["instrument_type"] in ("CE", "PE")]


def futures_map(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """tradable_root -> its futures, sorted by expiry ascending."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for f in _futs(rows):
        out.setdefault(f["name"], []).append(f)
    for k in out:
        out[k].sort(key=lambda x: x["expiry"])
    return out


def front_next_future(root: str, rows: Optional[List[Dict[str, Any]]] = None,
                      today: Optional[date] = None) -> Dict[str, Optional[Dict[str, Any]]]:
    """The front (nearest non-expired) and next future for a tradable root."""
    today = today or date.today()
    fs = [f for f in futures_map(rows).get((root or "").upper(), []) if f["expiry"] >= today]
    return {"front": fs[0] if fs else None, "next": fs[1] if len(fs) > 1 else None}


# ---------------------------------------------------------------------------
# Contract-aware option → future mapping (auditable)
# ---------------------------------------------------------------------------
@dataclass
class McxContractLink:
    option_token: Optional[int]
    option_symbol: Optional[str]
    option_root: str
    option_expiry: Optional[str]                 # ISO date str (JSON-friendly)
    underlying_future_token: Optional[int]
    underlying_future_symbol: Optional[str]
    underlying_future_root: Optional[str]
    underlying_future_expiry: Optional[str]
    economic_root: str
    mapping_method: str                          # explicit_metadata | contract_profile | validated_fallback
    mapping_confidence: str                      # high | medium | low
    validated_at: str
    days_option_to_future_expiry: Optional[int]
    contract_status: Literal["tradable", "near_expiry", "expired", "illiquid", "mapping_uncertain"]
    warnings: List[str]


def option_underlying_future(root: str, option_expiry: date,
                             rows: Optional[List[Dict[str, Any]]] = None,
                             today: Optional[date] = None) -> Dict[str, Any]:
    """Resolve the future backing an option: same tradable root, nearest future expiry ON OR
    AFTER the option expiry. Returns {status, future, mapping_method, mapping_confidence,
    warnings}. Never silently guesses — an invalid ordering or missing future is an explicit
    error status. (Fallback rule; explicit exchange metadata would override when available.)"""
    root = (root or "").upper()
    today = today or date.today()
    warnings: List[str] = []
    fs = futures_map(rows).get(root, [])
    if not fs:
        return {"status": "mapping_uncertain", "future": None, "mapping_method": "validated_fallback",
                "mapping_confidence": "low", "warnings": [f"no MCX future found for root {root}"]}
    # nearest future whose expiry is >= the option's (the future must outlive the option)
    eligible = [f for f in fs if f["expiry"] >= option_expiry]
    if not eligible:
        return {"status": "mapping_uncertain", "future": None, "mapping_method": "validated_fallback",
                "mapping_confidence": "low",
                "warnings": [f"every {root} future expires BEFORE the option expiry {option_expiry} — invalid ordering"]}
    fut = eligible[0]
    gap = (fut["expiry"] - option_expiry).days
    if gap > 45:
        warnings.append(f"nearest future is {gap}d after the option — unusually wide, verify the linkage")
    return {"status": "ok", "future": fut, "mapping_method": "validated_fallback",
            "mapping_confidence": "medium", "warnings": warnings}


def contract_link(option: Dict[str, Any], rows: Optional[List[Dict[str, Any]]] = None,
                  today: Optional[date] = None) -> McxContractLink:
    """Build an auditable option→future link from a parsed option instrument row."""
    today = today or date.today()
    root = (option.get("name") or "").upper()
    opt_exp = option.get("expiry")
    res = option_underlying_future(root, opt_exp, rows, today) if opt_exp else \
        {"status": "mapping_uncertain", "future": None, "mapping_method": "validated_fallback",
         "mapping_confidence": "low", "warnings": ["option has no expiry"]}
    fut = res["future"]
    days = (fut["expiry"] - opt_exp).days if (fut and opt_exp) else None
    if res["status"] != "ok":
        status = "mapping_uncertain"
    elif opt_exp and opt_exp < today:
        status = "expired"
    elif opt_exp and (opt_exp - today).days <= 1:
        status = "near_expiry"
    else:
        status = "tradable"
    return McxContractLink(
        option_token=option.get("token"), option_symbol=option.get("tradingsymbol"),
        option_root=root, option_expiry=opt_exp.isoformat() if opt_exp else None,
        underlying_future_token=fut["token"] if fut else None,
        underlying_future_symbol=fut["tradingsymbol"] if fut else None,
        underlying_future_root=fut["name"] if fut else None,
        underlying_future_expiry=fut["expiry"].isoformat() if fut else None,
        economic_root=economic_root(root),
        mapping_method=res["mapping_method"], mapping_confidence=res["mapping_confidence"],
        validated_at=datetime.now(timezone.utc).isoformat(),
        days_option_to_future_expiry=days, contract_status=status, warnings=res["warnings"],
    )


# ---------------------------------------------------------------------------
# Roll state
# ---------------------------------------------------------------------------
@dataclass
class McxRollState:
    root: str
    active_future_symbol: Optional[str]
    active_future_token: Optional[int]
    next_future_symbol: Optional[str]
    next_future_token: Optional[int]
    front_expiry_days: Optional[int]
    front_volume: Optional[float]
    next_volume: Optional[float]
    front_oi: Optional[float]
    next_oi: Optional[float]
    volume_ratio_next_to_front: Optional[float]
    oi_ratio_next_to_front: Optional[float]
    spread_front_next: Optional[float]
    roll_state: Literal["front_liquid", "transition", "next_dominant", "expiry_risk", "contract_dislocated", "unknown"]
    recommended_analysis_contract: Optional[str]
    recommended_execution_contract: Optional[str]


def roll_state(root: str, quotes: Optional[Dict[str, Any]] = None,
               rows: Optional[List[Dict[str, Any]]] = None, today: Optional[date] = None) -> McxRollState:
    """Front/next roll state. Volume/OI come from live quotes when available; without them the
    state is derived from days-to-expiry only and marked accordingly."""
    today = today or date.today()
    fn = front_next_future(root, rows, today)
    front, nxt = fn["front"], fn["next"]
    def q(f):
        if not f or not quotes:
            return (None, None)
        d = quotes.get(f"MCX:{f['tradingsymbol']}") or {}
        return (d.get("volume"), d.get("oi"))
    fv, foi = q(front); nv, noi = q(nxt)
    dte = (front["expiry"] - today).days if front else None
    vr = (nv / fv) if (fv and nv) else None
    orr = (noi / foi) if (foi and noi) else None
    if front is None:
        state = "unknown"
    elif dte is not None and dte <= 2:
        state = "expiry_risk"
    elif (vr and vr > 1.0) or (orr and orr > 1.0):
        state = "next_dominant"
    elif (vr and vr > 0.5) or (orr and orr > 0.5) or (dte is not None and dte <= 7):
        state = "transition"
    elif fv is None and foi is None:
        state = "unknown"
    else:
        state = "front_liquid"
    exec_contract = (nxt or front)["tradingsymbol"] if (state == "next_dominant" and nxt) else (front["tradingsymbol"] if front else None)
    return McxRollState(
        root=(root or "").upper(), active_future_symbol=front["tradingsymbol"] if front else None,
        active_future_token=front["token"] if front else None,
        next_future_symbol=nxt["tradingsymbol"] if nxt else None,
        next_future_token=nxt["token"] if nxt else None,
        front_expiry_days=dte, front_volume=fv, next_volume=nv, front_oi=foi, next_oi=noi,
        volume_ratio_next_to_front=round(vr, 2) if vr else None,
        oi_ratio_next_to_front=round(orr, 2) if orr else None, spread_front_next=None,
        roll_state=state,
        recommended_analysis_contract=front["tradingsymbol"] if front else None,
        recommended_execution_contract=exec_contract,
    )


# ---------------------------------------------------------------------------
# Liquidity + data-quality
# ---------------------------------------------------------------------------
def liquidity_grade(bid: Optional[float], ask: Optional[float], ltp: Optional[float],
                    bid_qty: Optional[float] = None, ask_qty: Optional[float] = None,
                    oi: Optional[float] = None, volume: Optional[float] = None,
                    max_spread_pct: float = 8.0) -> Dict[str, Any]:
    """Grade A/B/C/D/UNKNOWN from a single leg's book. grade_confidence flags missing depth/OI."""
    if not bid and not ask:
        return {"grade": "D", "grade_confidence": "high", "spread_pct": None,
                "reason": "no two-sided quote (one-sided or absent)"}
    if not (bid and ask):
        return {"grade": "D", "grade_confidence": "medium", "spread_pct": None,
                "reason": "one-sided quote"}
    mid = (bid + ask) / 2.0
    spread_pct = round((ask - bid) / mid * 100.0, 2) if mid else None
    depth_known = (bid_qty is not None) or (ask_qty is not None) or (oi is not None) or (volume is not None)
    conf = "high" if depth_known else "low"
    if spread_pct is None:
        grade = "UNKNOWN"; reason = "cannot compute spread"
    elif spread_pct <= max_spread_pct * 0.5:
        grade, reason = "A", "tight two-sided spread"
    elif spread_pct <= max_spread_pct:
        grade, reason = "B", "tradable, spread within limit"
    elif spread_pct <= max_spread_pct * 2:
        grade, reason = "C", "wide spread — insight only, not entry-eligible"
    else:
        grade, reason = "D", "spread too wide to execute"
    if grade in ("A", "B") and not depth_known:
        grade = "B" if grade == "A" else grade  # can't certify A without depth
        reason += "; depth/OI absent → capped confidence"
    return {"grade": grade, "grade_confidence": conf, "spread_pct": spread_pct, "reason": reason}


def _source_state(age_seconds: Optional[float], stale_after: float) -> str:
    if age_seconds is None:
        return "unavailable"
    if age_seconds <= stale_after:
        return "fresh"
    if age_seconds <= stale_after * 4:
        return "delayed"
    return "stale"


def data_quality(sources: Dict[str, Dict[str, Any]], warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build the standard data-quality envelope from per-source {age_seconds, stale_after, ts}."""
    out_sources = {}
    worst = "high"
    order = {"high": 0, "medium": 1, "low": 2}
    for name, s in sources.items():
        st = _source_state(s.get("age_seconds"), s.get("stale_after", 30))
        out_sources[name] = {"status": st, "age_seconds": s.get("age_seconds"),
                             "timestamp": s.get("ts")}
        lvl = {"fresh": "high", "delayed": "medium", "stale": "low", "unavailable": "low"}[st]
        if order[lvl] > order[worst]:
            worst = lvl
    return {"overall_confidence": worst, "warnings": warnings or [], "sources": out_sources}


def envelope(market_state: str, sources: Dict[str, Dict[str, Any]],
             warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    """Top-level response envelope every MCX endpoint returns."""
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "market_state": market_state,
        "data_quality": data_quality(sources, warnings),
    }


def market_state() -> str:
    try:
        s = core.ZerodhaPlumbingInspector.market_session(exchange="MCX")
        return {"OPEN": "OPEN", "WEEKEND": "CLOSED", "CLOSED": "CLOSED",
                "PRE_MARKET": "PREOPEN"}.get(s.get("session"), "UNKNOWN")
    except Exception:
        return "UNKNOWN"


# ---------------------------------------------------------------------------
# Live quotes + ATR (daily-cached) + watchlist / basic chain
# ---------------------------------------------------------------------------
_DAILY: Dict[int, Any] = {}    # token -> (date_iso, candles)  (ATR source, refreshed once/day)


def quote(symbols: List[str]) -> Dict[str, Any]:
    """Batch MCX /quote. `symbols` are bare tradingsymbols; keyed back as 'MCX:<sym>'."""
    if not symbols:
        return {}
    out: Dict[str, Any] = {}
    for i in range(0, len(symbols), 200):
        grp = [f"MCX:{s}" for s in symbols[i:i + 200]]
        try:
            j = requests.get("https://api.kite.trade/quote", params=[("i", s) for s in grp],
                             headers=_headers(), timeout=10).json()
            if j.get("status") == "success":
                out.update(j["data"])
        except Exception:
            pass
    return out


def _quote_age(d: Dict[str, Any]) -> Optional[float]:
    lt = d.get("last_trade_time") or d.get("timestamp")
    if not lt:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            t = datetime.strptime(lt, fmt)
            if t.tzinfo is None:
                from zoneinfo import ZoneInfo
                t = t.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            return max(0.0, (datetime.now(t.tzinfo) - t).total_seconds())
        except Exception:
            continue
    return None


def _daily_candles(token: int) -> List[List[Any]]:
    """~60 daily candles for a MCX future token, cached once per day (ATR source)."""
    today = date.today().isoformat()
    hit = _DAILY.get(token)
    if hit and hit[0] == today and hit[1]:
        return hit[1]
    try:
        from dashboard.trailing_backtest import fetch_window
        from datetime import timedelta
        candles = fetch_window(token, (date.today() - timedelta(days=90)).isoformat(), today)
    except Exception:
        candles = []
    if candles:
        _DAILY[token] = (today, candles)
    return candles


def atr(token: int, n: int = 14) -> Optional[float]:
    """Wilder ATR(n) from daily candles [ts,o,h,l,c,...]."""
    c = _daily_candles(token)
    if len(c) < n + 1:
        return None
    trs = []
    for i in range(1, len(c)):
        h, l, pc = c[i][2], c[i][3], c[i - 1][4]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return round(a, 2)


def _trade_state(dq_conf: str, liq_grade: str, roll: str, front_price: Optional[float],
                 mkt: str) -> Dict[str, str]:
    """Constrained operational taxonomy (never a raw buy/sell call)."""
    if mkt in ("CLOSED", "HOLIDAY"):
        return {"state": "MARKET_CLOSED", "why": "MCX not in session"}
    if front_price is None:
        return {"state": "NO_DATA", "why": "no fresh future quote"}
    if dq_conf == "low":
        return {"state": "STALE_DATA", "why": "future/option quote stale or unavailable"}
    if roll in ("expiry_risk", "contract_dislocated"):
        return {"state": "ROLL_GUARD", "why": f"front future in {roll}"}
    if liq_grade in ("D", "UNKNOWN"):
        return {"state": "ILLIQUID", "why": f"option liquidity grade {liq_grade}"}
    if liq_grade == "C":
        return {"state": "WATCH", "why": "option spread wide — insight only, not entry-eligible"}
    return {"state": "ELIGIBLE_FOR_REVIEW", "why": "fresh data, tradable liquidity — review, not a signal"}


def watchlist_row(root: str, rows: Optional[List[Dict[str, Any]]] = None,
                  today: Optional[date] = None) -> Dict[str, Any]:
    """One watchlist row for a tradable root. Degrades gracefully to controlled fields."""
    today = today or date.today()
    rows = rows if rows is not None else instruments()
    fn = front_next_future(root, rows, today)
    front, nxt = fn["front"], fn["next"]
    stale = _cfg().get("mcx_quote_stale_seconds", {})
    row: Dict[str, Any] = {
        "root": root.upper(), "economic_root": economic_root(root),
        "active_future": front["tradingsymbol"] if front else None,
        "future_expiry": front["expiry"].isoformat() if front else None,
        "lot_size": front["lot_size"] if front else None,
        "tick_size": front["tick_size"] if front else None,
        "price": None, "change_pct": None, "day_high": None, "day_low": None,
        "atr": None, "atr_pct": None, "notional_per_lot": None,
        "roll": None, "options": None, "trade_state": None,
    }
    if not front:
        row["trade_state"] = {"state": "NO_DATA", "why": "no live MCX future contract found"}
        return row
    syms = [front["tradingsymbol"]] + ([nxt["tradingsymbol"]] if nxt else [])
    q = quote(syms)
    fq = q.get(f"MCX:{front['tradingsymbol']}") or {}
    ltp = fq.get("last_price")
    ohlc = fq.get("ohlc") or {}
    prev = ohlc.get("close")
    a = atr(front["token"])
    fut_age = _quote_age(fq)
    if ltp:
        row["price"] = ltp
        row["day_high"], row["day_low"] = ohlc.get("high"), ohlc.get("low")
        row["change_pct"] = round((ltp - prev) / prev * 100, 2) if prev else None
        row["notional_per_lot"] = round(ltp * (front["lot_size"] or 0), 0) if front["lot_size"] else None
    row["atr"] = a
    row["atr_pct"] = round(a / ltp * 100, 2) if (a and ltp) else None
    rs = roll_state(root, q, rows, today)
    row["roll"] = {"state": rs.roll_state, "front_expiry_days": rs.front_expiry_days,
                   "next": rs.next_future_symbol}
    # basic ATM option snapshot (analytics/Black-76 come in C3)
    liq = {"grade": "UNKNOWN", "grade_confidence": "low", "spread_pct": None, "reason": "not evaluated"}
    if ltp:
        opts = [o for o in _opts(rows) if o["name"] == root.upper() and o["expiry"] and o["expiry"] >= today]
        if opts:
            exp0 = min(o["expiry"] for o in opts)
            near = [o for o in opts if o["expiry"] == exp0]
            atm = min(near, key=lambda o: abs((o["strike"] or 0) - ltp))
            oq = quote([atm["tradingsymbol"]]).get(f"MCX:{atm['tradingsymbol']}") or {}
            depth = oq.get("depth") or {}
            bid = (depth.get("buy") or [{}])[0].get("price")
            ask = (depth.get("sell") or [{}])[0].get("price")
            mx = _cfg().get("mcx_max_option_spread_pct", {}).get(root.upper(), 8.0)
            liq = liquidity_grade(bid, ask, oq.get("last_price"), oi=oq.get("oi"),
                                  volume=oq.get("volume"), max_spread_pct=mx)
            row["options"] = {"atm_strike": atm["strike"], "expiry": exp0.isoformat(),
                              "bid": bid, "ask": ask, "ltp": oq.get("last_price"),
                              "liquidity": liq}
    src = {"mcx_future": {"age_seconds": fut_age, "stale_after": stale.get("future", 10),
                          "ts": fq.get("last_trade_time")}}
    dq = data_quality(src)
    mkt = market_state()
    row["trade_state"] = _trade_state(dq["overall_confidence"], liq["grade"], rs.roll_state, ltp, mkt)
    row["data_quality"] = dq
    return row


def watchlist(roots: Optional[List[str]] = None) -> Dict[str, Any]:
    cfg = _cfg()
    roots = roots or cfg.get("mcx_watchlist_default", MCX_LIQUID_ROOTS)
    rows = instruments()
    out_rows = []
    warnings: List[str] = []
    for r in roots:
        try:
            out_rows.append(watchlist_row(r, rows))
        except Exception as e:
            out_rows.append({"root": r.upper(), "trade_state": {"state": "NO_DATA", "why": f"error: {e}"}})
            warnings.append(f"{r}: {e}")
    src = {"mcx_master": {"age_seconds": 0 if rows else None, "stale_after": cfg.get("mcx_instrument_master_ttl_seconds", 21600),
                          "ts": datetime.now(timezone.utc).isoformat() if rows else None}}
    env = envelope(market_state(), src, warnings)
    return {**env, "rows": out_rows}
