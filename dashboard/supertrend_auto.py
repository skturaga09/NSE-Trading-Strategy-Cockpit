#!/usr/bin/env python3
"""
SUPERTREND AUTO EXITS — stage 2 of docs/supertrend-auto-plan.md (owner 2026-11-13). Entries stay manual.

Every minute in market hours (com.clade.supertrend -> POST /api/supertrend/check) for each option bought through the
Supertrend "Buy in Kite" ticket (Kite order tag STREND, kept in REG so overnight positions stay managed):
  exit rules say SELL  -> delete every active SELL GTT on the option (the owner's own too) and cancel any pending SL order,
                          then a LIMIT SELL of the whole position at the best bid (if any of those cannot be removed, do
                          NOT sell: a leftover stop could later sell short)
  sell still unfilled  -> after REPRICE_AFTER_S re-price to the new bid, at most MAX_REPRICES times, then phone alert
  HOLD, GTT in place   -> raise its trigger as the option makes new highs (trailing 25 % under the high, view()'s
                          backstop), only upwards and only in steps >= TRAIL_STEP; keep its quantity = the position's
  HOLD, no stop        -> a single-leg GTT SELL, trigger 25 % below the high since the buy (the buy price at first),
                          LIMIT 5 % under the trigger. A GTT on an NFO
                          contract lives until the contract expires (Zerodha GTT terms, NRML on NFO allowed), so it
                          covers overnight and a sleeping Mac; a day SL order would lapse at each close.
Leftover stop: an active single-leg SELL GTT on an NFO option no longer held (sold by hand) is deleted (owner
2026-11-18: an orphan ICICIBANK stop 16 % from its trigger could have sold short). Positions unreadable -> nothing.
Positions not bought with the STREND tag are never touched, unless the owner hands one over with manage() (the
"Auto-manage" button). A two-leg GTT the owner placed (stop + target) is never modified, so its target is not lost;
it is still deleted before an auto SELL, since a leftover leg could later sell short.

Switch: data/engine/supertrend_auto.json {"armed": false} by default. Off = dry run: what it WOULD send goes to LOG only.
No duplicate orders: the order book is read before every send; a live SELL for the option means "already selling".
A failed or timed-out send is not repeated for RESEND_WAIT_S (it may have reached Kite); the next try re-reads first.
Kite calls (DOC https://kite.trade/docs/connect/v3/orders/, read 2026-11-13): POST /orders/regular -> data.order_id;
PUT /orders/regular/:id (price); DELETE /orders/regular/:id; tag alphanumeric <= 20 chars. GTT (DOC
https://kite.trade/docs/connect/v3/gtt/, read 2026-11-13): POST /gtt/triggers form fields type, condition (JSON),
orders (JSON) -> data.trigger_id; PUT /gtt/triggers/:id; DELETE /gtt/triggers/:id; status "active" until it fires.
All over the IPv4 KITE session.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from dashboard.supertrend import IST

DATA = Path(__file__).resolve().parents[1] / "data" / "engine"
SWITCH, REG, LOG = DATA / "supertrend_auto.json", DATA / "supertrend_auto_positions.json", DATA / "supertrend_auto_log.jsonl"
ENTRY_TAG, EXIT_TAG = "STREND", "STRENDX"
LIVE = {"OPEN", "TRIGGER PENDING", "OPEN PENDING", "PUT ORDER REQ RECEIVED", "VALIDATION PENDING",
        "MODIFY VALIDATION PENDING", "MODIFY PENDING", "CANCEL PENDING", "AMO REQ RECEIVED"}   # not yet final
REPRICE_AFTER_S, MAX_REPRICES, RESEND_WAIT_S = 60, 3, 180
_ORPHANS_SAID: set = set()   # leftover-stop GTT ids already logged in this server process (log/alert once, retry quietly)
TRAIL_STEP = 0.02    # raise the GTT trigger only when the trailing stop has moved up >= 2 % (fewer modifications)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def is_armed() -> bool:
    return bool(_read(SWITCH, {}).get("armed"))


def set_armed(on: bool) -> Dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    SWITCH.write_text(json.dumps({"armed": bool(on), "changed": datetime.now(IST).isoformat(timespec="seconds")}))
    return {"armed": bool(on)}


def manage(tsym: str, on: bool, held: set) -> Dict[str, Any]:
    """Hand a held option to auto exits (on) or take it back (off). Only options held right now can be handed over."""
    reg = _read(REG, {})
    if on:
        if tsym not in held:
            raise ValueError(f"{tsym} is not an option you hold right now")
        reg.setdefault(tsym, {"since": datetime.now(IST).isoformat(timespec="seconds"), "adopted": True})
    else:
        reg.pop(tsym, None)
    DATA.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(reg, indent=1))
    return {"managed": sorted(reg)}


def _send(method: str, path: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from dashboard import supertrend_trades as T
    j = T.KITE.request(method, f"https://api.kite.trade{path}", data=data, headers=T._headers(), timeout=10).json()
    if j.get("status") != "success":
        raise RuntimeError(j.get("message") or f"{method} {path} failed")
    return j["data"]


def _bid(tsym: str) -> float:
    from dashboard import supertrend_trades as T
    q = T._get("/quote", [("i", f"NFO:{tsym}")]).get(f"NFO:{tsym}") or {}
    return float((((q.get("depth") or {}).get("buy") or [{}])[0]).get("price") or 0.0)


def _tagged(o: Dict[str, Any], tag: str) -> bool:
    return o.get("tag") == tag or tag in (o.get("tags") or [])


def _when(o: Dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(o.get("order_timestamp"))).replace(tzinfo=IST)


def step(now: Optional[datetime] = None, v: Optional[Dict[str, Any]] = None, notify: Optional[Callable] = None,
         send: Callable = _send, bid: Callable = _bid) -> Dict[str, Any]:
    """One minute of auto exits. v = supertrend_trades.view() of the real account (read here if not given)."""
    from dashboard import supertrend_trades as T
    now = now or datetime.now(IST)
    v = v or T.view(now)
    out: Dict[str, Any] = {"armed": is_armed(), "actions": [], "errors": []}
    if "account" not in v:                         # account unreadable: never act (or forget positions) on a blank view
        out["errors"] = v.get("errors") or ["Kite account not readable"]
        return out
    if notify is None:
        from dashboard.exit_monitor import notify
    orders = T._get("/orders") or []
    gtts = [g for g in (T._get("/gtt/triggers") or []) if g.get("status") == "active"]
    held = {p["option"]: p for p in v["positions"]}
    reg = _read(REG, {})
    for o in orders:
        if _tagged(o, ENTRY_TAG) and o.get("transaction_type") == "BUY" and o.get("status") == "COMPLETE" \
                and o.get("tradingsymbol") in held:
            reg.setdefault(o["tradingsymbol"], {"since": str(o.get("order_timestamp"))})
    reg = {k: r for k, r in reg.items() if k in held}            # sold (by us, the SL or by hand): stop managing it
    at = now.isoformat(timespec="seconds")

    def act(tsym: str, what: str, why: str, data: Optional[dict] = None, **extra) -> None:
        rec = {"at": at, "option": tsym, "action": what, "why": why, "armed": out["armed"], **extra}
        if data:
            rec["order"] = data
        out["actions"].append(rec)
        DATA.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        if out["armed"]:
            notify(f"AUTO {what}: {tsym}", why, tags=["robot"], priority=5 if "FAILED" in what or "ALERT" in what else 4)

    # A SELL GTT on an option you no longer hold (sold by hand, outside auto exits) could later sell short: delete it.
    # Positions read raw (not view()'s F&O-stock list) so a held index option keeps its stop; unreadable -> touch nothing.
    try:
        owned = {p.get("tradingsymbol") for p in (T._get("/portfolio/positions") or {}).get("net") or []
                 if int(p.get("quantity") or 0) != 0}
    except Exception as e:
        owned = None
        out["errors"].append(f"positions not readable, leftover stops not checked: {e}")
    for g in gtts if owned is not None else []:
        c, legs = g.get("condition") or {}, g.get("orders") or []
        if g.get("type") != "single" or c.get("exchange") != "NFO" or c.get("tradingsymbol") in owned \
                or not legs or any(o.get("transaction_type") != "SELL" for o in legs):
            continue                                   # the owner's two-leg GTT is never touched here
        tsym = c.get("tradingsymbol")
        why = (f"SELL {legs[0].get('quantity')} qty, trigger ₹{(c.get('trigger_values') or ['?'])[0]}: "
               "you no longer hold this option, so it could sell short")
        if not out["armed"]:
            if g["id"] not in _ORPHANS_SAID:
                _ORPHANS_SAID.add(g["id"])
                act(tsym, "WOULD DELETE LEFTOVER STOP", why, delete_gtt=[g["id"]])
            continue
        try:
            send("DELETE", f"/gtt/triggers/{g['id']}")
            act(tsym, "LEFTOVER STOP DELETED", why, trigger_id=g["id"])
        except Exception as e:                         # retried every minute, alerted once
            if g["id"] not in _ORPHANS_SAID:
                _ORPHANS_SAID.add(g["id"])
                act(tsym, "LEFTOVER STOP DELETE FAILED", f"{str(e)[:120]}: delete this GTT in Kite yourself")

    for tsym, r in reg.items():
        p = held[tsym]
        mine = [o for o in orders if o.get("tradingsymbol") == tsym and o.get("transaction_type") == "SELL"
                and o.get("status") in LIVE]
        stops = [o for o in mine if o.get("order_type") in ("SL", "SL-M")]
        my_gtts = [g for g in gtts if (g.get("condition") or {}).get("tradingsymbol") == tsym
                   and any(o.get("transaction_type") == "SELL" for o in g.get("orders") or [])]
        sells = [o for o in mine if o.get("order_type") == "LIMIT"]
        if r.get("wait_until") and now < datetime.fromisoformat(r["wait_until"]):
            continue
        if p["action"] == "SELL":
            if sells:                                   # already selling: re-price a stale LIMIT, never add a second
                o = sells[0]
                if (now - _when(o)).total_seconds() < REPRICE_AFTER_S * (r.get("reprices", 0) + 1):
                    continue
                if r.get("reprices", 0) >= MAX_REPRICES:
                    if not r.get("stuck_alerted"):
                        r["stuck_alerted"] = True
                        act(tsym, "ALERT", f"sell order still not filled after {MAX_REPRICES} re-prices: sell it in Kite")
                    continue
                b = bid(tsym)
                if not b or b == o.get("price"):
                    continue
                data = {"price": b}
                if out["armed"]:
                    try:
                        send("PUT", f"/orders/regular/{o['order_id']}", data)
                    except Exception as e:
                        act(tsym, "REPRICE FAILED", str(e)[:160])
                        continue
                r["reprices"] = r.get("reprices", 0) + 1
                act(tsym, "REPRICE", f"sell not filled: price ₹{o.get('price')} -> bid ₹{b}", data)
                continue
            b = bid(tsym)
            if not b:
                if r.get("nobid_day") != now.date().isoformat():
                    r["nobid_day"] = now.date().isoformat()
                    act(tsym, "ALERT", f"{p['why']}, but no buyer in the market: sell it in Kite yourself")
                continue
            data = {"tradingsymbol": tsym, "exchange": "NFO", "transaction_type": "SELL", "order_type": "LIMIT",
                    "quantity": int(p["qty"]), "product": "NRML", "price": b, "validity": "DAY", "tag": EXIT_TAG}
            if not out["armed"]:
                if r.get("dry") != p["why"]:                # log each new reason once, not every minute
                    r["dry"] = p["why"]
                    act(tsym, "WOULD SELL", p["why"], data, cancel=[o["order_id"] for o in stops],
                        delete_gtt=[g["id"] for g in my_gtts])
                continue
            try:
                for g in my_gtts:
                    send("DELETE", f"/gtt/triggers/{g['id']}")
                for o in stops:
                    send("DELETE", f"/orders/regular/{o['order_id']}")
            except Exception as e:
                r["wait_until"] = (now + timedelta(seconds=RESEND_WAIT_S)).isoformat()
                act(tsym, "SELL FAILED", f"could not cancel the stop-loss ({str(e)[:120]}), so not selling: check Kite")
                continue
            try:
                oid = send("POST", "/orders/regular", data).get("order_id")
                r["reprices"] = 0
                act(tsym, "SELL", p["why"], data, order_id=oid)
            except Exception as e:
                r["wait_until"] = (now + timedelta(seconds=RESEND_WAIT_S)).isoformat()   # it may have reached Kite
                act(tsym, "SELL FAILED", f"{str(e)[:120]}; not resent for {RESEND_WAIT_S // 60} min: check Kite", data)
        elif p["action"] == "HOLD" and not stops and p.get("backstop") and p.get("ltp"):
            b, qty = p["backstop"][0], int(p["qty"])
            if my_gtts and not any(g.get("type") == "single" for g in my_gtts):
                if r.get("dry") != "two-leg":              # the owner's stop + target GTT: leave it as it is
                    r["dry"] = "two-leg"
                    act(tsym, "KEEPING YOUR GTT", "your two-leg GTT stays as you set it (not trailed); "
                        "it is deleted before an auto sell")
                continue
            if my_gtts:                                 # trail it up; keep its quantity equal to the position
                g = next(g for g in my_gtts if g.get("type") == "single")
                cur, cur_lim = g["condition"]["trigger_values"][0], g["orders"][0]["price"]
                up = cur * (1 + TRAIL_STEP) <= b["trigger_price"] < p["ltp"]      # never down, never at once
                if not up and all(int(o.get("quantity") or 0) == qty for o in g.get("orders") or []):
                    continue
                trig, lim = (b["trigger_price"], b["price"]) if up else (cur, cur_lim)
                how, path = "PUT", f"/gtt/triggers/{g['id']}"
            elif b["trigger_price"] >= p["ltp"]:        # would fire at once; the premium-stop SELL handles that case
                continue
            else:
                trig, lim, how, path = b["trigger_price"], b["price"], "POST", "/gtt/triggers"
            data = {"type": "single",
                    "condition": json.dumps({"exchange": "NFO", "tradingsymbol": tsym, "trigger_values": [trig],
                                             "last_price": p["ltp"]}),
                    "orders": json.dumps([{"exchange": "NFO", "tradingsymbol": tsym, "transaction_type": "SELL",
                                           "quantity": qty, "order_type": "LIMIT", "product": "NRML", "price": lim}])}
            what = "STOP-LOSS GTT" if how == "POST" else "STOP-LOSS RAISED" if trig != cur else "STOP-LOSS GTT QTY"
            if not out["armed"]:
                if r.get("dry") != f"{what} {trig} {qty}":
                    r["dry"] = f"{what} {trig} {qty}"
                    act(tsym, "WOULD PLACE " + what, f"trigger ₹{trig}, sell LIMIT ₹{lim}, {qty} qty", data)
                continue
            try:
                tid = send(how, path, data).get("trigger_id")
                act(tsym, what, f"in Zerodha until expiry: trigger ₹{trig}, sell LIMIT ₹{lim}, {qty} qty", data,
                    trigger_id=tid)
            except Exception as e:
                r["wait_until"] = (now + timedelta(seconds=RESEND_WAIT_S)).isoformat()
                act(tsym, "STOP-LOSS FAILED", str(e)[:160], data)
    DATA.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(reg, indent=1))
    out["managed"] = sorted(reg)
    return out


ENTRY_SWITCH, BOUGHT = DATA / "supertrend_auto_entries.json", DATA / "supertrend_auto_buys.json"
# Owner 2026-11-20: the real account's strategy. Off (default) = the live rules (10 % day loss budget, max 4 open, lots to
# fit). On = the paper main book's rules: no day loss budget, no 4-open cap, 1 lot; cash and 20 orders a day decide.
STRATEGY = DATA / "supertrend_strategy.json"
BUY_WAIT_S = 300      # stage 3: a buy not filled in 5 minutes is cancelled (the price has moved on)


def entries_armed() -> bool:
    return bool(_read(ENTRY_SWITCH, {}).get("armed"))


def set_entries(on: bool) -> Dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    ENTRY_SWITCH.write_text(json.dumps({"armed": bool(on), "changed": datetime.now(IST).isoformat(timespec="seconds")}))
    return {"entries": bool(on)}


def no_limits() -> bool:
    return bool(_read(STRATEGY, {}).get("no_limits"))


def set_no_limits(on: bool) -> Dict[str, Any]:
    DATA.mkdir(parents=True, exist_ok=True)
    STRATEGY.write_text(json.dumps({"no_limits": bool(on), "changed": datetime.now(IST).isoformat(timespec="seconds")}))
    return {"no_limits": bool(on)}


def enter(now: Optional[datetime] = None, v: Optional[Dict[str, Any]] = None, notify: Optional[Callable] = None,
          send: Callable = _send) -> Dict[str, Any]:
    """STAGE 3 AUTO ENTRIES: buy what view() marks TAKE — 1 lot, LIMIT at the ask, tag STREND — and cancel our own buy if
    it is not filled within BUY_WAIT_S. step() then manages the filled buy (GTT stop, exits) like a ticket buy.
    Sends only when BOTH switches are on (an entry without auto exits would have no stop). Off = WOULD BUY in the log.
    Never twice per signal (marked before the send, so a timeout is never resent); one pending buy at a time;
    nothing on any Kite read error; a failed send switches entries off (kill switch) and alerts the phone, except Zerodha's
    physical-delivery refusal: that stops stock option buys for the day only (index options go on)."""
    from dashboard import supertrend_trades as T
    from dashboard.option_chain import INDEX_SYM
    now = now or datetime.now(IST)
    v = v or T.view(now)
    out: Dict[str, Any] = {"armed": entries_armed() and is_armed(), "actions": [], "errors": []}
    if "account" not in v or v.get("errors"):
        out["errors"] = v.get("errors") or ["Kite account not readable"]
        return out
    if notify is None:
        from dashboard.exit_monitor import notify
    day = now.date().isoformat()
    book = _read(BOUGHT, {})
    if book.get("day") != day:
        book = {"day": day, "signals": [], "orders": {}}
    at = now.isoformat(timespec="seconds")

    def act(tsym: str, what: str, why: str, data: Optional[dict] = None, **extra) -> None:
        rec = {"at": at, "option": tsym, "action": what, "why": why, "armed": out["armed"], **extra}
        if data:
            rec["order"] = data
        out["actions"].append(rec)
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        if out["armed"]:
            notify(f"AUTO {what}: {tsym}", why, tags=["robot"], priority=5)

    orders = T._get("/orders") or []
    pending = [o for o in orders if o.get("order_id") in book["orders"] and o.get("status") in LIVE]
    for o in pending:                                  # our buy still unfilled after 5 min: cancel it
        r = book["orders"][o["order_id"]]
        if out["armed"] and not r.get("cancel_sent") and (now - _when(o)).total_seconds() >= BUY_WAIT_S:
            r["cancel_sent"] = True
            try:
                send("DELETE", f"/orders/regular/{o['order_id']}")
                act(o["tradingsymbol"], "BUY CANCELLED", f"not filled in {BUY_WAIT_S // 60} min at ₹{o.get('price')}")
            except Exception as e:
                act(o["tradingsymbol"], "CANCEL FAILED", f"{str(e)[:120]}: cancel the buy in Kite yourself")
    ordered = {o.get("tradingsymbol") for o in orders if o.get("transaction_type") == "BUY"}
    for s in v["signals"]:
        key = f"{s['symbol']}|{s['signal_at']}"
        if s["verdict"] != "TAKE" or key in book["signals"] or s["option"] in ordered:
            continue                                   # already sent, or you bought / tried it yourself today
        if book.get("stock_block") and s["symbol"] not in INDEX_SYM:
            continue                                   # Zerodha refused a stock option buy today (physical delivery)
        if pending and out["armed"]:
            break                                      # one buy at a time; a fresh signal is retried next minute
        # shortcut: always 1 lot (paper sizing, D-80); use s["lots"] once live fills match paper for 10+ days
        data = {"tradingsymbol": s["option"], "exchange": "NFO", "transaction_type": "BUY", "order_type": "LIMIT",
                "quantity": int(s["lot"]), "product": "NRML", "price": s["ask"], "validity": "DAY", "tag": ENTRY_TAG}
        book["signals"].append(key)
        why = f"{s['symbol']} turned {s['trend']} at {s['signal_at']}: 1 lot = {data['quantity']} qty at ₹{s['ask']}"
        if s.get("strength") is not None:
            why += f" · {'STRONG' if s.get('strong') else 'WEAK'} candle {s['strength']:.1f}x normal"
        if not out["armed"]:
            act(s["option"], "WOULD BUY", why, data)
            continue
        try:
            oid = send("POST", "/orders/regular", data).get("order_id")
            book["orders"][oid] = {"key": key}
            pending = [data]
            act(s["option"], "BUY", why, data, order_id=oid)
        except Exception as e:
            if "physical delivery" in str(e).lower():  # Zerodha's expiry block: stock options only, not a fault
                book["stock_block"] = str(e)[:160]
                act(s["option"], "BUY REFUSED", f"Zerodha: {str(e)[:120]}. Stock option buys skipped for the rest of "
                    "today; index options go on", data)
                continue
            set_entries(False)
            out["armed"] = False
            act(s["option"], "BUY FAILED", f"{str(e)[:120]}. Auto entries switched OFF: check Kite", data)
            notify(f"AUTO BUY FAILED: {s['option']}", "Auto entries switched off. Check Kite.", tags=["robot"], priority=5)
            break
    DATA.mkdir(parents=True, exist_ok=True)
    BOUGHT.write_text(json.dumps(book, indent=1))
    return out


def status(n: int = 50) -> Dict[str, Any]:
    try:
        lines = LOG.read_text().splitlines()[-n:]
    except OSError:
        lines = []
    return {"armed": is_armed(), "entries": entries_armed(), "no_limits": no_limits(), "managed": _read(REG, {}),
            "log": [json.loads(x) for x in reversed(lines)]}
