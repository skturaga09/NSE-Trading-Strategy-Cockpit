#!/usr/bin/env python3
"""
IV rank — is a name's option IV high or low versus its OWN recent history?

An IV of 30% means nothing alone: cheap for one stock, rich for another. We keep one ATM-IV
reading per F&O name per trading day (journal.db `iv_history`) and rank today against it:
  IV rank       = (iv − min) / (max − min) over the lookback        (0 = cheapest, 100 = richest)
  IV percentile = % of lookback days with IV below today
  HV20          = realised 20-day volatility of the underlying; IV/HV > 1 = options price in
                  more movement than the stock is actually delivering.

ATM IV = mean of the ATM call and put IV on the nearest expiry with ≥ MIN_DTE days left (IV in
the final week is dominated by gamma/pin noise). Readings come from:
  • snapshot() — once a day after 15:20, riding the radar job via rec_ledger.tick();
  • backfill() — one-off: rebuilds past days from Kite daily candles of the CURRENTLY listed
    contracts, so history starts at the oldest live expiry's listing (~2–3 months), not a year.
A rank needs MIN_DAYS readings; until then it's reported as "building", never guessed.

CLI: `python3 -m dashboard.iv_rank snapshot|backfill [SYMBOL]|rank SYMBOL|selfcheck`.
"""

import math
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from dashboard import option_chain as oc
from dashboard.rec_ledger import DB_PATH, _now

MIN_DTE = 7          # skip an expiry with < 7 days left — roll to the next
MIN_DAYS = 20        # readings needed before a rank means anything
LOOKBACK = 252       # ~1 year once enough snapshots exist
SNAP_AFTER = "15:20"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS iv_history (
    date TEXT NOT NULL, symbol TEXT NOT NULL, atm_iv REAL NOT NULL,
    spot REAL, strike REAL, expiry TEXT, source TEXT,
    PRIMARY KEY (date, symbol)
);
"""


@contextmanager
def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _opt_index() -> Dict[str, Dict[str, Dict[float, Dict[str, Dict[str, str]]]]]:
    """name → expiry → strike → {CE,PE: instrument row}, from the NFO master (cached daily)."""
    idx: Dict[str, Any] = {}
    for r in oc._instruments():
        if r.get("segment") != "NFO-OPT" or r.get("instrument_type") not in ("CE", "PE"):
            continue
        try:
            k = float(r["strike"])
        except Exception:
            continue
        idx.setdefault(r["name"], {}).setdefault(r["expiry"], {}).setdefault(k, {})[r["instrument_type"]] = r
    return idx


def _pick_expiry(expiries: List[str], on: date) -> Optional[str]:
    ok = sorted(e for e in expiries if (date.fromisoformat(e) - on).days >= MIN_DTE)
    return ok[0] if ok else None


def _atm_iv(ce: Optional[float], pe: Optional[float], spot: float, k: float, T: float) -> Optional[float]:
    ivs = [v for v in (oc._iv(ce, spot, k, T, True) if ce else None,
                       oc._iv(pe, spot, k, T, False) if pe else None) if v]
    return round(sum(ivs) / len(ivs), 2) if ivs else None


def _save(rows: List[tuple]) -> int:
    with _conn() as c:
        cur = c.executemany(
            "INSERT OR REPLACE INTO iv_history (date, symbol, atm_iv, spot, strike, expiry, source) "
            "VALUES (?,?,?,?,?,?,?)", rows)
        return cur.rowcount


def _quotes(syms: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for i in range(0, len(syms), 400):          # Kite /quote takes ≤ 500 instruments
        j = requests.get("https://api.kite.trade/quote", params=[("i", s) for s in syms[i:i + 400]],
                         headers=oc._headers(), timeout=15).json()
        if j.get("status") == "success":
            out.update(j["data"])
    return out


def snapshot() -> Dict[str, Any]:
    """Today's ATM IV for every F&O underlying (stocks + indices), two batched /quote sweeps."""
    from dashboard.fno_scanner import fno_universe
    today = _now().date()
    names = fno_universe() + list(oc.INDEX_SYM)
    spots = _quotes([oc.spot_symbol(n) for n in names])
    idx = _opt_index()
    plan: Dict[str, Any] = {}
    for n in names:
        q = spots.get(oc.spot_symbol(n)) or {}
        # indices carry no last_trade_time — their tick timestamp serves the same staleness check
        spot, ltt = q.get("last_price"), str(q.get("last_trade_time") or q.get("timestamp") or "")
        if not spot or not ltt.startswith(today.isoformat()):   # holiday / stale → no fake reading
            continue
        exps = idx.get(n) or {}
        exp = _pick_expiry(list(exps), today)
        if not exp:
            continue
        k = min(exps[exp], key=lambda s: abs(s - spot))
        legs = exps[exp][k]
        if "CE" in legs and "PE" in legs:
            plan[n] = (spot, k, exp, legs["CE"]["tradingsymbol"], legs["PE"]["tradingsymbol"])
    oq = _quotes([f"NFO:{s}" for p in plan.values() for s in p[3:]])

    def px(sym: str) -> Optional[float]:
        d = oq.get(f"NFO:{sym}") or {}
        if not d.get("volume"):                 # untraded today → its LTP is a stale print
            return None
        b, a = ((d.get("depth") or {}).get("buy") or [{}])[0].get("price"), \
               ((d.get("depth") or {}).get("sell") or [{}])[0].get("price")
        return (b + a) / 2 if b and a else d.get("last_price")

    rows = []
    for n, (spot, k, exp, ce, pe) in plan.items():
        T = (date.fromisoformat(exp) - today).days / 365
        iv = _atm_iv(px(ce), px(pe), spot, k, T)
        if iv:
            rows.append((today.isoformat(), n, iv, spot, k, exp, "snapshot"))
    _save(rows)
    return {"date": today.isoformat(), "saved": len(rows), "universe": len(names)}


