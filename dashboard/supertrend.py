#!/usr/bin/env python3
"""
SUPERTREND BOARD — every F&O stock and index, UP or DOWN on the owner's own chart setting:
Supertrend(10, 3) on 5-minute candles of the underlying (NSE spot), plus the same on 15-minute
candles (built from the 5-minute ones) so the board can show where both agree. Separate lane.

Why computed here: Kite chart alerts are not readable through the Kite Connect API
(GET /alerts lists only price/ATO alerts; it returned 0 for this account on 2026-11-13),
so the board recomputes the same indicator from Kite's 5-minute candles.

Standard Supertrend (TradingView `ta.supertrend` / Kite charts): ATR = Wilder's average
of true range over PERIOD; bands = (high+low)/2 -/+ MULT x ATR, each band only tightens
until price closes through it; the trend flips when a candle CLOSES beyond the band.
Closed candles only (no repaint), so a flip shows ~1-2 min after its 5-minute candle closes.

The com.clade.supertrend job POSTs /api/supertrend/check every minute; it scans once per new
closed candle (market hours only). Phone alerts are sent only for signals that pass the owner's rules
(supertrend_trades.check_entries: a TAKE verdict), not for every flip.
"""

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

from dashboard.option_chain import INDEX_SYM, _headers, _connected
from dashboard.fno_scanner import fno_universe

# The owner's Kite chart setting (answered 2026-11-13): change here if the chart setting changes.
PERIOD, MULT, INTERVAL, BAR_MIN = 10, 3.0, "5minute", 5
# Owner 2026-11-13: no alert for flips whose candle closes at/after 14:00 (real-option test: 23 % wins, -₹601 / trade)
LAST_ALERT = "14:00"
HISTORY_DAYS = 7          # calendar days of 5-minute candles: ~4-5 sessions, ATR(10) fully settled
REQ_GAP_S = 0.34          # Kite historical API: 3 requests / second
IST = ZoneInfo("Asia/Kolkata")
STRONG_MIN = 1.9         # flip candle body / ATR(14) at or above this = STRONG: top third of signals in the 28 Oct-17 Nov replay
_STATE = Path(__file__).parent / "supertrend_state.json"
_BUSY = threading.Lock()


def supertrend(candles: List[list], period: int = PERIOD, mult: float = MULT) -> List[Optional[Tuple[int, float]]]:
    """candles oldest first, each [ts, open, high, low, close, ...] -> per candle (direction, line):
    +1 = UP (line below price, the support), -1 = DOWN (line above price); None until ATR exists."""
    out: List[Optional[Tuple[int, float]]] = []
    atr = up = dn = None
    trs: List[float] = []
    d = -1
    for i, c in enumerate(candles):
        h, l, cl = float(c[2]), float(c[3]), float(c[4])
        pc = float(candles[i - 1][4]) if i else None
        tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
        if atr is None:
            trs.append(tr)
            if len(trs) < period:
                out.append(None)
                continue
            atr = sum(trs) / period
        else:
            atr = (atr * (period - 1) + tr) / period
        mid = (h + l) / 2
        bu, bd = mid - mult * atr, mid + mult * atr
        if up is not None:
            bu = bu if (bu > up or pc < up) else up      # support only rises, unless price already broke it
            bd = bd if (bd < dn or pc > dn) else dn      # resistance only falls, unless price already broke it
            d = (1 if cl > bd else -1) if d == -1 else (-1 if cl < bu else 1)
        up, dn = bu, bd
        out.append((d, up if d == 1 else dn))
    return out


def _bar_start(now: datetime) -> datetime:
    """Start of the newest CLOSED 5-minute candle at `now` (IST)."""
    t = now.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % BAR_MIN + BAR_MIN)


def _tokens() -> Dict[str, str]:
    """F&O stock -> NSE EQ instrument_token, plus the F&O indices' spot tokens."""
    import csv
    import io
    txt = requests.get("https://api.kite.trade/instruments/NSE", headers=_headers(), timeout=30).text
    rows = list(csv.DictReader(io.StringIO(txt)))
    eq = {r["tradingsymbol"]: r["instrument_token"] for r in rows if r.get("instrument_type") == "EQ"}
    idx = {r["tradingsymbol"]: r["instrument_token"] for r in rows if r.get("segment") == "INDICES"}
    out = {n: eq[n] for n in fno_universe() if n in eq}
    out.update({n: idx[s.split(":", 1)[1]] for n, s in INDEX_SYM.items() if s.split(":", 1)[1] in idx})
    return out


