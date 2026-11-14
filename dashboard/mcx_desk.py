#!/usr/bin/env python3
"""
MCX COMMODITY OPTIONS DESK — a separate trading workspace (own URL /mcx/, own API /api/mcx-desk, own data in
data/mcx_desk/). PAPER ONLY: nothing here places, modifies or cancels a Kite order; every Kite call is a GET.

Signal framework (owner spec 2026-11-13, all completed candles, no repaint):
  analysis instrument = the MCX FUTURE that underlies the option we would trade (nearest option expiry with
  >= min_option_dte days, mapped with mcx.option_underlying_future)
  direction = Supertrend(period, mult) of the last completed 15-minute candle of that future
  trigger   = Supertrend of the last completed 5-minute candle, evaluated when each 5-minute candle completes
  both UP -> BUY CE (1 strike in the money) · both DOWN -> BUY PE · they disagree -> WAIT (no entry)
  Entry (owner 2026-11-13): on every completed 5-minute candle where both agree and no position in that commodity is
  held — not only on the candle where they start agreeing.
  A CONFLICT alert and an ALIGNED alert go out right after the 5-minute candle on which the state changes.

Exits per position (checked every minute; hard limits every minute, the trend rule on completed candles):
  EXIT  premium (bid) at/below the stop · daily loss limit hit · Supertrend of the exit timeframe against the
        position · expiry/devolvement cutoff day · INTRADAY policy within N minutes of the session close
  TRAIL once the premium has risen trail_arm_pct above entry (stop = peak less trail_giveback_pct)
  HOLD  otherwise
The paper book exits on the 5-minute rule; an ALT book holds the same entries and exits on the 15-minute rule only,
so the validation view can show whether the 5-minute rule closes positions too often.

Funds: one Kite account backs both dashboards. Every entry is checked against the account's real available margin
(GET /user/margins) less the premium already committed by BOTH paper books (stocks + MCX). Owner 2026-11-13: in
PAPER mode a shortfall is recorded on the trade (real_funds) instead of blocking it; paper trades are limited by the
desk's own budget.
"""

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dashboard import mcx
from dashboard.supertrend import IST, _bar_start, supertrend, to_15m

DATA = Path(__file__).resolve().parents[1] / "data" / "mcx_desk"
SETTINGS, BOOK, STATE, ALERTS = (DATA / n for n in ("settings.json", "paper.json", "state.json", "alerts.jsonl"))
HOLIDAYS = Path(__file__).resolve().parents[1] / "config" / "mcx_holidays.json"
DESK = "MCX"
_LOCK = threading.Lock()

# Units per lot; MCX quotes GOLD per 10 g (1 kg lot), SILVER per kg (30 kg), CRUDEOIL per barrel (100 bbl),
# NATURALGAS per mmBtu (1,250 mmBtu). Kite's master reports lot_size=1 for MCX (quantity is in lots), so the
# multiplier is not in the master: these are the MCX contract specs, cross-checked against Kite's position
# `multiplier` whenever a real position exists (mismatch -> warning on that position).
MULTIPLIER = {"GOLD": 100, "SILVER": 30, "CRUDEOIL": 100, "NATURALGAS": 1250}

DEFAULTS: Dict[str, Any] = {
    "mode": "PAPER",                      # the only mode: live order routing is not built
    "auto_paper_entries": True,
    "alerts": True,
    "roots": ["GOLD", "SILVER", "CRUDEOIL", "NATURALGAS"],
    "st_period": 10, "st_mult": 3.0,
    "capital": 500000.0,                  # MCX desk risk budget (paper), independent of the stock desk (owner 2026-11-13)
    "max_premium_per_trade": 250000.0,    # 1 GOLD lot ≈ ₹2 L of premium
    "daily_loss_limit": 5000.0,
    "max_open_positions": 2,
    "max_lots_per_position": 1,
    "max_entries_per_day": 4,
    "premium_stop_pct": 30.0,
    "trail_arm_pct": 20.0, "trail_giveback_pct": 15.0,
    "exit_policy": "INTRADAY",            # INTRADAY | OVERNIGHT, fixed on each position at entry
    "intraday_exit_before_close_min": 15,
    "no_entry_before_close_min": 45,
    "min_option_dte": 5,
    "exit_before_expiry_days": 2,         # every policy: out by this many days before option expiry (devolvement)
    "max_spread_pct": {"GOLD": 6.0, "SILVER": 8.0, "CRUDEOIL": 8.0, "NATURALGAS": 12.0},
}

