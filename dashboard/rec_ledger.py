#!/usr/bin/env python3
"""
Recommendation ledger — every call the platform makes, frozen at the moment it's made, then
scored against what actually happened. Answers "were the recommendations right?" so we can
course-correct with data instead of opinion.

Sources (one row per date+source+symbol+bias — the FIRST call wins, so time and price never
change; after 09:08 you still see exactly what was said, and when):
  gap       — real opening gaps (|gap| ≥ 1%), recorded once at the open (ref = open price).
              The gap radar claims MAGNITUDE ("a wide day"), so it is scored on range, not
              direction: hit = the day's range from the open ≥ the name's ADR.
  shortlist — names that first turn GO on the permission shortlist (ref = LTP then).
  radar     — ignition-radar fires (first fire per name per day).
              shortlist/radar are directional: hit = close is beyond the call price in the
              called direction.

Resolution (after the close): the 5-min path AFTER the call → MFE / MAE / close return / range,
all in the call's direction; next session → next-day close return. The scoreboard aggregates
per source with a minimum-sample guard. Read-only against Kite; places no orders.
"""

import json
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import requests

DB_PATH = Path(__file__).parent / "journal.db"
_FIRES = Path(__file__).parent / "logs" / "ignite_fires.jsonl"
IST = ZoneInfo("Asia/Kolkata")
MIN_SAMPLE = 30
GAP_MIN = 1.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rec_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL, ts TEXT NOT NULL, source TEXT NOT NULL,
    symbol TEXT NOT NULL, bias TEXT NOT NULL, ref_price REAL NOT NULL,
    score REAL, details TEXT,
    resolved INTEGER DEFAULT 0, close_price REAL, ret_close REAL,
    mfe REAL, mae REAL, range_pct REAL, next_close REAL, ret_next REAL,
    UNIQUE(date, source, symbol, bias)
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


def _now() -> datetime:
    return datetime.now(IST)


def record(source: str, symbol: str, bias: str, ref_price: float, score: Optional[float] = None,
           details: Optional[Dict[str, Any]] = None, ts: Optional[str] = None) -> bool:
    """Freeze a call. First call per (date, source, symbol, bias) wins — later calls are ignored
    so the record shows when it was FIRST made. Returns True if a new row was written."""
    if not (symbol and ref_price):
        return False
    ts = ts or _now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO rec_ledger (date, ts, source, symbol, bias, ref_price, score, details) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ts[:10], ts, source, symbol, bias, float(ref_price), score, json.dumps(details or {})))
        return cur.rowcount > 0


def _score_path(ref: float, d: int, path: List[List[Any]]) -> Optional[Dict[str, float]]:
    """Directional outcome of a call from its 5-min path AFTER the call. d=+1 long, -1 short.
    mfe ≥ 0 = best move in our favour; mae ≤ 0 = worst move against; range = high-low span."""
    if not path or not ref:
        return None
    hi, lo, close = max(c[2] for c in path), min(c[3] for c in path), path[-1][4]
    up, dn = (hi / ref - 1) * 100, (lo / ref - 1) * 100
    return {"close_price": close,
            "ret_close": round((close / ref - 1) * 100 * d, 2),
            "mfe": round(max(0.0, up if d == 1 else -dn), 2),
            "mae": round(min(0.0, dn if d == 1 else -up), 2),
            "range_pct": round((hi - lo) / ref * 100, 2)}


_TOKENS: Dict[str, Any] = {}


def _token(symbol: str) -> Optional[str]:
    if not _TOKENS:
        from dashboard.liquidity_sweep import _eq_tokens
        _TOKENS.update(_eq_tokens())
    return _TOKENS.get(symbol)


def _candles_5m(token: str, frm: str, to: str) -> List[List[Any]]:
    from dashboard.option_chain import _headers
    try:
        j = requests.get(f"https://api.kite.trade/instruments/historical/{token}/5minute",
                         params={"from": frm, "to": to}, headers=_headers(), timeout=15).json()
        return j.get("data", {}).get("candles", []) if j.get("status") == "success" else []
    except Exception:
        return []


