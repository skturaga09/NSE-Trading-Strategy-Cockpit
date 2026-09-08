#!/usr/bin/env python3
"""
MCX event calendar + event-risk guard (C4). Timezone-aware: recurring events store their
NATIVE timezone (e.g. America/New_York) and IST is computed at runtime (DST-aware — an EIA
report at 10:30 ET is 20:00 IST in US summer, 21:00 IST in US winter). Calendar + exposure
only — it NEVER infers bullish/bearish and NEVER auto-exits. It raises alerts / review states
and can block/flag new naked short-premium entries before high-severity events.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_FILE = Path(__file__).parent.parent / "config" / "mcx_events.json"
_WD = {"MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3, "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6}


def _tz(name: str):
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def _ist_now() -> datetime:
    return datetime.now(_tz("Asia/Kolkata"))


def load_events() -> List[Dict[str, Any]]:
    try:
        return json.loads(_FILE.read_text()).get("events", [])
    except Exception:
        return []


def calendar_version() -> Optional[str]:
    try:
        return json.loads(_FILE.read_text()).get("version")
    except Exception:
        return None


def _nth_weekday(year: int, month: int, n: int, weekday: int) -> Optional[date]:
    d = date(year, month, 1)
    day = 1 + (weekday - d.weekday()) % 7 + (n - 1) * 7
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _occurrences(event: Dict[str, Any], now_et: datetime, back_days: int = 3, fwd_days: int = 45) -> List[datetime]:
    """Sorted tz-aware ET datetimes for this event in [now-back, now+fwd]. Overrides are merged
    in (and win as one-offs). Returns [] for override-only events with no dated overrides."""
    tz = now_et.tzinfo
    occs: List[datetime] = []
    rule = event.get("rule")
    lo, hi = (now_et - timedelta(days=back_days)).date(), (now_et + timedelta(days=fwd_days)).date()
    if event.get("schedule_type") == "recurring" and rule:
        parts = rule.split()
        if parts[0] == "WEEKLY":
            wd = _WD[parts[1]]; hh, mm = map(int, parts[2].split(":"))
            d = lo
            while d <= hi:
                if d.weekday() == wd:
                    occs.append(datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz))
                d += timedelta(days=1)
        elif parts[0] == "MONTHLY_NTH":
            n = int(parts[1]); wd = _WD[parts[2]]; hh, mm = map(int, parts[3].split(":"))
            for delta in (-1, 0, 1):
                y, m = now_et.year, now_et.month + delta
                y += (m - 1) // 12; m = (m - 1) % 12 + 1
                nd = _nth_weekday(y, m, n, wd)
                if nd and lo <= nd <= hi:
                    occs.append(datetime(nd.year, nd.month, nd.day, hh, mm, tzinfo=tz))
    for ov in event.get("overrides", []):
        try:
            if ov.get("status") == "cancelled":
                continue
            dt = datetime.fromisoformat(ov["datetime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            occs.append(dt)
        except Exception:
            continue
    return sorted(occs)


def event_state(event: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Next/most-recent occurrence for one event, converted to IST, with a status + guard."""
    now = now or _ist_now()
    tz_et = _tz(event.get("timezone", "America/New_York"))
    now_et = now.astimezone(tz_et)
    occs = _occurrences(event, now_et)
    upcoming = next((o for o in occs if o > now_et), None)
    recent = None
    for o in occs:
        if o <= now_et:
            recent = o
    cooldown = int(event.get("post_event_cooldown_minutes", 30))
    pre = int(event.get("pre_event_minutes", 240))
    status, current = "unknown", None
    if recent and (now_et - recent) <= timedelta(minutes=cooldown):
        status, current = "released", recent          # in post-release cooldown window
    elif upcoming:
        status, current = "scheduled", upcoming
    elif event.get("schedule_type") == "override_only":
        status = "unknown"                             # no dated override → genuinely unknown
    ist = _tz("Asia/Kolkata")
    ttm = round((current.astimezone(ist) - now).total_seconds() / 60.0) if (current and status == "scheduled") else None
    within_guard = bool(ttm is not None and 0 <= ttm <= pre)
    return {
        "id": event["id"], "name": event["name"], "severity": event.get("severity"),
        "commodity_roots": event.get("commodity_roots", []),
        "status": status,
        "event_time_local": current.isoformat() if current else None,
        "event_time_ist": current.astimezone(ist).isoformat() if current else None,
        "time_to_event_minutes": ttm,
        "pre_event_minutes": pre, "post_event_cooldown_minutes": cooldown,
        "within_guard": within_guard,
        "schedule_type": event.get("schedule_type"),
    }


def _roots_for(state: Dict[str, Any], all_roots: List[str]) -> List[str]:
    r = state.get("commodity_roots", [])
    return all_roots if ("ALL" in r) else r