def maybe_snapshot() -> Optional[Dict[str, Any]]:
    """Once per trading day after 15:20 — cheap no-op if today's snapshot already exists."""
    now = _now()
    if now.weekday() >= 5 or now.strftime("%H:%M") < SNAP_AFTER:
        return None
    with _conn() as c:
        done = c.execute("SELECT COUNT(*) FROM iv_history WHERE date=? AND source='snapshot'",
                         (now.strftime("%Y-%m-%d"),)).fetchone()[0]
    return None if done else snapshot()


def _hist(token: Any, frm: str, to: str) -> List[List[Any]]:
    try:
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/day",
                         params={"from": frm, "to": to}, headers=oc._headers(), timeout=15).json()
        return j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        return []


def backfill(only: Optional[str] = None) -> Dict[str, int]:
    """Rebuild past ATM IV from daily candles of the currently listed option contracts.
    shortcut: dates before the near expiry existed use the next expiry (a longer tenor, so a
    slightly different IV) and expired contracts are gone from Kite — history is ~2–3 months.
    Never overwrites a live snapshot row."""
    from dashboard.liquidity_sweep import _eq_tokens
    eq = _eq_tokens()
    idx = _opt_index()
    today = _now().date()
    frm = (today - timedelta(days=100)).isoformat()
    with _conn() as c:                                  # resumable: skip names already backfilled
        done = {r[0] for r in c.execute("SELECT DISTINCT symbol FROM iv_history WHERE source='backfill'")}
    names = [only.upper()] if only else sorted(n for n in eq if n in idx and n not in done)
    saved = 0
    for i, n in enumerate(names):
        if n not in eq or n not in idx:
            continue
        spot_bars = _hist(eq[n], frm, today.isoformat())
        time.sleep(0.35)
        want: Dict[tuple, Dict[str, str]] = {}           # (exp, strike) → legs, per past day
        days: List[tuple] = []
        for b in spot_bars:
            d = date.fromisoformat(b[0][:10])
            if d >= today:
                continue
            exp = _pick_expiry(list(idx[n]), d)
            if not exp:
                continue
            k = min(idx[n][exp], key=lambda s: abs(s - b[4]))
            days.append((d, b[4], exp, k))
            want[(exp, k)] = idx[n][exp][k]
        candles: Dict[str, Dict[str, List[Any]]] = {}   # tradingsymbol → date → candle
        for legs in want.values():
            for row in legs.values():
                cs = _hist(row["instrument_token"], frm, today.isoformat())
                time.sleep(0.35)
                candles[row["tradingsymbol"]] = {c[0][:10]: c for c in cs}
        rows = []
        for d, spot, exp, k in days:
            legs = idx[n][exp][k]

            def close(t: str) -> Optional[float]:
                c = candles.get(legs[t]["tradingsymbol"], {}).get(d.isoformat()) if t in legs else None
                return c[4] if c and c[5] else None        # untraded that day → skip
            iv = _atm_iv(close("CE"), close("PE"), spot, k, (date.fromisoformat(exp) - d).days / 365)
            if iv:
                rows.append((d.isoformat(), n, iv, spot, k, exp, "backfill"))
        with _conn() as c:
            have = {r[0] for r in c.execute("SELECT date FROM iv_history WHERE symbol=? AND source='snapshot'", (n,))}
        saved += _save([r for r in rows if r[0] not in have])
        if (i + 1) % 20 == 0:
            print(f"  …{i + 1}/{len(names)} names, {saved} readings", file=sys.stderr)
    return {"names": len(names), "saved": saved}