def resolve(upto: Optional[str] = None) -> Dict[str, int]:
    """Score every unresolved call whose session has closed, and fill next-day returns where the
    next session now exists. One 5-min request per symbol covers all its calls (Kite allows
    ≤100 days per request) — shortcut: calls spanning >100 days need chunking, not hit today."""
    today = _now().strftime("%Y-%m-%d")
    after_close = _now().strftime("%H:%M") >= "15:35"
    upto = upto or (today if after_close else (date.fromisoformat(today) - timedelta(days=1)).isoformat())
    with _conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM rec_ledger WHERE (resolved=0 AND date<=?) OR (resolved=1 AND ret_next IS NULL AND date<?)",
            (upto, today))]
    by_sym: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], []).append(r)
    done = nexts = 0
    for sym, rs in by_sym.items():
        tok = _token(sym)
        if not tok:
            continue
        frm = min(r["date"] for r in rs) + " 09:15:00"
        to = (date.fromisoformat(max(r["date"] for r in rs)) + timedelta(days=7)).isoformat() + " 15:30:00"
        cs = _candles_5m(tok, frm, to)
        time.sleep(0.35)                        # stay under Kite's historical rate limit
        if not cs:
            continue
        sessions = sorted({k[0][:10] for k in cs})
        for r in rs:
            d = 1 if r["bias"] == "LONG" else -1
            upd: Dict[str, Any] = {}
            if not r["resolved"] and r["date"] <= upto:
                call_t = r["ts"][:16].replace(" ", "T")
                path = [k for k in cs if k[0][:10] == r["date"] and k[0][:16] >= call_t]
                s = _score_path(r["ref_price"], d, path)
                if s:
                    upd.update(s)
                    upd["resolved"] = 1
                    done += 1
            nxt = next((x for x in sessions if x > r["date"]), None)
            if nxt and nxt <= today and (nxt < today or after_close):
                nc = [k for k in cs if k[0][:10] == nxt]
                if nc:
                    upd["next_close"] = nc[-1][4]
                    upd["ret_next"] = round((nc[-1][4] / r["ref_price"] - 1) * 100 * d, 2)
                    nexts += 1
            if upd:
                with _conn() as c:
                    c.execute(f"UPDATE rec_ledger SET {', '.join(k + '=?' for k in upd)} WHERE id=?",
                              (*upd.values(), r["id"]))
    return {"resolved": done, "next_day": nexts, "symbols": len(by_sym)}


def backfill_radar() -> int:
    """Seed the ledger with every past ignition-radar first-fire (from ignite_fires.jsonl)."""
    if not _FIRES.exists():
        return 0
    seen, n = set(), 0
    for line in _FIRES.read_text().splitlines():
        try:
            f = json.loads(line)
        except Exception:
            continue
        key = (f.get("ts", "")[:10], f.get("symbol"))
        if not f.get("symbol") or key in seen:
            continue
        seen.add(key)
        n += record("radar", f["symbol"], f.get("bias", "LONG"), f.get("ltp"), f.get("score"),
                    {"vol_pace": f.get("vol_pace"), "day_pct": f.get("day_pct")}, ts=f["ts"])
    return n


def today_calls() -> Dict[str, Any]:
    """Today's frozen calls with live performance since each call (in its direction)."""
    from dashboard.option_chain import _headers
    day = _now().strftime("%Y-%m-%d")
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM rec_ledger WHERE date=? ORDER BY ts", (day,))]
    from dashboard.fno_scanner import _adr_pct
    from dashboard.news_sweep import for_symbols
    quotes: Dict[str, Any] = {}
    syms = sorted({r["symbol"] for r in rows})
    try:
        news = for_symbols(syms)                  # high-impact filings since the last close, per name
    except Exception:
        news = {}
    for i in range(0, len(syms), 200):
        try:
            j = requests.get("https://api.kite.trade/quote", params=[("i", f"NSE:{s}") for s in syms[i:i + 200]],
                             headers=_headers(), timeout=10).json()
            for k, v in (j.get("data") or {}).items():
                quotes[k.split(":", 1)[1]] = v
        except Exception:
            pass
    room: Dict[str, Optional[float]] = {}
    for s, q in quotes.items():
        o = q.get("ohlc") or {}
        pc, hi, lo = o.get("close"), o.get("high"), o.get("low")
        adr = _adr_pct(q.get("instrument_token")) if q.get("instrument_token") else None
        # Room left = the name's typical daily range (ADR) still unused today — the same
        # forward gauge as the scanner's "room left": near 0 means it has already run its day.
        room[s] = round(max(0.0, adr - (hi - lo) / pc * 100), 2) if (adr and pc and hi and lo) else None
    for r in rows:
        r["details"] = json.loads(r["details"] or "{}")
        now = (quotes.get(r["symbol"]) or {}).get("last_price")
        r["ltp"] = now
        r["since_pct"] = (round((now / r["ref_price"] - 1) * 100 * (1 if r["bias"] == "LONG" else -1), 2)
                          if now and r["ref_price"] else None)
        r["room_left_pct"] = room.get(r["symbol"])
        r["news"] = news.get(r["symbol"], [])
    return {"date": day, "calls": rows}