def events(now: Optional[datetime] = None) -> Dict[str, Any]:
    from dashboard import mcx
    now = now or _ist_now()
    all_roots = []
    try:
        from dashboard import mcx_config
        all_roots = mcx_config.get().get("mcx_watchlist_default", mcx.MCX_LIQUID_ROOTS)
    except Exception:
        all_roots = mcx.MCX_LIQUID_ROOTS
    states = []
    for e in load_events():
        if not e.get("enabled", True):
            continue
        st = event_state(e, now)
        st["roots_resolved"] = _roots_for(st, all_roots)
        states.append(st)
    states.sort(key=lambda s: (s["time_to_event_minutes"] is None, s["time_to_event_minutes"] or 1e9))
    return {**mcx.envelope(mcx.market_state(), {}), "calendar_version": calendar_version(), "events": states}


def position_event_risk(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Per open MCX OPTION position: nearest relevant event, exposure (delta/gamma/vega sign,
    naked-short flag), and a guard state. Alerts/review only — never auto-exits."""
    from dashboard import mcx, black76
    now = now or _ist_now()
    ev = events(now)["events"]
    try:
        from dashboard.exit_monitor import _positions
        raw = _positions()
    except Exception as e:
        return {**mcx.envelope("UNKNOWN", {}, [f"positions unavailable: {e}"]), "positions": [], "events": ev}
    rows = mcx.instruments()
    by_sym = {o["tradingsymbol"]: o for o in mcx._opts(rows)}
    out: List[Dict[str, Any]] = []
    for p in raw:
        if (p.get("exchange") or "").upper() != "MCX":
            continue
        opt = by_sym.get(p.get("tradingsymbol"))
        if not opt or not opt.get("expiry"):
            continue
        econ = mcx.economic_root(opt["name"])
        qty = p.get("quantity", 0)
        side = "LONG" if qty > 0 else "SHORT"
        is_short_premium = side == "SHORT"                 # naked unless part of a spread (not detectable here)
        # relevant, imminent events for this root
        rel = [e for e in ev if e["within_guard"] and econ.upper() in [r.upper() for r in e["roots_resolved"]]]
        rel.sort(key=lambda e: e["time_to_event_minutes"] if e["time_to_event_minutes"] is not None else 1e9)
        nearest = rel[0] if rel else None
        high_imminent = any(e["severity"] == "high" for e in rel)
        # exposure greeks (best-effort; None where quote/IV missing)
        greeks = {"delta": None, "gamma": None, "vega": None}
        link = mcx.contract_link(opt, rows)
        try:
            fq = mcx.quote([link.underlying_future_symbol]).get(f"MCX:{link.underlying_future_symbol}") or {} if link.underlying_future_symbol else {}
            F = fq.get("last_price")
            oq = mcx.quote([opt["tradingsymbol"]]).get(f"MCX:{opt['tradingsymbol']}") or {}
            depth = oq.get("depth") or {}
            bid = (depth.get("buy") or [{}])[0].get("price"); ask = (depth.get("sell") or [{}])[0].get("price")
            mid = (bid + ask) / 2 if (bid and ask) else oq.get("last_price")
            T = max((opt["expiry"] - now.date()).days, 0) / 365.0
            iv = black76.implied_vol(mid, F, opt["strike"], T, opt["instrument_type"] == "CE") if (F and mid) else None
            if F and iv and T > 0:
                g = black76.greeks(F, opt["strike"], T, iv / 100.0, opt["instrument_type"] == "CE")
                sign = 1 if side == "LONG" else -1     # short position flips the sign of the position's greeks
                greeks = {k: (round(v * sign, 6) if v is not None else None) for k, v in g.items()}
        except Exception:
            pass
        if nearest and high_imminent and is_short_premium:
            guard = "POSITION_RISK_ALERT"
        elif nearest:
            guard = "EVENT_GUARD"
        else:
            guard = "NONE"
        out.append({
            "symbol": opt["tradingsymbol"], "economic_root": econ, "side": side,
            "is_short_premium": is_short_premium, "greeks": greeks,
            "nearest_event": nearest["name"] if nearest else None,
            "time_to_event_minutes": nearest["time_to_event_minutes"] if nearest else None,
            "severity": nearest["severity"] if nearest else None,
            "guard_state": guard,
            "constraint": ("Short premium into a high-severity event — elevated gamma/vega risk; review."
                           if guard == "POSITION_RISK_ALERT" else
                           "Relevant event within the guard window — size/attention." if guard == "EVENT_GUARD" else None),
        })
    return {**mcx.envelope(mcx.market_state(), {}), "positions": out, "events": ev}


def new_entry_blocked(economic_root: str, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Is a NEW naked short-premium entry blocked for this root by an imminent high event?"""
    ev = events(now)
    blocking = [e for e in ev["events"]
                if e["severity"] == "high" and e["within_guard"] and economic_root.upper() in [r.upper() for r in e["roots_resolved"]]]
    return {"blocked": bool(blocking), "by": [e["id"] for e in blocking]}