# Zerodha commodity options, checked 2026-11-13 against zerodha.com/charges + support article on MCX transaction
# charges: ₹20 / executed order, CTT 0.05 % sell premium, MCX 0.0418 % premium, SEBI ₹10 / crore, stamp 0.003 % buy,
# GST 18 % on brokerage + exchange + SEBI. ASSUMED until a contract note confirms.
CHARGES = {"brokerage_per_order": 20.0, "ctt_sell": 0.0005, "exchange": 0.000418, "sebi": 1e-6,
           "stamp_buy": 0.00003, "gst": 0.18}


# ---------------------------------------------------------------------------- storage (MCX namespace only)
def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write(path: Path, obj) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    tmp.replace(path)


def settings() -> Dict[str, Any]:
    return {**DEFAULTS, **_read(SETTINGS, {})}


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist a settings patch (MCX file only). Raises ValueError on a bad key or value."""
    s = settings()
    for k, v in patch.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown setting {k}")
        if k == "mode":
            if v != "PAPER":
                raise ValueError("only PAPER mode exists: live MCX order routing is not built")
        elif k == "exit_policy":
            if v not in ("INTRADAY", "OVERNIGHT"):
                raise ValueError("exit_policy must be INTRADAY or OVERNIGHT")
        elif k == "roots":
            if not v or any(r not in MULTIPLIER for r in v):
                raise ValueError(f"roots must be a non-empty subset of {sorted(MULTIPLIER)}")
        elif k == "max_spread_pct":
            v = {r: float(x) for r, x in v.items() if r in MULTIPLIER and float(x) > 0}
        elif isinstance(DEFAULTS[k], bool):
            v = bool(v)
        else:
            v = type(DEFAULTS[k])(v)
            if v < 0 or (k in ("st_period", "st_mult", "max_lots_per_position") and v <= 0):
                raise ValueError(f"{k} must be positive")
        s[k] = v
    _write(SETTINGS, {k: s[k] for k in DEFAULTS})
    return s


def book() -> Dict[str, Any]:
    return _read(BOOK, {"open": [], "closed": [], "alt_open": [], "alt_closed": []})


def state() -> Dict[str, Any]:
    return _read(STATE, {})


def alerts(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        lines = ALERTS.read_text().splitlines()[-limit:]
    except OSError:
        return []
    return [json.loads(x) for x in reversed(lines)]


# ---------------------------------------------------------------------------- calendar
def _nth_sunday(y: int, m: int, n: int) -> date:
    d = date(y, m, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))


def us_dst(d: date) -> bool:
    """US daylight saving: 2nd Sunday of March to 1st Sunday of November."""
    return _nth_sunday(d.year, 3, 2) <= d < _nth_sunday(d.year, 11, 1)


def session(now: datetime) -> Dict[str, Any]:
    """MCX non-agri session: 09:00 to 23:30 while the US is on daylight time, else 23:55. Morning 09:00-17:00,
    evening 17:00-close. Holidays from config/mcx_holidays.json (an entry may close only one half)."""
    h = _read(HOLIDAYS, {})
    hol = next((x for x in h.get("holidays", []) if x.get("date") == now.date().isoformat()), None)
    close = "23:30" if us_dst(now.date()) else "23:55"
    hm = now.strftime("%H:%M")
    half = "MORNING" if hm < "17:00" else "EVENING"
    out = {"open": "09:00", "close": close, "half": half, "holiday": hol,
           "holidays_verified": bool(h.get("verified")), "is_open": False, "minutes_to_close": None}
    if now.weekday() >= 5:
        return {**out, "state": "WEEKEND"}
    if hol and hol.get(half.lower()) == "closed":
        return {**out, "state": "HOLIDAY"}
    if hm < "09:00" or hm >= close:
        return {**out, "state": "CLOSED"}
    end = now.replace(hour=int(close[:2]), minute=int(close[3:]), second=0, microsecond=0)
    return {**out, "state": "OPEN", "is_open": True, "minutes_to_close": int((end - now).total_seconds() // 60)}


# ---------------------------------------------------------------------------- calculations
def charges(buy_value: float, sell_value: float) -> float:
    """Round-trip charges for one long option trade, ₹ (values = premium x units)."""
    c = CHARGES
    brok = c["brokerage_per_order"] * 2
    exch = c["exchange"] * (buy_value + sell_value)
    sebi = c["sebi"] * (buy_value + sell_value)
    return round(brok + exch + sebi + c["ctt_sell"] * sell_value + c["stamp_buy"] * buy_value
                 + c["gst"] * (brok + exch + sebi), 2)


def signal_at(candles: List[list], closed_through: datetime, period: int, mult: float) -> Optional[Dict[str, Any]]:
    """Signal using only candles that started at or before `closed_through` (start of the newest closed 5-min bar)."""
    cs = [c for c in candles if datetime.fromisoformat(c[0]) <= closed_through]
    s5 = supertrend(cs, period, mult)
    s15 = supertrend(to_15m(cs, closed_through), period, mult)   # 15-min grid from 09:15 == from 09:00
    if not s5 or s5[-1] is None or not s15 or s15[-1] is None:
        return None
    (d5, l5), (d15, l15) = s5[-1], s15[-1]
    sig = "UP" if d5 == d15 == 1 else "DOWN" if d5 == d15 == -1 else "WAIT"
    return {"dir5": d5, "line5": round(l5, 2), "dir15": d15, "line15": round(l15, 2),
            "close": float(cs[-1][4]), "bar": cs[-1][0], "signal": sig}


def regime(candles: List[list], n: int = 24) -> str:
    """Crude label for validation buckets: efficiency ratio of the last n 5-min closes (>= 0.3 trending)."""
    cl = [float(c[4]) for c in candles[-(n + 1):]]
    path = sum(abs(b - a) for a, b in zip(cl, cl[1:]))
    return "UNKNOWN" if len(cl) < n + 1 or not path else ("TRENDING" if abs(cl[-1] - cl[0]) / path >= 0.3 else "SIDEWAYS")


def option_expiry(root: str, rows: List[Dict[str, Any]], today: date, min_dte: int) -> Optional[date]:
    exps = sorted({o["expiry"] for o in mcx._opts(rows) if o["name"] == root and (o["expiry"] - today).days >= min_dte})
    return exps[0] if exps else None


def pick_option(root: str, direction: str, price: float, expiry: date,
                rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """1 strike in the money: CE = highest strike below the future price, PE = lowest strike above it."""
    typ = "CE" if direction == "UP" else "PE"
    ch = [o for o in mcx._opts(rows) if o["name"] == root and o["expiry"] == expiry and o["instrument_type"] == typ]
    itm = [o for o in ch if (o["strike"] < price if typ == "CE" else o["strike"] > price)]
    if not itm:
        return None
    return max(itm, key=lambda o: o["strike"]) if typ == "CE" else min(itm, key=lambda o: o["strike"])


def book_side(q: Dict[str, Any]) -> Dict[str, Any]:
    d = q.get("depth") or {}
    b, a = (d.get("buy") or [{}])[0], (d.get("sell") or [{}])[0]
    bid, ask = b.get("price") or None, a.get("price") or None
    return {"bid": bid, "ask": ask, "ask_qty": a.get("quantity") or 0, "ltp": q.get("last_price"),
            "spread_pct": round((ask - bid) / ((ask + bid) / 2) * 100, 2) if bid and ask else None,
            "oi": q.get("oi"), "volume": q.get("volume")}


def account_funds(margins: Optional[Dict[str, Any]], exchanges: Optional[List[str]] = None) -> Dict[str, Any]:
    """One account, one pool. Zerodha keeps equity and commodity funds in a single ledger, so the pool is the
    largest `net` among ENABLED segments (never the sum — that would double count).
    MCX access comes from /user/profile `exchanges`: with the single ledger, /user/margins reports the commodity
    block as enabled=false, net 0 even on an MCX-enabled account (seen on this account 2026-11-13)."""
    mcx_on = None if exchanges is None else "MCX" in exchanges
    if not margins:
        return {"available": None, "commodity_enabled": mcx_on, "error": "broker funds unavailable"}
    en = {k: v for k, v in margins.items() if isinstance(v, dict) and v.get("enabled")}
    return {"available": max((float(v.get("net") or 0) for v in en.values()), default=0.0),
            "commodity_enabled": mcx_on, "error": None}


def committed(positions: List[Dict[str, Any]]) -> float:
    return round(sum(p["entry"] * p["units"] for p in positions), 2)


def stock_paper_committed() -> float:
    """Premium held by the STOCK paper book (read-only): it shares the same broker account."""
    from dashboard.supertrend_paper import STATE as STOCK
    open_ = _read(STOCK, {}).get("open", [])
    return round(sum(p["qty"] * p["entry"] for p in open_), 2)


def guide(pos: Dict[str, Any], quote: Dict[str, Any], sig: Optional[Dict[str, Any]], now: datetime,
          sess: Dict[str, Any], s: Dict[str, Any], tf: str = "5m", day_locked: bool = False) -> Dict[str, Any]:
    """HOLD / TRAIL / EXIT for one long option position, with reason, premium, est. P&L, stops and timestamp."""
    entry, units = pos["entry"], pos["units"]
    px = quote.get("bid") or None                     # what a sell would get now
    peak = max(pos.get("peak", entry), px or 0)
    hard = entry * (1 - s["premium_stop_pct"] / 100)
    armed = peak >= entry * (1 + s["trail_arm_pct"] / 100)
    stop = max(hard, peak * (1 - s["trail_giveback_pct"] / 100)) if armed else hard
    side = 1 if pos["option_type"] == "CE" else -1
    d, line = (sig["dir5"], sig["line5"]) if sig and tf == "5m" else (sig["dir15"], sig["line15"]) if sig else (None, None)
    reason = None
    if px is not None and px <= stop:
        reason = "trailing premium stop hit" if armed else "premium stop hit"
    elif day_locked:
        reason = "daily loss limit reached"
    elif d is not None and d != side:
        reason = f"{tf} Supertrend of {pos['future']} turned against the position"
    elif pos.get("exit_by") and now.date().isoformat() >= pos["exit_by"]:
        reason = f"expiry / devolvement cutoff ({pos['exit_by']})"
    elif pos.get("policy") == "INTRADAY" and sess.get("minutes_to_close") is not None \
            and sess["minutes_to_close"] <= s["intraday_exit_before_close_min"]:
        reason = "intraday policy: square off before the session close"
    action = "EXIT" if reason else ("TRAIL" if armed else "HOLD")
    if not reason:
        reason = f"trailing: stop moved up to ₹{stop:.2f}" if armed else f"trend with the position on {tf}; stop ₹{stop:.2f}"
    pnl = None if px is None else round((px - entry) * units - charges(entry * units, px * units), 2)
    return {"action": action, "reason": reason, "premium": px, "ltp": quote.get("ltp"), "peak": round(peak, 2),
            "est_pnl": pnl, "stop_premium": round(stop, 2), "stop_future": line, "at": now.isoformat(timespec="seconds"),
            "no_bid": px is None}


def entry_blocks(s: Dict[str, Any], sess: Dict[str, Any], root: str, q: Dict[str, Any], lots: int, cost: float,
                 bk: Dict[str, Any], today: str, day_locked: bool) -> List[str]:
    """Every reason a fresh paper entry is refused (empty = allowed)."""
    out = []
    if not s["auto_paper_entries"]:
        out.append("auto paper entries are off")
    if not sess["is_open"]:
        out.append(f"MCX {sess.get('state', 'closed').lower()}")
    elif sess["minutes_to_close"] <= s["no_entry_before_close_min"]:
        out.append(f"no entries in the last {s['no_entry_before_close_min']} min of the session")
    if day_locked:
        out.append("daily loss limit reached")
    if not (q.get("bid") and q.get("ask")):
        out.append("no two-sided option quote")
    elif q["spread_pct"] > s["max_spread_pct"].get(root, 8.0):
        out.append(f"spread {q['spread_pct']}% > {s['max_spread_pct'].get(root, 8.0)}%")
    elif q["ask_qty"] < lots:
        out.append(f"only {q['ask_qty']} lot(s) offered at the ask")
    if any(p["root"] == root for p in bk["open"]):
        out.append(f"already holding a {root} position")
    if len(bk["open"]) >= s["max_open_positions"]:
        out.append(f"max {s['max_open_positions']} open positions")
    if sum(1 for p in bk["open"] + bk["closed"] if p["entry_at"][:10] == today) >= s["max_entries_per_day"]:
        out.append(f"max {s['max_entries_per_day']} entries today")
    if cost > s["max_premium_per_trade"]:
        out.append(f"premium ₹{cost:,.0f} > per-trade cap ₹{s['max_premium_per_trade']:,.0f}")
    desk_free = s["capital"] + sum(c["net"] for c in bk["closed"]) - committed(bk["open"])
    if cost > desk_free:
        out.append(f"premium ₹{cost:,.0f} > MCX desk budget left ₹{desk_free:,.0f}")
    return out


def account_shortfall(cost: float, funds: Dict[str, Any], stock_committed: float, bk: Dict[str, Any]) -> Optional[str]:
    """Why the REAL account could not pay for this trade (None = it could): Kite's free funds less the premium held
    by BOTH paper books. Owner 2026-11-13: in PAPER mode this is a flag on the trade, not a block; a live mode
    must treat it as a block."""
    if funds.get("available") is None:
        return "real funds unknown (Kite /user/margins did not answer)"
    acct_free = funds["available"] - stock_committed - committed(bk["open"])
    if cost <= acct_free:
        return None
    return (f"real account short: premium ₹{cost:,.0f} > free ₹{acct_free:,.0f} (Kite ₹{funds['available']:,.0f} "
            f"less paper held: stocks ₹{stock_committed:,.0f}, MCX ₹{committed(bk['open']):,.0f})")


def day_pnl(bk: Dict[str, Any], guides: Dict[str, Dict[str, Any]], today: str) -> float:
    realised = sum(c["net"] for c in bk["closed"] if c["exit_at"][:10] == today)
    return round(realised + sum(g["est_pnl"] or 0 for g in guides.values()), 2)


# ---------------------------------------------------------------------------- Kite I/O (GET only)
def _kite_get(path: str) -> Optional[Dict[str, Any]]:
    import requests
    try:
        j = requests.get(f"https://api.kite.trade{path}", headers=mcx._headers(), timeout=10).json()
        return j.get("data") if j.get("status") == "success" else None
    except Exception:
        return None


def _io() -> Dict[str, Callable]:
    from dashboard.supertrend import _candles
    from dashboard.option_chain import _connected
    return {"rows": mcx.instruments, "candles": _candles, "quote": mcx.quote, "connected": _connected,
            "margins": lambda: _kite_get("/user/margins"),
            "exchanges": lambda: (_kite_get("/user/profile") or {}).get("exchanges"),
            "positions": lambda: (_kite_get("/portfolio/positions") or {}).get("net", []),
            "notify": _notify}


def _notify(title: str, body: str) -> None:
    from dashboard.exit_monitor import notify
    notify(f"MCX · {title}", body, tags=["oil_drum"], priority=4)


def _alert(st: Dict[str, Any], key: str, kind: str, title: str, body: str, send: Callable, on: bool) -> None:
    """Record (MCX alert log) and push one alert per key."""
    if key in st.setdefault("alerted", []):
        return
    st["alerted"] = st["alerted"][-300:] + [key]
    DATA.mkdir(parents=True, exist_ok=True)
    with ALERTS.open("a") as f:
        f.write(json.dumps({"desk": DESK, "kind": kind, "title": title, "body": body,
                            "at": datetime.now(IST).isoformat(timespec="seconds")}) + "\n")
    if on:
        try:
            send(title, body)
        except Exception:
            pass


# ---------------------------------------------------------------------------- the minute loop
def tick(now: Optional[datetime] = None, io: Optional[Dict[str, Callable]] = None) -> Dict[str, Any]:
    if not _LOCK.acquire(blocking=False):
        return {"skipped": "tick already running"}
    try:
        return _tick(now or datetime.now(IST), io or _io())
    finally:
        _LOCK.release()


def _tick(now: datetime, io: Dict[str, Callable]) -> Dict[str, Any]:
    s, bk, st = settings(), book(), state()
    today, at = now.date().isoformat(), now.isoformat(timespec="seconds")
    sess = session(now)
    st.update(last_tick=at, session=sess, errors=[])
    if st.get("day") != today:
        st.update(day=today, day_locked=False, alerted=[])
    if not io["connected"]():
        st["errors"].append("Kite not connected")
        _write(STATE, st)
        return {"skipped": "Kite not connected"}
    rows = io["rows"]()
    bar = _bar_start(now)
    new_bar = st.get("bar") != bar.isoformat()
    by_sym = {o["tradingsymbol"]: o for o in mcx._opts(rows)}

    # analysis futures: one per root (underlying of the nearest option expiry we may trade) + every held future
    contracts: Dict[str, Dict[str, Any]] = {}
    for root in s["roots"]:
        exp = option_expiry(root, rows, now.date(), s["min_option_dte"])
        res = mcx.option_underlying_future(root, exp, rows, now.date()) if exp else {"status": "none", "future": None}
        fut = res.get("future")
        contracts[root] = {"root": root, "option_expiry": exp.isoformat() if exp else None,
                           "future": fut["tradingsymbol"] if fut else None, "token": fut["token"] if fut else None,
                           "future_expiry": fut["expiry"].isoformat() if fut else None,
                           "mapping": res.get("mapping_method"), "mapping_confidence": res.get("mapping_confidence"),
                           "warnings": res.get("warnings", [])}
    broker = [p for p in io["positions"]() if (p.get("exchange") or "").upper() == "MCX" and p.get("quantity")]
    fut_tokens = {c["future"]: c["token"] for c in contracts.values() if c["future"]}
    fut_tokens.update({p["future"]: p["future_token"] for p in bk["open"] + bk["alt_open"]})
    for p in broker:
        o = by_sym.get(p["tradingsymbol"])
        if o:
            ln = mcx.contract_link(o, rows, now.date())
            if ln.underlying_future_symbol:
                fut_tokens[ln.underlying_future_symbol] = ln.underlying_future_token

    # signals on completed candles: refreshed once per new 5-min bar, only when Kite already has that bar
    # (market closed: keep the last board, fetch only futures it lacks)
    sigs = {} if (new_bar and sess["is_open"]) else dict(st.get("signals", {}))
    fresh: Dict[str, Dict[str, Any]] = {}      # state changed on this candle -> alerts
    evaluated: Dict[str, Dict[str, Any]] = {}  # evaluated on this completed candle -> entries
    complete = True
    for fsym, tok in fut_tokens.items():
        if fsym in sigs:
            continue
        try:
            cs = io["candles"](str(tok), now)
        except Exception as e:
            st["errors"].append(f"{fsym} candles: {str(e)[:80]}")
            complete = False
            continue
        if sess["is_open"] and (not cs or datetime.fromisoformat(cs[-1][0]) < bar):
            complete = False                 # Kite has not published this bar yet: retry next minute
        cur = signal_at(cs, bar, s["st_period"], s["st_mult"])
        prev = signal_at(cs, bar - timedelta(minutes=5), s["st_period"], s["st_mult"])
        if cur:
            sigs[fsym] = {**cur, "prev_signal": prev["signal"] if prev else None,
                          "regime": regime([c for c in cs if datetime.fromisoformat(c[0]) <= bar])}
            if sess["is_open"]:
                evaluated[fsym] = sigs[fsym]
                if prev and prev["signal"] != cur["signal"]:
                    fresh[fsym] = sigs[fsym]
    st["signals"] = sigs
    if complete:
        st["bar"] = bar.isoformat()
    else:
        fresh, evaluated = {}, {}             # no alerts/entries on a partial bar

    # quotes: futures + held options + candidate options
    picks: Dict[str, Optional[Dict[str, Any]]] = {}
    for root, c in contracts.items():
        sg = sigs.get(c["future"])
        if sg and sg["signal"] in ("UP", "DOWN") and c["option_expiry"]:
            picks[root] = pick_option(root, sg["signal"], sg["close"], date.fromisoformat(c["option_expiry"]), rows)
    syms = set(fut_tokens) | {p["option"] for p in bk["open"] + bk["alt_open"]} \
        | {p["tradingsymbol"] for p in broker} | {o["tradingsymbol"] for o in picks.values() if o}
    raw = io["quote"](sorted(syms)) if syms else {}
    quotes = {k.split(":", 1)[1]: v for k, v in raw.items()}
    qs = {k: book_side(v) for k, v in quotes.items()}

    # exits (main book: 5-min rule; alt book: 15-min rule) — hard limits every minute
    guides = {p["id"]: guide(p, qs.get(p["option"], {}), sigs.get(p["future"]), now, sess, s, "5m") for p in bk["open"]}
    if not st.get("day_locked") and day_pnl(bk, guides, today) <= -s["daily_loss_limit"]:
        st["day_locked"] = True
        _alert(st, f"lock|{today}", "RISK", "Daily loss limit reached",
               f"MCX desk day P&L ≤ −₹{s['daily_loss_limit']:,.0f}. All paper positions exit; no entries today.",
               io["notify"], s["alerts"])
    locked = st["day_locked"]
    sold = []
    for name, tf, lk in (("open", "5m", locked), ("alt_open", "15m", False)):
        closed_key = "closed" if name == "open" else "alt_closed"
        for p in list(bk[name]):
            g = guide(p, qs.get(p["option"], {}), sigs.get(p["future"]), now, sess, s, tf, lk)
            p["peak"], p["last"] = g["peak"], g
            if g["action"] != "EXIT" or g["no_bid"] or not sess["is_open"]:
                continue
            q = qs[p["option"]]
            bk[name].remove(p)
            cost = charges(p["entry"] * p["units"], q["bid"] * p["units"])
            gross = (q["bid"] - p["entry"]) * p["units"]
            bk[closed_key].append({**p, "exit": q["bid"], "exit_ask": q["ask"], "exit_at": at, "exit_why": g["reason"],
                                   "gross": round(gross, 2), "costs": cost, "net": round(gross - cost, 2),
                                   "hold_min": int((now - datetime.fromisoformat(p["entry_at"])).total_seconds() // 60)})
            if name == "open":
                sold.append(p["option"])
                _alert(st, f"exit|{p['id']}", "EXIT", f"PAPER EXIT {p['option']}: ₹{gross - cost:+,.0f}",
                       f"{g['reason']}. Sold at bid ₹{q['bid']} ({p['lots']} lot × {p['multiplier']}).",
                       io["notify"], s["alerts"])

    # alerts for state changes on the just-completed candle
    for root, c in contracts.items():
        sg = fresh.get(c["future"])
        if not sg:
            continue
        if sg["signal"] == "WAIT":
            _alert(st, f"sig|{root}|{sg['bar']}", "CONFLICT", f"{root} WAIT: 15m and 5m disagree",
                   f"{c['future']} 15m {'UP' if sg['dir15'] == 1 else 'DOWN'}, 5m {'UP' if sg['dir5'] == 1 else 'DOWN'} "
                   f"(candle {sg['bar'][11:16]}). No entry while they disagree.", io["notify"], s["alerts"])
        else:
            o = picks.get(root)
            _alert(st, f"sig|{root}|{sg['bar']}", "ALIGNED", f"{root} {sg['signal']}: 15m and 5m agree",
                   f"{c['future']} @ {sg['close']} (candle {sg['bar'][11:16]}). "
                   f"Option: {o['tradingsymbol'] if o else 'none 1-ITM'}. Paper mode.", io["notify"], s["alerts"])

    # paper entries: both agree on this completed candle and nothing held in that commodity (entry_blocks)
    margins = io["margins"]()
    funds = account_funds(margins, io["exchanges"]())
    stock_c = stock_paper_committed()
    bought, blocked, gates = [], {}, {}
    for root, c in contracts.items():
        o = picks.get(root)
        if not o:
            continue
        sg = evaluated.get(c["future"])
        q = qs.get(o["tradingsymbol"], {})
        mult = MULTIPLIER[root]
        lots = int(s["max_lots_per_position"])
        cost = (q.get("ask") or 0) * mult * lots
        why = entry_blocks(s, sess, root, q, lots, cost, bk, today, locked)
        short = account_shortfall(cost, funds, stock_c, bk)
        gates[root] = {"cost": round(cost, 2), "lots": lots, "blocks": why, "real_funds": short}   # signal-table preview
        if not sg:
            continue
        if why:
            blocked[root] = why
            continue
        p = {"id": f"{root}|{at}", "desk": DESK, "exchange": "MCX", "root": root, "option": o["tradingsymbol"],
             "option_type": o["instrument_type"], "strike": o["strike"], "option_expiry": o["expiry"].isoformat(),
             "future": c["future"], "future_token": c["token"], "lots": lots, "multiplier": mult,
             "units": lots * mult, "entry": q["ask"], "entry_bid": q["bid"], "entry_spread_pct": q["spread_pct"],
             "entry_at": at, "signal": sg["signal"], "signal_bar": sg["bar"], "future_at_entry": sg["close"],
             "policy": s["exit_policy"], "exit_by": (o["expiry"] - timedelta(days=s["exit_before_expiry_days"])).isoformat(),
             "half": sess["half"], "regime": sg["regime"], "dte": (o["expiry"] - now.date()).days, "peak": q["ask"],
             "real_funds": short or "ok"}
        bk["open"].append(p)
        bk["alt_open"].append(dict(p))
        bought.append(p["option"])
        _alert(st, f"buy|{p['id']}", "ENTRY", f"PAPER BUY {p['option']}",
               f"{root} {sg['signal']} · ask ₹{q['ask']} × {mult} = ₹{cost:,.0f} · policy {p['policy']}, out by "
               f"{p['exit_by']}. Paper only.", io["notify"], s["alerts"])

    # real broker positions: guidance only (the desk never trades them)
    peaks = st.setdefault("broker_peaks", {})
    real = []
    for bp in broker:
        o = by_sym.get(bp["tradingsymbol"])
        ln = mcx.contract_link(o, rows, now.date()) if o else None
        root = mcx.economic_root(o["name"]) if o else None
        mult = MULTIPLIER.get(o["name"]) if o else None
        warn = []
        if bp.get("multiplier") and mult and float(bp["multiplier"]) != mult:
            warn.append(f"Kite multiplier {bp['multiplier']} ≠ desk {mult}: using Kite's")
        mult = float(bp.get("multiplier") or mult or 1)
        qty = int(bp["quantity"])
        row = {"source": "BROKER", "option": bp["tradingsymbol"], "lots": qty, "multiplier": mult,
               "avg": bp.get("average_price"), "kite_pnl": bp.get("pnl"), "product": bp.get("product"), "warnings": warn}
        if o and qty > 0 and ln and ln.underlying_future_symbol:
            pos = {"entry": float(bp["average_price"]), "units": qty * mult, "option_type": o["instrument_type"],
                   "future": ln.underlying_future_symbol, "peak": peaks.get(bp["tradingsymbol"], float(bp["average_price"])),
                   "policy": "SET IN KITE", "exit_by": (o["expiry"] - timedelta(days=s["exit_before_expiry_days"])).isoformat()}
            g = guide(pos, qs.get(bp["tradingsymbol"], {}), sigs.get(pos["future"]), now, sess, s, "5m", locked)
            peaks[bp["tradingsymbol"]] = g["peak"]
            row.update(root=root, future=pos["future"], exit_by=pos["exit_by"], guide=g)
            if g["action"] == "EXIT":
                _alert(st, f"real|{bp['tradingsymbol']}|{g['reason']}", "EXIT", f"REAL position EXIT? {bp['tradingsymbol']}",
                       f"{g['reason']}. Guidance only — exit it yourself in Kite.", io["notify"], s["alerts"])
        else:
            row["warnings"].append("short or unmapped MCX position: no exit guidance (desk models long options only)")
        real.append(row)

    st.update(contracts=contracts, picks={r: (o["tradingsymbol"] if o else None) for r, o in picks.items()},
              quotes={k: {**v, "age_s": mcx._quote_age(quotes[k])} for k, v in qs.items()},
              funds={**funds, "stock_paper_committed": stock_c, "mcx_paper_committed": committed(bk["open"])},
              broker=real, blocked=blocked, gates=gates, day_pnl=day_pnl(bk, {p["id"]: p.get("last", {"est_pnl": 0}) for p in bk["open"]}, today))
    _write(BOOK, bk)
    _write(STATE, st)
    return {"bar": st.get("bar"), "new_bar": new_bar, "fresh": list(fresh), "evaluated": list(evaluated), "bought": bought, "sold": sold,
            "blocked": blocked, "errors": st["errors"]}


# ---------------------------------------------------------------------------- read models for the page
def desk() -> Dict[str, Any]:
    s, bk, st = settings(), book(), state()
    hist = sorted(bk["closed"], key=lambda c: c["exit_at"], reverse=True)
    daily: Dict[str, Dict[str, float]] = {}
    for c in bk["closed"]:
        d = daily.setdefault(c["exit_at"][:10], {"trades": 0, "net": 0.0, "costs": 0.0})
        d["trades"] += 1
        d["net"] = round(d["net"] + c["net"], 2)
        d["costs"] = round(d["costs"] + c["costs"], 2)
    return {"desk": DESK, "mode": s["mode"], "settings": s, "multipliers": MULTIPLIER, "charges": CHARGES,
            "state": st, "now": datetime.now(IST).isoformat(timespec="seconds"),
            "session": session(datetime.now(IST)), "paper_open": bk["open"], "history": hist[:200],
            "daily": [{"day": k, **v} for k, v in sorted(daily.items(), reverse=True)],
            "alerts": alerts(40)}


def validation() -> Dict[str, Any]:
    """Closed paper trades grouped the ways the owner asked: per commodity, session half, regime, expiry distance,
    exit reason — and the 5-min-exit book against the same entries exited on the 15-min rule only."""
    bk = book()

    def stats(rows):
        n = len(rows)
        return {"trades": n, "wins": sum(1 for r in rows if r["net"] > 0),
                "net": round(sum(r["net"] for r in rows), 2), "avg": round(sum(r["net"] for r in rows) / n, 2) if n else None,
                "costs": round(sum(r["costs"] for r in rows), 2),
                "spread_paid": round(sum((r["entry"] - r["entry_bid"]) * r["units"] for r in rows if r.get("entry_bid")), 2),
                "avg_hold_min": round(sum(r["hold_min"] for r in rows) / n) if n else None,
                "trend_exits": sum(1 for r in rows if "Supertrend" in r["exit_why"])}

    def group(rows, key):
        out: Dict[str, list] = {}
        for r in rows:
            out.setdefault(key(r), []).append(r)
        return [{"key": k, **stats(v)} for k, v in sorted(out.items())]

    main, alt = bk["closed"], bk["alt_closed"]
    alt_ids = {r["id"] for r in alt}
    paired = [r for r in main if r["id"] in alt_ids]
    return {"by_root": group(main, lambda r: r["root"]),
            "by_bucket": group(main, lambda r: f"{r['root']} · {r['half']} · {r['regime']} · "
                                                f"{'≤10d' if r['dte'] <= 10 else '>10d'} to expiry"),
            "by_exit": group(main, lambda r: r["exit_why"].split(" (")[0]),
            "exit_rule": {"5m": stats(paired), "15m": stats([r for r in alt if r["id"] in {p["id"] for p in paired}]),
                          "alt_still_open": len(bk["alt_open"])},
            "note": "Paper fills at the live best ask (buy) and best bid (sell), charges per CHARGES. Small samples "
                    "say nothing; read these only after dozens of trades per bucket."}