def scoreboard() -> Dict[str, Any]:
    """Per-source track record over all resolved calls. Directional sources: hit = closed beyond
    the call price in the called direction. Gap: hit = realised range from the open ≥ ADR."""
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM rec_ledger WHERE resolved=1")]
    out: Dict[str, Any] = {}
    for src in ("radar", "shortlist", "gap"):
        rs = [r for r in rows if r["source"] == src]
        n = len(rs)
        if not n:
            out[src] = {"n": 0}
            continue
        if src == "gap":
            pairs = [(r["range_pct"], json.loads(r["details"] or "{}").get("adr_pct")) for r in rs]
            pairs = [(rg, a) for rg, a in pairs if rg is not None and a]
            hits = sum(1 for rg, a in pairs if rg >= a)
            ratio = round(sum(rg / a for rg, a in pairs) / len(pairs), 2) if pairs else None
            s = {"n": n, "hit_pct": round(hits / len(pairs) * 100, 1) if pairs else None,
                 "range_vs_adr": ratio, "metric": "wide-day rate (range ≥ ADR)"}
        else:
            rets = [r["ret_close"] for r in rs if r["ret_close"] is not None]
            nxt = [r["ret_next"] for r in rs if r["ret_next"] is not None]
            s = {"n": n, "hit_pct": round(sum(1 for x in rets if x > 0) / len(rets) * 100, 1) if rets else None,
                 "avg_ret_close": round(sum(rets) / len(rets), 2) if rets else None,
                 "avg_mfe": round(sum(r["mfe"] for r in rs) / n, 2),
                 "avg_mae": round(sum(r["mae"] for r in rs) / n, 2),
                 "n_next": len(nxt),
                 "avg_ret_next": round(sum(nxt) / len(nxt), 2) if nxt else None,
                 "metric": "closed in the called direction"}
        s["verdict"] = "accumulating" if n < MIN_SAMPLE else (
            "working" if (s.get("hit_pct") or 0) >= 55 else "not working — demote" if (s.get("hit_pct") or 0) < 45 else "coin-flip")
        out[src] = s
    return out


def tick() -> Dict[str, Any]:
    """Ledger heartbeat — called from the ignition-radar job every few minutes. In session:
    freeze today's real gaps once, and any name newly GO on the shortlist. After 15:35:
    resolve today's calls. Cheap no-op otherwise."""
    now = _now()
    hm, weekday, day = now.strftime("%H:%M"), now.weekday() < 5, now.strftime("%Y-%m-%d")
    res: Dict[str, Any] = {"gap": 0, "shortlist": 0}
    if not weekday:
        return res
    from dashboard import fno_scanner, news_sweep
    try:                                          # morning + intraday filings sweep (throttled 30 min)
        res["news"] = news_sweep.maybe_sweep()
    except Exception as e:
        res["news_error"] = str(e)
    if "09:15" <= hm <= "15:30":
        with _conn() as c:
            have_gaps = c.execute("SELECT COUNT(*) FROM rec_ledger WHERE date=? AND source='gap'", (day,)).fetchone()[0]
        if not have_gaps:
            g = fno_scanner.premarket_scan(top=30)
            for r in g.get("gap_up", []) + g.get("gap_down", []):
                if abs(r["gap_pct"]) >= GAP_MIN:
                    res["gap"] += record("gap", r["symbol"], "LONG" if r["gap_pct"] > 0 else "SHORT", r["ref_price"],
                                         None, {"gap_pct": r["gap_pct"], "adr_pct": r.get("adr_pct"),
                                                "exp_range_pct": r.get("exp_range_pct")},
                                         ts=f"{day} 09:15:00")
        s = fno_scanner.shortlist()
        for r in s.get("names", []):
            if r["tier"] == "GO" and r.get("ltp"):
                res["shortlist"] += record("shortlist", r["symbol"], r["bias"], r["ltp"], None,
                                           {"why": r["why"], "regime": s.get("regime")})
    elif hm >= "15:35":
        with _conn() as c:
            pending = c.execute("SELECT COUNT(*) FROM rec_ledger WHERE date=? AND resolved=0", (day,)).fetchone()[0]
        if pending:
            res["resolved"] = resolve()
    return res


def _selfcheck() -> None:
    p = [["t1", 100, 105, 98, 103, 0], ["t2", 103, 104, 99, 101, 0]]
    s = _score_path(100.0, 1, p)                    # long: best +5, worst -2, closed +1
    assert s == {"close_price": 101, "ret_close": 1.0, "mfe": 5.0, "mae": -2.0, "range_pct": 7.0}, s
    s = _score_path(100.0, -1, p)                   # short: best +2 (fell to 98), worst -5, closed -1
    assert s["mfe"] == 2.0 and s["mae"] == -5.0 and s["ret_close"] == -1.0, s
    s = _score_path(100.0, 1, [["t", 101, 106, 101, 105, 0]])   # never adverse → mae 0
    assert s["mae"] == 0.0 and s["mfe"] == 6.0, s
    print("selfcheck ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selfcheck":
        _selfcheck()
    elif cmd == "backfill":
        n = backfill_radar()
        print(f"backfilled {n} radar calls; resolving…")
        print(resolve())
        print(json.dumps(scoreboard(), indent=2))
    elif cmd == "resolve":
        print(resolve())
    else:
        print(json.dumps(scoreboard(), indent=2))