def _hv20(underlying: str) -> Optional[float]:
    from dashboard.fno_scanner import _daily
    q = _quotes([oc.spot_symbol(underlying)]).get(oc.spot_symbol(underlying)) or {}
    tok = q.get("instrument_token")
    closes = [c[4] for c in _daily(tok)][-21:] if tok else []
    return _realised(closes)


def _realised(closes: List[float]) -> Optional[float]:
    """Annualised close-to-close volatility, %."""
    if len(closes) < 11:
        return None
    r = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    m = sum(r) / len(r)
    return round(math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252) * 100, 1)


def _rank_of(ivs: List[float]) -> Dict[str, Any]:
    cur, lo, hi = ivs[-1], min(ivs), max(ivs)
    return {"iv": cur, "iv_lo": lo, "iv_hi": hi,
            "iv_rank": round((cur - lo) / (hi - lo) * 100) if hi > lo else 50,
            "iv_pct": round(sum(1 for v in ivs[:-1] if v < cur) / max(len(ivs) - 1, 1) * 100)}


def rank(underlying: str, live_iv: Optional[float] = None) -> Dict[str, Any]:
    """IV rank/percentile vs stored history (+ today's live ATM IV if given), and IV/HV20."""
    u = underlying.upper()
    with _conn() as c:
        hist = [(r["date"], r["atm_iv"]) for r in c.execute(
            "SELECT date, atm_iv FROM iv_history WHERE symbol=? ORDER BY date DESC LIMIT ?", (u, LOOKBACK))]
    hist.reverse()
    today = _now().strftime("%Y-%m-%d")
    ivs = [v for d, v in hist if not (live_iv and d == today)] + ([live_iv] if live_iv else [])
    out: Dict[str, Any] = {"symbol": u, "days": len(ivs), "since": hist[0][0] if hist else None,
                           "iv": ivs[-1] if ivs else None, "iv_rank": None, "iv_pct": None,
                           "hv20": None, "iv_hv": None, "label": "NO DATA"}
    try:
        out["hv20"] = _hv20(u)
    except Exception:
        pass
    if out["iv"] and out["hv20"]:
        out["iv_hv"] = round(out["iv"] / out["hv20"], 2)
    if len(ivs) < MIN_DAYS:
        out["label"] = f"BUILDING ({len(ivs)}/{MIN_DAYS} days)" if ivs else "NO DATA"
        return out
    out.update(_rank_of(ivs))
    out["label"] = "HIGH" if out["iv_rank"] >= 70 else "LOW" if out["iv_rank"] <= 30 else "MID"
    return out


def _selfcheck() -> None:
    r = _rank_of([20.0, 30.0, 40.0, 25.0])
    assert r["iv_rank"] == 25 and r["iv_pct"] == 33 and r["iv_lo"] == 20 and r["iv_hi"] == 40
    assert _rank_of([30.0, 30.0])["iv_rank"] == 50                  # flat history → mid, no /0
    assert _realised([100.0] * 21) == 0.0
    assert _realised([100.0] * 5) is None                           # too short → None, not a guess
    assert _pick_expiry(["2026-11-05", "2026-11-26"], date(2026, 11, 2)) == "2026-11-26"  # 3 DTE → roll
    k, S, T = 100.0, 100.0, 30 / 365
    iv = _atm_iv(oc._bs(S, k, T, 0.3, True), oc._bs(S, k, T, 0.3, False), S, k, T)
    assert abs(iv - 30.0) < 0.5, iv                                  # BS round trip
    print("selfcheck ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selfcheck"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "snapshot":
        print(snapshot())
    elif cmd == "backfill":
        print(backfill(arg))
    elif cmd == "rank":
        print(rank(arg or "NIFTY"))
    else:
        _selfcheck()
