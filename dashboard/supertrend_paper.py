#!/usr/bin/env python3
"""
SUPERTREND LIVE PAPER TRADING — stage 1 of docs/supertrend-auto-plan.md (owner request 2026-11-13). No order is sent.

Every minute in market hours (the com.clade.supertrend job) the SAME decisions the order tickets show
(supertrend_trades.view) are run against a paper account instead of the Kite account:
  TAKE signal   -> the exact Kite order the auto version would POST is recorded and filled on paper
  SELL decision -> the paper position is sold at the option's live price; net P&L after charges is booked
So it proves the live path end to end: signal -> order -> fill -> exit -> P&L, on live prices.

Paper account (owner 2026-11-13): ₹1,00,000 start (₹50,000 + the ₹50,000 being added), profits reused the same day, losses
shrink it. 1 lot per signal (MAX_LOTS); the 1 lot must still fit the cash and the 10 % day loss budget decided in
supertrend_trades.view (D-78); here only the owner's
2-losses-in-a-row rule (journal MAIN) is added.
Fills: a buy fills at once at the best ask the view priced it at (lots already capped to the quantity offered there);
a sell fills at the last price less an ASSUMED 1 % half-spread.
Charges: the verified schedule (engine.costs.round_trip), booked at the exit.

SHADOW BOOK (owner 2026-11-13): every paper buy is copied into st["shadow"] at the same price and lots, and sold only when
a 5-minute candle CLOSES with the opposite Supertrend signal (no line-touch stop); premium stop, 15:15 and expiry rules
are the same. It never touches the main book's cash, budget or entries: the two differ only in the exit.
Backtest 2 Sep-12 Nov (751 signals): touch +₹848 / trade, candle close +₹676 / trade.

STRONG BOOK (owner 2026-11-19): a second, separate ₹1,00,000 paper account (STRONG_STATE) run by the same rules, except
it buys only signals whose flip candle's body is at least STRONG_MIN x the average 5-minute range (ATR of the 14 candles
before it). Own cash, 4-open / order / day-loss limits and 2-losses rule, no shadow, no phone alerts. Replay 28 Oct-17 Nov
(1,310 signals, cut fixed at the top tercile): ₹6.7 -> ₹11.1 per ₹100 trending, -₹0.5 -> +₹3.0 sideways. Paper decides.

NO LIMITS ON THE MAIN BOOK (owner 2026-11-20): the main paper account runs WITHOUT the 10 % day loss budget and the
2-losses-in-a-row rule (Journal replay NO_DAY_LIMITS); cash, 1 lot, 4 open and 20 orders a day stay. It continues the
no-limits test account started 10:08 that day; the account run with the rules until then (history from 13 Nov) carries on
as the RULES BOOK (RULES_STATE): the live rules, own cash, no shadow, no alerts. Paper only: the live rules are unchanged.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from dashboard.supertrend import IST, STRONG_MIN

START_CASH, HALF = 100_000.0, 0.01
MAX_LOTS = 1          # owner 2026-11-13: 1 lot per signal (backtest 2 Sep-12 Nov: more trades, smaller falls than flexible lots)
STATE = Path(__file__).resolve().parents[1] / "data" / "engine" / "supertrend_paper.json"
STRONG_STATE = STATE.with_name("supertrend_paper_strong.json")
RULES_STATE = STATE.with_name("supertrend_paper_rules.json")


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    try:
        return json.loads((path or STATE).read_text())
    except (OSError, ValueError):
        return {"start": START_CASH, "cash": START_CASH, "open": [], "closed": [], "orders": [], "day": None}


_LIVE: Dict[str, Any] = {"at": 0.0, "syms": [], "px": {}}


def live_prices(books) -> Dict[str, Any]:
    """Fresh last prices of every open paper option and its stock for the Paper panel: one Kite call per 5 s at most.
    Display only: the minute job still makes every buy/sell decision. -> {at, px: {"NFO:X": price, "NSE:Y": price}}"""
    from dashboard.option_chain import INDEX_SYM
    key = {f"NFO:{p['option']}": f"NFO:{p['option']}" for b in books for p in b.get("open", [])}
    key |= {INDEX_SYM.get(p["underlying"], f"NSE:{p['underlying']}"): f"NSE:{p['underlying']}"
            for b in books for p in b.get("open", [])}         # index spot "NSE:NIFTY 50" is shown as "NSE:NIFTY"
    syms = sorted(key)
    if syms and (syms != _LIVE["syms"] or time.time() - _LIVE["at"] >= 5):
        from dashboard.supertrend_trades import _get
        q = _get("/quote/ltp", [("i", s) for s in syms])
        _LIVE.update(at=time.time(), syms=syms, px={key[k]: v.get("last_price") for k, v in q.items() if k in key})
    return {"at": datetime.fromtimestamp(_LIVE["at"], IST).isoformat(timespec="seconds") if _LIVE["at"] else None,
            "px": _LIVE["px"]}


def _costs(entry: float, exit_: float, qty: int, day) -> float:
    from engine.costs import round_trip
    from engine.paper import load as cfg
    return round_trip(cfg(), "OPT", "BUY", entry, exit_, qty, day).total_inr


def _net(book: list) -> list:
    """Paper positions in Kite's net-position shape, for supertrend_trades.view."""
    return [{"exchange": "NFO", "tradingsymbol": p["option"], "quantity": p["qty"], "average_price": p["entry"],
             "last_price": p["ltp"], "pnl": (p["ltp"] - p["entry"]) * p["qty"]} for p in book]