_PACE = threading.Lock()
_NEXT = [0.0]


def _pace() -> None:
    """Spaces request starts REQ_GAP_S apart across the scan's worker threads (Kite: 3 / second)."""
    with _PACE:
        wait = _NEXT[0] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _NEXT[0] = time.monotonic() + REQ_GAP_S


def _candles(token: str, now: datetime) -> List[list]:
    frm = (now - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d 09:00:00")
    for attempt in range(2):
        _pace()
        r = requests.get(f"https://api.kite.trade/instruments/historical/{token}/{INTERVAL}",
                         params={"from": frm, "to": now.strftime("%Y-%m-%d %H:%M:%S")}, headers=_headers(), timeout=10)
        if r.status_code == 429 and not attempt:     # rate limited: wait once
            time.sleep(1.0)
            continue
        j = r.json()
        if j.get("status") != "success":
            raise RuntimeError(j.get("message") or f"HTTP {r.status_code}")
        return j["data"]["candles"]
    raise RuntimeError("rate limited")


def to_15m(cs: List[list], closed_through: datetime) -> List[list]:
    """5-minute candles -> 15-minute candles aligned to 09:15 (as Kite builds them), CLOSED ones only:
    a 15-minute candle counts once its last 5-minute slot (start + 10 min) is at or before `closed_through`."""
    out: Dict[str, list] = {}
    for c in cs:
        t = datetime.fromisoformat(c[0])
        m = t.hour * 60 + t.minute - 555                     # minutes since 09:15
        start = t - timedelta(minutes=m % 15)
        if start + timedelta(minutes=10) > closed_through:
            continue
        k = start.isoformat()
        b = out.get(k)
        out[k] = [k, c[1], c[2], c[3], c[4], c[5]] if b is None else \
            [k, b[1], max(b[2], c[2]), min(b[3], c[3]), c[4], b[5] + c[5]]
    return list(out.values())


def _trend(cs: List[list]) -> Optional[Dict[str, Any]]:
    """Current Supertrend of these candles: trend, line, and the candle its run started on."""
    st = supertrend(cs)
    if not st or st[-1] is None:
        return None
    d, line = st[-1]

    def seg_start(k: int) -> int:   # first candle of the run of equal direction ending at k
        while k > 0 and st[k - 1] is not None and st[k - 1][0] == st[k][0]:
            k -= 1
        return k
    i = seg_start(len(st) - 1)
    # flip candle's body vs the average true range of the 14 candles before it (paper test 2026-11-19: strong flips only)
    trs = [max(float(c[2]), float(p[4])) - min(float(c[3]), float(p[4])) for p, c in zip(cs[i - 15:i - 1], cs[i - 14:i])]
    strength = round(abs(float(cs[i][4]) - float(cs[i][1])) / (sum(trs) / len(trs)), 2) if len(trs) == 14 and sum(trs) else None
    # a real flip needs a real trend before it: the first run only reflects the starting assumption (DOWN), not a trend
    flipped = i > 0 and st[i - 1] is not None and seg_start(i - 1) > 0 and st[seg_start(i - 1) - 1] is not None
    return {"trend": "UP" if d == 1 else "DOWN", "line": round(line, 2),
            "since": cs[i][0] if flipped else None, "since_close": float(cs[i][4]) if flipped else None,
            "since_strength": strength if flipped else None,
            "since_strong": None if strength is None or not flipped else strength >= STRONG_MIN,
            "since_at_least": None if flipped else cs[i][0]}


def row(symbol: str, candles: List[list], closed_through: datetime) -> Optional[Dict[str, Any]]:
    """One board row from a symbol's 5-minute candles, using only candles that started at or before `closed_through`:
    the 5-minute trend (fields without suffix), the 15-minute trend (`_15m`), and whether the two agree."""
    cs = [c for c in candles if datetime.fromisoformat(c[0]) <= closed_through]
    a = _trend(cs)
    if a is None:
        return None
    b = _trend(to_15m(cs, closed_through)) or {}
    close = float(cs[-1][4])
    agree = b.get("trend") == a["trend"]
    # both runs known: they have agreed since the later of the two flip candles closed
    ends = [datetime.fromisoformat(s) + timedelta(minutes=n) for s, n in ((a["since"], 5), (b.get("since"), 15)) if s]
    day_open = float(next(c for c in cs if c[0][:10] == cs[-1][0][:10])[1])   # first candle of the board's day
    return {"symbol": symbol, **a, "close": close, "open": day_open, "gap_pct": round((close - a["line"]) / close * 100, 2),
            "bar": cs[-1][0], **{f"{k}_15m": b.get(k) for k in ("trend", "line", "since", "since_at_least")},
            "agree": agree, "agree_since": max(ends).isoformat() if agree and len(ends) == 2 else None}


def scan(now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(IST)
    bar = _bar_start(now)
    from concurrent.futures import ThreadPoolExecutor
    rows, errors = [], {}

    def one(item):
        sym, tok = item
        try:
            return sym, row(sym, _candles(tok, now), bar), None
        except Exception as e:
            return sym, None, str(e)[:120]
    with ThreadPoolExecutor(max_workers=3) as ex:   # overlap network waits; _pace keeps the 3 / second limit
        for sym, r, err in ex.map(one, sorted(_tokens().items())):
            if err:
                errors[sym] = err
            elif r:
                rows.append(r)
    rows.sort(key=lambda r: (r["since"] or "", r["symbol"]), reverse=True)   # newest flips first
    return {"bar": bar.isoformat(), "scanned_at": datetime.now(IST).isoformat(timespec="seconds"),
            "rows": rows, "errors": errors}


def _load() -> Dict[str, Any]:
    try:
        return json.loads(_STATE.read_text())
    except (OSError, ValueError):
        return {}


def new_flips(rows: List[Dict[str, Any]], after: str) -> List[Dict[str, Any]]:
    """Rows whose current trend began on a candle newer than `after` (ISO time) that closed before LAST_ALERT."""
    return [r for r in rows if r["since"] and datetime.fromisoformat(r["since"]) > datetime.fromisoformat(after)
            and (datetime.fromisoformat(r["since"]) + timedelta(minutes=BAR_MIN)).strftime("%H:%M") < LAST_ALERT]


CLOSE_GRACE_MIN = 15   # the last candle closes exactly at the bell, when the market-hours gate shuts: scan it this long after


def _bell(session: Dict[str, Any], now: datetime) -> Optional[datetime]:
    """Shortly after a trading day's close -> the closing time (scan as of the bell, so the last candle is in), else None."""
    if session.get("session") != "CLOSED":   # weekend / holiday / pre-market are other labels
        return None
    hm = (session.get("special") or {}).get("close", "15:30")
    close = now.replace(hour=int(hm[:2]), minute=int(hm[3:]), second=0, microsecond=0)
    return close if now - close < timedelta(minutes=CLOSE_GRACE_MIN) else None


PREOPEN_MATCH_MIN = 9   # owner: the pre-open auction can run until 09:08, so read opening prices from 09:09


def _opening_prices() -> Dict[str, float]:
    """Symbol -> opening price discovered in the pre-open auction (stocks via the gap screen's quote sweep, plus the
    indices). A stock that did not match has no open yet and is left out."""
    from dashboard.fno_scanner import _universe_quotes
    _, _, quotes = _universe_quotes()
    r = requests.get("https://api.kite.trade/quote", params=[("i", s) for s in INDEX_SYM.values()],
                     headers=_headers(), timeout=10).json()
    quotes.update(r.get("data") or {})
    syms = {f"NSE:{n}": n for n in fno_universe()} | {s: n for n, s in INDEX_SYM.items()}
    return {syms[k]: q["ohlc"]["open"] for k, q in quotes.items() if k in syms and (q.get("ohlc") or {}).get("open")}


def preopen_crossings(rows: List[Dict[str, Any]], opens: Dict[str, float]) -> List[Dict[str, Any]]:
    """Rows whose opening price is already on the other side of their 5-minute line, so the first candle (09:15-09:20)
    may flip them. A forecast: the line itself moves with that candle, and the price can come back before it closes."""
    out = []
    for r in rows:
        p, line = opens.get(r["symbol"]), r.get("line")
        if p and line and ((r["trend"] == "UP" and p < line) or (r["trend"] == "DOWN" and p > line)):
            out.append({"symbol": r["symbol"], "trend": r["trend"], "may_turn": "DOWN" if r["trend"] == "UP" else "UP",
                        "line": line, "open": p, "gap_pct": round((p - line) / line * 100, 2)})
    return sorted(out, key=lambda x: -abs(x["gap_pct"]))


def _preopen(session: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Once per day, after the pre-open auction has matched: which stocks open across their line (saved on the board)."""
    start = (session.get("special") or {}).get("pre_open", "09:00")
    ready = now.replace(hour=int(start[:2]), minute=int(start[3:]), second=0, microsecond=0) + timedelta(minutes=PREOPEN_MATCH_MIN)
    if now < ready:
        return {"skipped": f"pre-open auction still matching; opening prices from {ready:%H:%M}"}
    prev = _load()
    if (prev.get("preopen") or {}).get("day") == now.date().isoformat():
        return {"skipped": "pre-open already checked"}
    if not prev.get("rows"):
        return {"skipped": "no board from the last session to compare with"}
    if not _connected():
        return {"skipped": "Kite not connected"}
    try:
        opens = _opening_prices()
    except Exception as e:   # nothing saved: the next minute retries
        return {"error": f"pre-open quotes failed: {e}"[:200]}
    rows = preopen_crossings(prev["rows"], opens)
    prev["preopen"] = {"day": now.date().isoformat(), "at": now.isoformat(timespec="seconds"),
                       "priced": len(opens), "rows": rows, "opens": opens}
    _STATE.write_text(json.dumps(prev))
    return {"preopen": len(rows), "priced": len(opens)}


def check_and_alert(now: Optional[datetime] = None, market_open=None) -> Dict[str, Any]:
    """Once per new closed 5-minute candle in market hours (plus the closing candle just after the bell):
    scan and save the board (`flips` counts the new ones; no alert here). In the pre-open, once a day: flag stocks opening across their line."""
    from dashboard import app as core
    now = now or datetime.now(IST)
    bell, s = None, {}
    if market_open is None:
        try:
            s = core.ZerodhaPlumbingInspector.market_session(now, "NSE")
            market_open, bell = bool(s["is_open"]), _bell(s, now)
        except Exception:   # same fallback as is_open(): unknown = closed
            market_open = False
    if not market_open:
        if s.get("session") == "PRE_OPEN":
            return _preopen(s, now)
        if bell is None:
            return {"skipped": "market closed"}
        now = bell
    if not _connected():
        return {"skipped": "Kite not connected"}
    bar = _bar_start(now)
    if bar.strftime("%H:%M") < "09:15":
        return {"skipped": "today's first 5-minute candle has not closed yet"}
    prev = _load()
    if prev.get("bar") == bar.isoformat():
        return {"skipped": f"candle {bar:%H:%M} already scanned"}
    if not _BUSY.acquire(blocking=False):
        return {"skipped": "scan already running"}
    try:
        out = scan(now)
    finally:
        _BUSY.release()
    if len(out["errors"]) > len(out["rows"]):       # e.g. token expired: keep the last good board, retry next minute
        return {"error": f"{len(out['errors'])} symbols failed", "first": next(iter(out["errors"].items()))}
    same_day = prev.get("bar", "")[:10] == out["bar"][:10]
    after = prev["bar"] if same_day else (bar - timedelta(seconds=1)).isoformat()   # first scan of the day: newest candle only
    flips = new_flips(out["rows"], after)
    _STATE.write_text(json.dumps(out))
    return {"bar": out["bar"], "rows": len(out["rows"]), "errors": len(out["errors"]), "flips": len(flips)}


def board() -> Dict[str, Any]:
    """The last saved board for the tab (cheap: no Kite calls)."""
    from dashboard import app as core
    s = _load()
    if (s.get("preopen") or {}).get("day") != datetime.now(IST).date().isoformat():
        s.pop("preopen", None)   # only today's pre-open forecast; the first scan of the day replaces it anyway
    return {**s, "rows": s.get("rows", []), "market_open": core.ZerodhaPlumbingInspector.is_open("NSE"),
            "setting": f"Supertrend({PERIOD},{MULT:g}) on 5-minute and 15-minute candles"}
