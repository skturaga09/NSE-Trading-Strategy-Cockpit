#!/usr/bin/env python3
"""
SUPERTREND ORDER TICKETS — the owner's Supertrend rules turned into one-click Kite orders (owner request 2026-11-13).

The dashboard only FILLS IN Kite's own order window (Kite Publisher basket: new KiteConnect(api_key).add(order).connect(),
https://kite.trade/docs/connect/v3/publisher/ and https://kite.trade/publisher.js); the owner reviews each order in Kite
and presses Buy / Sell there. Nothing in this module places, modifies or cancels an order: every Kite call is a GET.

Entry (a BUY ticket) for a 5-minute Supertrend(10,3) flip whose candle closed before 14:00 with the 15-minute trend
agreeing, while it is fresh (<= FRESH_MIN minutes old): the 1-strike-in-the-money option of the current month
(nearest expiry after today), LIMIT at the best ask (depth.sell[0], /quote F-QUOTE-3), product NRML (held overnight OK).
The last traded price can be minutes old on a thin strike (paper replay 2-12 Nov 2026: SBILIFE "bought" at ₹41.46 when the
first real trade was ₹51.86), so: no seller -> SKIP; bid-ask gap over MAX_SPREAD -> SKIP; lots <= quantity offered at the ask.
The owner's limits decide TAKE / SKIP: max 4 open, 5 buys a day, one position per stock.
Lots (owner 2026-11-13, option 2): as many as fit BOTH the free cash (booked profit is reused the same day) AND the day's
loss budget = balance - 90 % of the morning balance - what the open options can still lose (RISK of what was paid each).
The balance = cash + what was paid for the open options, so only booked P&L moves it.

Exit, for each option the owner holds on an F&O stock (read from Kite positions):
  SELL now  the option trades 25 % below its highest price since the buy (trailing premium stop, owner 2026-11-13; never
            below 25 % under the buy; highs are taken from each reading, kept in _PEAKS for the real account)
            · the stock crossed its 5-minute Supertrend line (or the 5-minute trend flipped against the position)
            · 15:15 and the 5-minute and 15-minute trends are not both still with the position
            · expiry day from 15:00
  HOLD      otherwise, with the stop shown as a stock price (the line, which only moves in the position's favour)
Optional backstop ticket: a stop-loss SELL on the option 25 % below the average buy price (it then sits in Zerodha);
offered only for positions already held, never with the BUY, so it can't turn into a short if the buy doesn't fill.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from dashboard.supertrend import IST, LAST_ALERT, board

FRESH_MIN = 15                  # a signal older than this is shown as missed: its price has moved on
LIMITS = {"max_open": 4, "max_buys_per_day": 5, "day_loss_pct": 0.10}       # D-78
SL_FRACTION, SL_LIMIT_GAP = 0.75, 0.05   # premium stop / backstop trigger 25 % below the buy; limit 5 % under it (ASSUMED)
MAX_SPREAD = 0.03                        # owner 2026-11-13: skip a buy when (ask - bid) / ask is wider than this
RISK = 0.30                              # loss per ₹ of premium at the 25 % stop + spread, slippage, charges (ASSUMED)
_DAY = Path(__file__).resolve().parents[1] / "data" / "engine" / "supertrend_day.json"
_PEAKS = Path(__file__).resolve().parents[1] / "data" / "engine" / "supertrend_peaks.json"   # real account: option -> high
_ALERTED = Path(__file__).parent / "supertrend_exit_alerts.json"


def _headers() -> Dict[str, str]:
    from dashboard.option_chain import _headers as h
    return h()


class _IPv4(requests.adapters.HTTPAdapter):
    """Zerodha's order whitelist is the IPv4 106.51.226.2; this Mac reaches api.kite.trade over IPv6 by default.
    Binding the socket to 0.0.0.0 makes every IPv6 attempt fail to bind, so urllib3 falls through to IPv4."""
    def init_poolmanager(self, *a, **kw):
        super().init_poolmanager(*a, source_address=("0.0.0.0", 0), **kw)


KITE = requests.Session()
KITE.mount("https://api.kite.trade", _IPv4())


def _get(path: str, params=None) -> Any:
    j = KITE.get(f"https://api.kite.trade{path}", params=params, headers=_headers(), timeout=10).json()
    if j.get("status") != "success":
        raise RuntimeError(j.get("message") or path)
    return j["data"]


def _tick(x: float, tick: float, up: bool) -> float:
    n = round(x / tick, 6)                         # 3.6 / 0.05 is 71.99999...: not a reason to move a tick
    n = int(n) + (1 if up and n != int(n) else 0)
    return round(n * tick, 2)


def pick_option(nfo: List[Dict[str, str]], underlying: str, kind: str, spot: float, today: str) -> Optional[Dict[str, str]]:
    """1 strike in the money, nearest expiry after today: CE one strike below the at-the-money strike, PE one above."""
    rows = [r for r in nfo if r["name"] == underlying and r["instrument_type"] == kind and r["expiry"] > today]
    if not rows:
        return None
    exp = min(r["expiry"] for r in rows)
    rows = sorted((r for r in rows if r["expiry"] == exp), key=lambda r: float(r["strike"]))
    strikes = [float(r["strike"]) for r in rows]
    atm = min(range(len(strikes)), key=lambda i: (abs(strikes[i] - spot), strikes[i]))
    j = atm - 1 if kind == "CE" else atm + 1
    return rows[j] if 0 <= j < len(rows) else None


def order(tradingsymbol: str, side: str, qty: int, order_type: str, price: float, trigger: Optional[float] = None) -> Dict[str, Any]:
    """One Kite Publisher basket entry (fields as in publisher.js); the owner can still edit it in Kite."""
    o = {"variety": "regular", "exchange": "NFO", "tradingsymbol": tradingsymbol, "transaction_type": side,
         "quantity": qty, "order_type": order_type, "price": price, "product": "NRML", "readonly": False, "tag": "STREND"}
    if trigger is not None:
        o["trigger_price"] = trigger
    return o


def exit_decision(kind: str, stock_ltp: Optional[float], row: Optional[Dict[str, Any]], expiry: str, now: datetime,
                  opt_ltp: Optional[float] = None, avg: Optional[float] = None, touch: bool = True,
                  peak: Optional[float] = None) -> Dict[str, Any]:
    """The owner's exit rules for one held option. -> {action: SELL | HOLD | UNKNOWN, why}.
    touch=False drops the line-touch stop, leaving the closed-candle flip (the paper shadow book's exit).
    peak = the option's highest price since the buy (before this reading): the premium stop trails 25 % under it."""
    want = "UP" if kind == "CE" else "DOWN"
    base = max(avg or 0.0, peak or 0.0)
    if opt_ltp and base and opt_ltp <= SL_FRACTION * base:
        return {"action": "SELL", "why": f"option at ₹{opt_ltp:,.2f} is 25 % below " +
                (f"its high ₹{base:,.2f} since your buy (trailing stop)" if base > (avg or 0.0) else
                 f"your buy ₹{base:,.2f} (premium stop)")}
    if row is None or stock_ltp is None:
        return {"action": "UNKNOWN", "why": "no Supertrend reading for this stock yet: watch it yourself"}
    hm = now.strftime("%H:%M")
    line = row["line"]
    if expiry == now.date().isoformat() and hm >= "15:00":
        return {"action": "SELL", "why": "expiry day: sell before the close"}
    if row["trend"] != want:
        return {"action": "SELL", "why": f"the 5-minute Supertrend turned {row['trend']}"}
    if touch and ((kind == "CE" and stock_ltp <= line) or (kind == "PE" and stock_ltp >= line)):
        return {"action": "SELL", "why": f"stock at ₹{stock_ltp:,.2f} crossed the Supertrend line ₹{line:,.2f}"}
    if "15:15" <= hm < "15:30" and row.get("trend_15m") != want:
        return {"action": "SELL", "why": "15:15: the 15-minute trend does not agree, so no overnight hold"}
    side = "below" if kind == "CE" else "above"
    return {"action": "HOLD", "why": f"stop: sell if the stock trades {side} ₹{line:,.2f} (the line moves only in your favour)"}


def _day_open(balance: float, today: str) -> float:
    """The real account's balance at its first reading of the day (kept in _DAY)."""
    try:
        d = json.loads(_DAY.read_text())
    except (OSError, ValueError):
        d = {}
    if d.get("day") != today:
        d = {"day": today, "day_open": balance}
        _DAY.parent.mkdir(parents=True, exist_ok=True)
        _DAY.write_text(json.dumps(d))
    return float(d["day_open"])


def view(now: Optional[datetime] = None, account: Optional[tuple] = None, touch: bool = True,
         max_lots: Optional[int] = None, peaks: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """account = (cash, net positions, today's orders, the morning balance) in Kite's shapes; None reads the real Kite account.
    supertrend_paper passes its paper account here, so paper and real go through the very same decisions."""
    from dashboard import app as core
    from dashboard.option_chain import _instruments, ensure_fresh_config
    now = now or datetime.now(IST)
    ensure_fresh_config()
    api_key = core.KITE_CONFIG.get("api_key")
    b = board()
    rows = {r["symbol"]: r for r in b.get("rows", [])}
    today = now.date().isoformat()
    out: Dict[str, Any] = {"at": now.isoformat(timespec="seconds"), "api_key": api_key, "board_bar": b.get("bar"),
                           "limits": LIMITS, "signals": [], "positions": [], "errors": []}
    try:
        cash, net, orders, *day_open = account or (
            float(((_get("/user/margins").get("equity") or {}).get("available") or {}).get("live_balance") or 0.0),
            _get("/portfolio/positions").get("net") or [], _get("/orders") or [])
    except Exception as e:
        out["errors"].append(f"Kite account not readable: {e}")
        return out
    nfo = _instruments()
    by_sym = {r["tradingsymbol"]: r for r in nfo}
    held = [p for p in net if p.get("exchange") == "NFO" and (p.get("quantity") or 0) > 0 and p["tradingsymbol"] in by_sym
            and by_sym[p["tradingsymbol"]]["instrument_type"] in ("CE", "PE")]
    buys_today = sum(1 for o in orders if o.get("exchange") == "NFO" and o.get("transaction_type") == "BUY"
                     and o.get("status") == "COMPLETE")
    pending_sl = {o["tradingsymbol"] for o in orders if o.get("transaction_type") == "SELL" and o.get("status") == "TRIGGER PENDING"}
    if account is None:                          # an active SELL GTT is a stop in Zerodha too: never offer a second one
        try:
            pending_sl |= {(g.get("condition") or {}).get("tradingsymbol") for g in (_get("/gtt/triggers") or [])
                           if g.get("status") == "active" and any(o.get("transaction_type") == "SELL" for o in g.get("orders") or [])}
        except Exception as e:
            out["errors"].append(f"GTTs not readable: {e}")
    paid = sum(float(p.get("average_price") or 0) * int(p["quantity"]) for p in held)
    balance = cash + paid
    day_open = day_open[0] if day_open else _day_open(balance, today)
    budget = balance - (1 - LIMITS["day_loss_pct"]) * day_open - RISK * paid
    out["account"] = {"cash": round(cash), "balance": round(balance), "day_open": round(day_open),
                      "budget": round(max(budget, 0)), "open": len(held), "buys_today": buys_today}

    # entries: today's eligible flips
    sig = []
    for r in rows.values():
        if not r.get("since") or r["since"][:10] != today or r.get("trend_15m") != r["trend"]:
            continue
        close = datetime.fromisoformat(r["since"]) + timedelta(minutes=5)
        if close.strftime("%H:%M") >= LAST_ALERT:
            continue
        kind = "CE" if r["trend"] == "UP" else "PE"
        opt = pick_option(nfo, r["symbol"], kind, r["close"], today)
        sig.append((r, close, kind, opt))
    quotes, book = {}, {}
    entry_syms = sorted({f"NFO:{o['tradingsymbol']}" for _, _, _, o in sig if o})
    for i in range(0, len(entry_syms), 500):                   # full quote with depth, 500 a request (F-QUOTE-1)
        try:
            for k, q in _get("/quote", [("i", s) for s in entry_syms[i:i + 500]]).items():
                quotes[k], book[k] = q.get("last_price"), q.get("depth") or {}
        except Exception as e:
            out["errors"].append(f"option quotes not readable: {e}")
    syms = [f"NFO:{p['tradingsymbol']}" for p in held] + [f"NSE:{by_sym[p['tradingsymbol']]['name']}" for p in held]
    for i in range(0, len(syms), 200):
        try:
            quotes.update({k: v.get("last_price") for k, v in _get("/quote/ltp", [("i", s) for s in syms[i:i + 200]]).items()})
        except Exception as e:
            out["errors"].append(f"prices not readable: {e}")
    held_names = {by_sym[p["tradingsymbol"]]["name"] for p in held}
    free, n_open, n_buys = cash, len(held), buys_today
    for r, close, kind, opt in sorted(sig, key=lambda x: x[1], reverse=True):
        s = {"symbol": r["symbol"], "trend": r["trend"], "signal_at": close.strftime("%H:%M"),
             "age_min": int((now - close).total_seconds() // 60), "stop_line": r["line"]}
        if opt is None:
            out["signals"].append({**s, "verdict": "SKIP", "why": f"no 1-strike-ITM {kind} listed"})
            continue
        k = f"NFO:{opt['tradingsymbol']}"
        sell0, buy0 = (((book.get(k) or {}).get(x) or [{}])[0] for x in ("sell", "buy"))     # best ask / best bid
        ask, bid, at_ask = sell0.get("price") or 0.0, buy0.get("price") or 0.0, int(sell0.get("quantity") or 0)
        ltp, lot = quotes.get(k), int(opt["lot_size"])
        s.update({"option": opt["tradingsymbol"], "lot": lot, "ltp": ltp, "ask": ask or None, "bid": bid or None,
                  "premium": round(ask * lot) if ask else None})
        gap = (ask - bid) / ask if ask and bid else 1.0
        lots = int(min(free // (ask * lot), budget // (RISK * ask * lot), at_ask // lot, max_lots or 10 ** 9)) if ask else 0
        why = ("missed: the signal is more than 15 minutes old" if s["age_min"] > FRESH_MIN else
               "no seller in the market for this option" if not ask else
               f"bid-ask gap {gap:.1%} is wider than {MAX_SPREAD:.0%}" if gap > MAX_SPREAD else
               f"only {at_ask} qty offered at the ask, less than 1 lot ({lot})" if at_ask < lot else
               "you already hold this stock" if r["symbol"] in held_names else
               "4 positions already open" if n_open >= LIMITS["max_open"] else
               "5 buys already today" if n_buys >= LIMITS["max_buys_per_day"] else
               f"not enough cash (₹{free:,.0f} free)" if ask * lot > free else
               f"day loss limit: ₹{max(budget, 0):,.0f} of budget left, 1 lot can lose ₹{RISK * ask * lot:,.0f}" if lots < 1
               else None)
        if why:
            out["signals"].append({**s, "verdict": "SKIP", "why": why})
            continue
        price = ask                                          # exchange prices are already on the tick
        out["signals"].append({**s, "lots": lots, "verdict": "TAKE", "why": "fits your rules",
                               "orders": [order(opt["tradingsymbol"], "BUY", lots * lot, "LIMIT", price)]})
        free, budget = free - lots * price * lot, budget - lots * RISK * price * lot    # the next fresh signal sees this one
        n_open, n_buys = n_open + 1, n_buys + 1

    # exits: options held
    real = peaks is None and account is None
    if real:
        try:
            peaks = json.loads(_PEAKS.read_text())
        except (OSError, ValueError):
            peaks = {}
    peaks, highs = peaks or {}, {}
    for p in held:
        ins = by_sym[p["tradingsymbol"]]
        und, kind, qty, tick = ins["name"], ins["instrument_type"], int(p["quantity"]), float(ins["tick_size"])
        ltp = quotes.get(f"NFO:{p['tradingsymbol']}") or p.get("last_price")
        avg = float(p.get("average_price") or 0.0)
        peak = max(avg, float(peaks.get(p["tradingsymbol"]) or 0.0))
        d = exit_decision(kind, quotes.get(f"NSE:{und}"), rows.get(und), ins["expiry"], now, ltp, avg, touch, peak)
        trig = _tick(peak * SL_FRACTION, tick, up=False)
        highs[p["tradingsymbol"]] = max(peak, ltp or 0.0)
        out["positions"].append({
            "option": p["tradingsymbol"], "underlying": und, "qty": qty, "avg": avg, "ltp": ltp,
            "high": highs[p["tradingsymbol"]],
            "pnl": round(p.get("pnl") or 0.0), "stock_ltp": quotes.get(f"NSE:{und}"), "line": rows.get(und, {}).get("line"),
            **d, "sl_in_zerodha": p["tradingsymbol"] in pending_sl,
            "sell": [order(p["tradingsymbol"], "SELL", qty, "LIMIT", _tick(ltp, tick, up=False))] if ltp else [],
            "backstop": [order(p["tradingsymbol"], "SELL", qty, "SL", _tick(trig * (1 - SL_LIMIT_GAP), tick, up=False), trig)]
            if avg else []})
    from dashboard.supertrend_auto import REG, _read
    managed = set(_read(REG, {}))
    for x in out["positions"]:
        x["managed"] = x["option"] in managed      # auto exits handles it (bought via the ticket, or handed over)
    if real and highs != peaks:                  # only held options are kept: a sold one starts fresh if bought again
        _PEAKS.parent.mkdir(parents=True, exist_ok=True)
        _PEAKS.write_text(json.dumps(highs))
    return out


def check_entries(send=None, now: Optional[datetime] = None, v: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every minute (com.clade.supertrend): one phone alert per TAKE signal (owner 2026-11-14: alert only what the rules
    say to take, not every flip). SKIP signals stay on the dashboard with their reason."""
    now = now or datetime.now(IST)
    v = v or view(now)
    try:
        seen = json.loads(_ALERTED.read_text())
    except (OSError, ValueError):
        seen = {}
    if seen.get("day") != now.date().isoformat():
        seen = {"day": now.date().isoformat(), "keys": []}
    sent = 0
    for s in v["signals"]:
        key = f"ENTRY|{s['symbol']}|{s['signal_at']}"
        if s["verdict"] != "TAKE" or key in seen["keys"]:
            continue
        if send is None:
            from dashboard.exit_monitor import notify as send
        o, side = s["orders"][0], "below" if s["trend"] == "UP" else "above"
        until = (datetime.strptime(s["signal_at"], "%H:%M") + timedelta(minutes=FRESH_MIN)).strftime("%H:%M")
        send(f"Supertrend BUY: {s['option']}",
             f"{s['symbol']} turned {s['trend']} at {s['signal_at']} (15-minute trend agrees).\n"
             f"Buy {s['lots']} lot{'s' if s['lots'] > 1 else ''} = {o['quantity']} qty, LIMIT ₹{o['price']:,.2f} "
             f"(about ₹{o['price'] * o['quantity']:,.0f}).\n"
             f"Stop: sell if {s['symbol']} trades {side} ₹{s['stop_line']:,.2f}.\n"
             f"Open the Supertrend tab and press Buy in Kite before {until}.",
             tags=["chart_with_upwards_trend" if s["trend"] == "UP" else "chart_with_downwards_trend"], priority=5)
        seen["keys"].append(key)
        sent += 1
    _ALERTED.write_text(json.dumps(seen))
    return {"take": sum(s["verdict"] == "TAKE" for s in v["signals"]), "alerts": sent}


def check_positions(send=None, now: Optional[datetime] = None, v: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Every minute (com.clade.supertrend): phone alert once per held option per exit reason per day."""
    now = now or datetime.now(IST)
    v = v or view(now)
    from dashboard import supertrend_auto as A
    auto = set(A._read(A.REG, {})) if A.is_armed() else set()      # auto exits is selling these: "press Sell" would
    sells = [p for p in v["positions"] if p["action"] == "SELL" and p["option"] not in auto]   # sell twice (short)
    try:
        seen = json.loads(_ALERTED.read_text())
    except (OSError, ValueError):
        seen = {}
    if seen.get("day") != now.date().isoformat():
        seen = {"day": now.date().isoformat(), "keys": []}
    sent = 0
    for p in sells:
        key = f"{p['option']}|{p['why'].split(':')[0]}"
        if key in seen["keys"]:
            continue
        if send is None:
            from dashboard.exit_monitor import notify as send
        send(f"Supertrend EXIT: sell {p['option']}", f"{p['why']}.\nOpen the Supertrend tab and press Sell in Kite "
             f"({p['qty']} qty).{' Cancel your stop-loss order in Kite too.' if p['sl_in_zerodha'] else ''}",
             tags=["rotating_light"], priority=5)
        seen["keys"].append(key)
        sent += 1
    _ALERTED.write_text(json.dumps(seen))
    return {"positions": len(v["positions"]), "sell_now": len(sells), "alerts": sent, "errors": v["errors"]}