def _close(book: Dict[str, Any], p: Dict[str, Any], d: Dict[str, Any], at: str, now: datetime) -> Dict[str, Any]:
    """Sell paper position p at the option's live price less the spread; book net P&L after charges."""
    exit_px = d["ltp"] * (1 - HALF)
    costs = _costs(p["entry"], exit_px, p["qty"], now.date())
    gross = (exit_px - p["entry"]) * p["qty"]
    book["open"].remove(p)
    c = {**p, "exit": round(exit_px, 2), "exit_at": at, "exit_why": d["why"],
         "gross": round(gross, 2), "costs": round(costs, 2), "net": round(gross - costs, 2)}
    book["closed"].append(c)
    return c


def _day_blocked(st: Dict[str, Any], today: str) -> Optional[str]:
    done = [c for c in st["closed"] if c["exit_at"][:10] == today]
    if len(done) >= 2 and done[-1]["net"] < 0 and done[-2]["net"] < 0:
        return "2 losses in a row today"
    return None


def step(now: Optional[datetime] = None, notify=None, view=None) -> Dict[str, Any]:
    """One minute of paper trading: main book (no limits), strong-candle book, rules book. -> {bought, sold, balance, errors, strong, rules}."""
    from dashboard import supertrend_trades as T
    now = now or datetime.now(IST)
    view = view or T.view
    if notify is None:
        from dashboard.exit_monitor import notify
    out = _book(STATE, now, view, notify, shadow=True, limits=False)
    try:                                             # the test book never stops the main one
        s = _book(STRONG_STATE, now, view, lambda *a, **k: None, shadow=False, strong_min=STRONG_MIN)
        out["strong"] = {k: s[k] for k in ("bought", "sold", "balance")}
        out["errors"] += [f"strong book: {e}" for e in s["errors"] if "not bought" in e]
    except Exception as e:
        out["errors"].append(f"strong book: {str(e)[:120]}")
    try:
        r = _book(RULES_STATE, now, view, lambda *a, **k: None, shadow=False)
        out["rules"] = {k: r[k] for k in ("bought", "sold", "balance")}
    except Exception as e:
        out["errors"].append(f"rules book: {str(e)[:120]}")
    return out


def _book(path: Path, now: datetime, view, notify, shadow: bool, strong_min: Optional[float] = None,
          limits: bool = True) -> Dict[str, Any]:
    """One minute of one paper account: exits, then entries for the TAKE signals (strong_min: see view()).
    limits=False: no day loss budget, no 2-losses rule (the main book since 2026-11-20)."""
    today, at = now.date().isoformat(), now.isoformat(timespec="seconds")
    st = load(path)
    if st.get("day") != today:
        st.update(day=today, keys=[], day_open=st["cash"] + sum(p["qty"] * p["entry"] for p in st["open"]))  # booked only
    buys = [{"exchange": "NFO", "transaction_type": side, "status": "COMPLETE"}      # today's paper buys and sells
            for side, k, ps in (("BUY", "entry_at", st["open"] + st["closed"]), ("SELL", "exit_at", st["closed"]))
            for p in ps if p[k][:10] == today]
    kw = {"strong_min": strong_min} if strong_min is not None else {}     # main book: view() exactly as before
    if not limits:
        kw["day_loss"] = False
    v = view(now, account=(st["cash"], _net(st["open"]), buys, st["day_open"]), max_lots=MAX_LOTS,
             peaks={p["option"]: p.get("peak", p["entry"]) for p in st["open"]}, **kw)
    out = {"bought": [], "sold": [], "errors": v["errors"]}

    # exits first: they free cash and slots for this minute's entries
    for d in v["positions"]:
        p = next(x for x in st["open"] if x["option"] == d["option"])
        if d["ltp"]:
            p["ltp"] = d["ltp"]
        p["peak"] = d["high"]                         # trailing premium stop: highest price seen since the buy
        p.update(stock=d["stock_ltp"], line=d["line"], plan=d["why"], action=d["action"], checked=at)   # the system's last check, for the panel
        if d["action"] != "SELL" or not d["ltp"]:
            continue
        c = _close(st, p, d, at, now)
        st["cash"] += c["exit"] * c["qty"] - c["costs"]
        st["orders"].append({"at": at, **d["sell"][0]})
        out["sold"].append(p["option"])
        notify(f"PAPER SELL {p['option']}: {'+' if c['net'] >= 0 else ''}₹{c['net']:,.0f}", d["why"],
               tags=["memo"], priority=3)

    sh = st.setdefault("shadow", {"open": [], "closed": []}) if shadow else {"open": []}
    blocked = _day_blocked(st, today) if limits else None
    for s in v["signals"]:
        key = f"{s['symbol']}|{today}|{s['signal_at']}"
        if s["verdict"] != "TAKE" or key in st["keys"]:
            continue
        if blocked:
            st["keys"].append(key)
            out["errors"].append(f"{s['symbol']} not bought: {blocked}")
            continue
        o = s["orders"][0]
        entry = o["price"]                           # the ask
        st["cash"] -= entry * o["quantity"]
        st["keys"].append(key)
        pos = {"option": s["option"], "underlying": s["symbol"], "qty": o["quantity"], "entry": entry,
               "entry_at": at, "signal_at": s["signal_at"], "ltp": s["ltp"], "delta": s.get("delta")}
        st["open"].append(pos)
        if shadow:
            sh["open"].append(dict(pos))
        st["orders"].append({"at": at, **o})
        out["bought"].append(s["option"])
        notify(f"PAPER BUY {s['option']} ({o['quantity']} qty)", f"Supertrend {s['trend']} at {s['signal_at']}; "
               f"₹{entry * o['quantity']:,.0f} premium. Paper only, nothing sent to Kite.", tags=["memo"], priority=3)

    # shadow book: same positions, sold only on a closed-candle flip (its quotes come from a second view call)
    if sh["open"]:
        # shortcut: highs keyed by option, so the rare same option held twice in the shadow shares the higher one
        sv = view(now, account=(0.0, _net(sh["open"]), [], st["day_open"]), touch=False,
                  peaks={p["option"]: max(x.get("peak", x["entry"]) for x in sh["open"] if x["option"] == p["option"])
                         for p in sh["open"]})
        for d in sv["positions"]:
            p = next(x for x in sh["open"] if x["option"] == d["option"] and x["entry"] == d["avg"])  # may hold it twice
            if d["ltp"]:
                p["ltp"] = d["ltp"]
            p["peak"] = max(p.get("peak", p["entry"]), d["ltp"] or 0.0)
            if d["action"] == "SELL" and d["ltp"]:
                out.setdefault("shadow_sold", []).append(_close(sh, p, d, at, now)["option"])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=1))
    out["balance"] = round(st["cash"] + sum(p["qty"] * p["ltp"] for p in st["open"]))
    return out
