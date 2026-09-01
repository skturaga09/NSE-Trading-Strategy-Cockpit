#!/usr/bin/env python3
"""
Rule-based EXIT monitor for live Kite positions + mobile alerts.

This is NOT discretionary advice ("sell now"). YOU set objective thresholds
(target %, stop %, trailing stop, time exit); the monitor evaluates each open
position against them and fires a mechanical signal when one is hit — the same
stance as the intraday discipline console. A background job can push these
signals to your phone (ntfy or Telegram) so you don't have to watch the screen.

State (all gitignored, in dashboard/):
  exit_config.json  rules + notification channel
  exit_peaks.json   best P&L% seen per symbol (for the trailing stop)
  exit_seen.json    per symbol: {signal, ts, pnl_pct} — drives once-then-every-N-min
                    re-alerts with reversal suppression (legacy plain-string is migrated)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from dashboard import app as core
from dashboard.option_chain import ensure_fresh_config

_DIR = Path(__file__).parent
_CONFIG = _DIR / "exit_config.json"
_PEAKS = _DIR / "exit_peaks.json"
_SEEN = _DIR / "exit_seen.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "target_pct": 40.0,     # take profit at +40% on the position
    "stop_pct": 25.0,       # cut at −25%
    "trail_pct": 20.0,      # flat give-back used when the ratchet is OFF
    "trail_arm_pct": 15.0,  # flat-trail arms after +15%
    # Profit ratchet: the trail tightens as the peak profit grows, so a big runner
    # keeps room early then is protected hard near the top. Each tier = {above, trail}.
    "ratchet_enabled": True,
    "ratchet_tiers": [
        {"above": 15.0, "trail": 12.0},
        {"above": 25.0, "trail": 8.0},
        {"above": 40.0, "trail": 5.0},
    ],
    "pullback_alert_pct": 5.0,  # heads-up when a winner gives back this much from peak (0=off)
    # Re-alert cadence: once an exit signal fires, keep nudging every N minutes while
    # the position is STILL open on that signal — unless it's reversing back in your
    # favour (P&L% recovered by >= reversal_pct since the last nudge), in which case
    # stay quiet until it stalls again. Set realert_every_min to 0 for one-shot alerts.
    "realert_every_min": 15.0,
    "reversal_pct": 2.0,
    "time_exit": "",        # e.g. "15:15" — flag positions to flatten before cut-off (never assumed)
    "summary_every_min": 30,  # periodic portfolio heartbeat during market hours (0 = off)
    "candidate_every_min": 60,  # periodic "top F&O candidates" digest (0 = off)
    "candidate_top": 5,         # how many longs/shorts to list
    "breakout_alerts": True,    # push VCP breakouts (pivot cross) as they happen
    # Tapping an alert opens this. Universal link → opens the Kite iOS/Android app
    # when installed (else the browser). Change if you find a scheme that opens the app.
    "kite_link": "https://kite.zerodha.com/positions",
    "notify": {"channel": "none", "ntfy_topic": "", "telegram_token": "", "telegram_chat_id": ""},
}

_SUMMARY = _DIR / "exit_summary.json"
_THESIS_SEEN = _DIR / "exit_thesis_seen.json"
_CANDIDATE_LAST = _DIR / "exit_candidate_last.json"
_BREAKOUT_SEEN = _DIR / "exit_breakout_seen.json"


def _load(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


def _save(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def get_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_load(_CONFIG, {}))
    n = dict(DEFAULT_CONFIG["notify"]); n.update(cfg.get("notify", {})); cfg["notify"] = n
    return cfg


def set_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    cfg = get_config()
    for k, v in patch.items():
        if k == "notify" and isinstance(v, dict):
            cfg["notify"].update(v)
        else:
            cfg[k] = v
    _save(_CONFIG, cfg)
    return cfg


def _headers() -> Dict[str, str]:
    ensure_fresh_config()
    kc = core.KITE_CONFIG
    return {"Authorization": f"token {kc.get('api_key','')}:{kc.get('access_token','')}", "X-Kite-Version": "3"}


def _positions() -> List[Dict[str, Any]]:
    kc = core.KITE_CONFIG
    if not (kc.get("api_key") and kc.get("access_token")):
        return []
    try:
        j = requests.get("https://api.kite.trade/portfolio/positions", headers=_headers(), timeout=10).json()
        if j.get("status") == "success":
            return [p for p in j["data"].get("net", []) if p.get("quantity")]
    except Exception:
        pass
    return []


def _is_option(sym: str) -> bool:
    s = sym.upper()
    return s.endswith("CE") or s.endswith("PE")


def _fresh_ltp(positions: List[Dict[str, Any]]) -> Dict[str, float]:
    """Kite /portfolio/positions last_price lags; fetch real-time LTP via /quote."""
    insts = [f"{p.get('exchange', 'NSE')}:{p['tradingsymbol']}" for p in positions]
    out: Dict[str, float] = {}
    for i in range(0, len(insts), 200):
        grp = insts[i:i + 200]
        try:
            j = requests.get("https://api.kite.trade/quote/ltp",
                             params=[("i", s) for s in grp], headers=_headers(), timeout=8).json()
            if j.get("status") == "success":
                out.update({k: v.get("last_price") for k, v in j["data"].items() if v.get("last_price")})
        except Exception:
            pass
    return out


def _effective_trail(peak: float, cfg: Dict[str, Any]) -> Optional[float]:
    """Give-back % that applies at this peak, or None if the trail isn't armed yet.
    With the ratchet on, the tightest tier whose threshold the peak has cleared."""
    if cfg.get("ratchet_enabled", True):
        gb: Optional[float] = None
        for t in sorted(cfg.get("ratchet_tiers", []), key=lambda x: x["above"]):
            if peak >= t["above"]:
                gb = t["trail"]
        return gb
    return cfg.get("trail_pct", 20.0) if peak >= cfg.get("trail_arm_pct", 15.0) else None


def evaluate() -> Dict[str, Any]:
    """Compute per-position exit signals from the configured rules. Live, read-only."""
    cfg = get_config()
    peaks = _load(_PEAKS, {})
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    positions = _positions()
    fresh = _fresh_ltp(positions)
    rows: List[Dict[str, Any]] = []
    for p in positions:
        sym = p["tradingsymbol"]
        qty = p.get("quantity", 0)
        entry = p.get("buy_price") if qty > 0 else p.get("sell_price")
        kite_ltp = p.get("last_price")
        # Prefer the real-time /quote LTP; fall back to the (laggy) positions LTP.
        live = fresh.get(f"{p.get('exchange', 'NSE')}:{sym}")
        ltp = live or kite_ltp
        if not ltp or not entry:
            continue
        # Kite's pnl is on the stale LTP — adjust it for the fresher price.
        pnl = p.get("pnl", 0.0) + ((live - kite_ltp) * qty if (live and kite_ltp) else 0.0)
        pnl_pct = round((ltp / entry - 1.0) * 100.0 * (1 if qty > 0 else -1), 2)
        peak = max(peaks.get(sym, pnl_pct), pnl_pct)
        peaks[sym] = round(peak, 2)

        gb = _effective_trail(peak, cfg)              # armed give-back %, or None
        giveback = round(peak - pnl_pct, 1)           # how much off the peak, now
        pb = cfg.get("pullback_alert_pct", 0)
        signal, reason = "HOLD", ""
        if pnl_pct <= -cfg["stop_pct"]:
            signal, reason = "STOP", f"{pnl_pct}% ≤ −{cfg['stop_pct']}% stop"
        elif pnl_pct >= cfg["target_pct"]:
            signal, reason = "TARGET", f"{pnl_pct}% ≥ +{cfg['target_pct']}% target"
        elif gb is not None and giveback >= gb:
            signal, reason = "TRAIL", f"gave back {giveback}% from +{round(peak,1)}% peak (ratchet trail {gb}%)"
        elif cfg["time_exit"] and now.strftime("%H:%M") >= cfg["time_exit"]:
            signal, reason = "TIME", f"past {cfg['time_exit']} cut-off"
        elif gb is not None and pb and giveback >= pb:
            signal, reason = "PULLBACK", f"off {giveback}% from +{round(peak,1)}% peak — trail exits at {gb}%"

        rows.append({"symbol": sym, "qty": qty, "is_option": _is_option(sym),
                     "entry": round(entry, 2), "ltp": round(ltp, 2), "pnl": round(pnl, 2),
                     "pnl_pct": pnl_pct, "peak_pct": round(peak, 2), "product": p.get("product"),
                     "signal": signal, "reason": reason})
    _save(_PEAKS, peaks)
    rows.sort(key=lambda r: ({"STOP": 0, "TIME": 1, "TARGET": 2, "TRAIL": 3, "PULLBACK": 4, "HOLD": 5}[r["signal"]], -abs(r["pnl"])))
    return {"timestamp": ts, "config": cfg, "positions": rows,
            "actionable": [r for r in rows if r["signal"] != "HOLD"]}


def notify(title: str, message: str, cfg: Optional[Dict[str, Any]] = None,
           tags: Optional[List[str]] = None, priority: int = 4,
           actions: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Push a rich card to the configured mobile channel (ntfy or Telegram).

    Uses ntfy JSON publishing so emoji render in the title (no latin-1 header
    limit), with tags, priority, a tap-to-open action and action buttons."""
    cfg = cfg or get_config()
    n = cfg["notify"]
    ch = n.get("channel", "none")
    try:
        if ch == "ntfy" and n.get("ntfy_topic"):
            payload: Dict[str, Any] = {
                "topic": n["ntfy_topic"], "title": title, "message": message,
                "tags": tags or ["chart_with_upwards_trend"], "priority": priority,
            }
            if actions:  # no default button — plain informational card
                payload["actions"] = actions
            requests.post("https://ntfy.sh/", json=payload, timeout=8)
            return {"success": True, "channel": "ntfy"}
        if ch == "telegram" and n.get("telegram_token") and n.get("telegram_chat_id"):
            requests.get(f"https://api.telegram.org/bot{n['telegram_token']}/sendMessage",
                         params={"chat_id": n["telegram_chat_id"], "text": f"{title}\n{message}",
                                 "parse_mode": "Markdown"}, timeout=8)
            return {"success": True, "channel": "telegram"}
    except Exception as e:
        return {"success": False, "message": str(e)}
    return {"success": False, "message": "No notification channel configured."}


def _portfolio_line(res: Dict[str, Any]) -> str:
    total = sum(p["pnl"] for p in res["positions"])
    wins = sum(1 for p in res["positions"] if p["pnl"] > 0)
    return f"Portfolio: ₹{total:+,.0f} · {wins}/{len(res['positions'])} green"


CAPITAL = 200_000


def _short(sym: str) -> str:
    """DIVISLAB26SEP9000CE → DIVISLAB 9000CE for a cleaner card."""
    import re
    m = re.match(r"^([A-Z&-]+?)\d{2}[A-Z]{3}(\d+)(CE|PE)$", sym)
    return f"{m.group(1)} {m.group(2)}{m.group(3)}" if m else sym


def send_summary(res: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Push a scannable portfolio heartbeat card: total, breakdown, top movers."""
    pos = res["positions"]
    if not pos:
        return {"success": False, "message": "no positions"}
    total = sum(p["pnl"] for p in pos)
    wins = [p for p in pos if p["pnl"] > 0]
    losers = [p for p in pos if p["pnl"] < 0]
    opts = [p for p in pos if p["is_option"]]
    opt_total = sum(p["pnl"] for p in opts)
    on_cap = total / CAPITAL * 100
    ranked = sorted(pos, key=lambda p: p["pnl"], reverse=True)
    up, down = "📈" if total >= 0 else "📉", ""

    lines = [
        f"💰 ₹{total:+,.0f}   ({on_cap:+.1f}% on ₹2L)",
        f"🟢 {len(wins)} green   🔴 {len(losers)} red   ·   {len(pos)} open",
        f"📊 Options ₹{opt_total:+,.0f}  ·  Equity ₹{total - opt_total:+,.0f}",
        "",
        "Top movers",
    ]
    for p in ranked[:3]:
        lines.append(f"  🟢 {_short(p['symbol'])}  ₹{p['pnl']:+,.0f} ({p['pnl_pct']:+.0f}%)")
    if losers:
        w = ranked[-1]
        lines.append(f"  🔴 {_short(w['symbol'])}  ₹{w['pnl']:+,.0f} ({w['pnl_pct']:+.0f}%)")
    lines.append(f"\n🕒 {res['timestamp'].split(' ')[1]}")

    return notify(f"{up}{down} Portfolio  ₹{total:+,.0f}  ({on_cap:+.1f}%)",
                  "\n".join(lines), cfg, tags=["moneybag"], priority=3)


def send_candidates(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Push a 'top F&O candidates' card from the live momentum scan — a SCREEN you
    review, not a recommendation. So you know what to look at even when away."""
    cfg = cfg or get_config()
    from dashboard import fno_scanner
    top = int(cfg.get("candidate_top", 5) or 5)
    r = fno_scanner.scan(top=top)
    if not r.get("is_live"):
        return {"success": False, "message": r.get("source", "scan unavailable")}
    longs, shorts = r.get("longs", []), r.get("shorts", [])
    if not longs and not shorts:
        return {"success": False, "message": "no candidates"}
    fmt = lambda x: f"{x['symbol']} {x['pct_change']:+.1f}%"
    body = (
        "▲ Longs: " + (", ".join(fmt(x) for x in longs) or "—") + "\n"
        "▼ Shorts: " + (", ".join(fmt(x) for x in shorts) or "—") + "\n"
        "Ranked by momentum (screen, NOT advice). Review each, check the gates, "
        "and mind you're not chasing an extended move — you decide."
    )
    return notify("📊 Top F&O candidates", body, cfg, tags=["mag_right"], priority=3)


def _breakout_alerts(cfg: Dict[str, Any]) -> int:
    """Push VCP breakouts (pivot cross) once each, as they turn live."""
    try:
        b = core.compute_breakouts()
    except Exception:
        return 0
    if not b.get("is_live"):
        return 0  # modeled/warming — don't announce placeholders
    seen = _load(_BREAKOUT_SEEN, {})
    sent, live = 0, set()
    for x in b.get("breakouts", []):
        if x.get("state") not in ("BROKEN_OUT", "IMMINENT"):
            continue
        key = x["symbol"]
        live.add(key)
        if seen.get(key) == x["state"]:
            continue
        pos = x.get("positional", {}) or {}
        emoji = "🚀" if x["state"] == "BROKEN_OUT" else "🔔"
        verb = "crossed" if x["state"] == "BROKEN_OUT" else "nearing"
        notify(f"{emoji} {x['state'].replace('_', ' ')} · {x['symbol']}",
               f"{verb} pivot ₹{x['pivot']} · LTP ₹{x['ltp']} ({x['above_pivot_pct']:+}%)\n"
               f"Plan: E {pos.get('entry')} · SL {pos.get('stop')} · T {pos.get('target1')} (R:R {pos.get('gross_rr')})\n"
               f"VCP screen — confirm volume & the market regime, run the gates. Not advice.",
               cfg, tags=["rocket"], priority=4)
        seen[key] = x["state"]
        sent += 1
    _save(_BREAKOUT_SEEN, {k: v for k, v in seen.items() if k in live})
    return sent


def send_breakouts(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """On-demand digest of the current actionable breakouts (for the test button)."""
    cfg = cfg or get_config()
    try:
        b = core.compute_breakouts()
    except Exception as e:
        return {"success": False, "message": str(e)}
    if not b.get("is_live"):
        return {"success": False, "message": "breakout screen still warming up (modeled) — try during market hours"}
    act = [x for x in b.get("breakouts", []) if x.get("state") in ("BROKEN_OUT", "IMMINENT")]
    if not act:
        return {"success": False, "message": "no actionable breakouts right now"}
    lines = [f"{'🚀' if x['state'] == 'BROKEN_OUT' else '🔔'} {x['symbol']} {x['state'].replace('_', ' ').lower()} · pivot ₹{x['pivot']} ({x['above_pivot_pct']:+}%)" for x in act[:8]]
    return notify("🚀 Actionable breakouts", "\n".join(lines) + "\nVCP screen — confirm volume & regime. Not advice.",
                  cfg, tags=["rocket"], priority=4)


def _market_open() -> bool:
    """NSE cash/F&O hours, weekdays (no holiday calendar). IST assumed = local."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    hm = now.strftime("%H:%M")
    return "09:15" <= hm <= "15:30"


def check_and_notify(force: bool = False) -> Dict[str, Any]:
    """Run by the background job: evaluate, and push any NEW exit signal once.
    Skips outside market hours unless forced (so the 2-min job stays quiet)."""
    if not force and not _market_open():
        return {"skipped": "market closed", "alerts_sent": 0, "actionable": []}
    res = evaluate()
    seen = _load(_SEEN, {})
    sent = 0
    SIG = {
        "STOP": ("🛑", ["octagonal_sign"], 5, "EXIT"),
        "TARGET": ("🎯", ["dart", "tada"], 5, "BOOK IT"),   # max priority — hit the target
        "TRAIL": ("📉", ["chart_with_downwards_trend"], 4, "EXIT"),
        "TIME": ("⏰", ["alarm_clock"], 4, "EXIT"),
        "PULLBACK": ("👀", ["eyes"], 3, "HEADS-UP"),  # a nudge, not a hard exit
    }
    TAIL = {
        "TARGET": "🎯 Target hit — BOOK IT NOW (place the exit in Kite yourself).",
        "PULLBACK": "It's coming off its peak — watch for the trail exit.",
        "STOP": "Stop breached — your rule says cut it. You place the order.",
    }
    cfg = res["config"]
    realert_min = float(cfg.get("realert_every_min", 15) or 0)   # 0 = one-shot
    reversal_pct = float(cfg.get("reversal_pct", 2.0) or 0)
    FMT = "%Y-%m-%d %H:%M:%S"
    now_dt = datetime.now()
    for r in res["actionable"]:
        key = r["symbol"]
        prev = seen.get(key)
        if isinstance(prev, str):            # migrate legacy {sym: "SIGNAL"} state
            prev = {"signal": prev, "ts": None, "pnl_pct": r["pnl_pct"]}
        is_new = (not prev) or (prev.get("signal") != r["signal"])
        reminder_n: Optional[int] = None
        if not is_new:
            # Same exit signal, still open → decide whether to re-nudge. Keep quiet
            # unless it's been >= realert_min since the last nudge AND it isn't
            # reversing back in your favour (P&L% recovered by >= reversal_pct).
            base = prev.get("pnl_pct", r["pnl_pct"])
            reversing = (r["pnl_pct"] - base) >= reversal_pct
            elapsed_min: Optional[float] = None
            if prev.get("ts"):
                try:
                    elapsed_min = (now_dt - datetime.strptime(prev["ts"], FMT)).total_seconds() / 60.0
                except Exception:
                    elapsed_min = None
            due = realert_min > 0 and (elapsed_min is None or elapsed_min >= realert_min)
            if not (due and not reversing):
                # Not re-alerting this cycle. If recovering, raise the baseline so a
                # later stall re-nudges from the better level (keep the original ts).
                seen[key] = {"signal": prev["signal"], "ts": prev.get("ts"),
                             "pnl_pct": max(base, r["pnl_pct"]) if reversing else base}
                continue
            reminder_n = int(round(elapsed_min)) if elapsed_min is not None else None
        emoji, tags, prio, kind = SIG.get(r["signal"], ("•", ["bell"], 4, "EXIT"))
        tail = TAIL.get(r["signal"], "Your rule triggered — you decide.")
        if reminder_n is not None:
            head = f"🔁 STILL OPEN · {r['signal']} · {r['symbol']}"
            remind_line = f"↻ Reminder ({reminder_n}m on, not exited) — re-nudges every {int(realert_min)}m unless it reverses.\n"
        else:
            head = f"{emoji} {kind} {r['signal']} · {r['symbol']}"
            remind_line = ""
        body = (
            f"{remind_line}"
            f"P&L: {r['pnl_pct']:+.1f}%  (₹{r['pnl']:+,.0f})\n"
            f"Now ₹{r['ltp']} · entry ₹{r['entry']} · peak {r['peak_pct']:+.1f}%\n"
            f"Rule: {r['reason']}\n"
            f"{_portfolio_line(res)}\n"
            f"{tail}"
        )
        notify(head, body, cfg, tags=tags, priority=prio)
        seen[key] = {"signal": r["signal"], "ts": now_dt.strftime(FMT), "pnl_pct": r["pnl_pct"]}
        sent += 1
    # drop symbols no longer actionable so a fresh trigger later alerts again
    live = {r["symbol"] for r in res["actionable"]}
    seen = {k: v for k, v in seen.items() if k in live}
    _save(_SEEN, seen)

    # Thesis-drift alerts: when an open option's underlying newly flips against
    # the bet (status → DRIFT), nudge once. A heads-up, not an exit.
    try:
        from dashboard import thesis, journal
        align = thesis.alignment()
        amap = {p["symbol"]: p for p in align.get("positions", [])}
        # Snapshot ENTRY features onto each open option (idempotent; preserved on
        # close) so the closed-trade sample carries the regime it was taken in.
        for r in res["positions"]:
            if not r.get("is_option"):
                continue
            a = amap.get(r["symbol"])
            if not a:
                continue
            regime = ("BULLISH" if a.get("lean") == "bullish" else "BEARISH" if a.get("lean") == "bearish"
                      else ("BULLISH" if (a.get("day_pct") or 0) > 0 else "BEARISH"))
            journal.record_external(
                order_id=f"KITE_{r['symbol']}", symbol=r["symbol"], source="Zerodha (live)",
                entry_price=r["entry"], qty=abs(int(r["qty"])), is_option=True, status="OPEN",
                plan_type="intraday" if r.get("product") == "MIS" else "positional",
                regime=regime, sector=a.get("underlying"), bias_score=a.get("agree"))
        tseen = _load(_THESIS_SEEN, {})
        drift_syms = set()
        for p in align.get("positions", []):
            if p["status"] == "DRIFT":
                drift_syms.add(p["symbol"])
                if tseen.get(p["symbol"]) != "DRIFT":
                    notify(f"👀 THESIS DRIFT · {p['symbol']}",
                           f"Underlying {p['underlying']} turned against your {p['direction']}:\n"
                           f"day {p['day_pct']}% · vs VWAP {p['vs_vwap_pct']}% · {p['buildup']}\n"
                           f"The reason you entered has weakened — you decide.",
                           res["config"], tags=["eyes"], priority=3)
                    tseen[p["symbol"]] = "DRIFT"
        tseen = {k: v for k, v in tseen.items() if k in drift_syms}
        _save(_THESIS_SEEN, tseen)
    except Exception:
        pass

    # Periodic portfolio heartbeat (market hours only, throttled).
    every = res["config"].get("summary_every_min", 0)
    summary_sent = False
    if every and every > 0 and res["positions"]:
        st = _load(_SUMMARY, {})
        due = True
        if st.get("last"):
            try:
                due = (datetime.now() - datetime.strptime(st["last"], "%Y-%m-%d %H:%M:%S")).total_seconds() >= every * 60
            except Exception:
                due = True
        if due:
            send_summary(res, res["config"])
            _save(_SUMMARY, {"last": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            summary_sent = True

    # Periodic "top candidates" digest (market hours only, throttled).
    cand_every = res["config"].get("candidate_every_min", 0)
    cand_sent = False
    if cand_every and cand_every > 0:
        st = _load(_CANDIDATE_LAST, {})
        due = True
        if st.get("last"):
            try:
                due = (datetime.now() - datetime.strptime(st["last"], "%Y-%m-%d %H:%M:%S")).total_seconds() >= cand_every * 60
            except Exception:
                due = True
        if due:
            send_candidates(res["config"])
            _save(_CANDIDATE_LAST, {"last": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            cand_sent = True

    # VCP breakout alerts (pivot cross), as they happen.
    breakout_sent = 0
    if res["config"].get("breakout_alerts", True):
        breakout_sent = _breakout_alerts(res["config"])

    res["alerts_sent"] = sent
    res["summary_sent"] = summary_sent
    res["candidates_sent"] = cand_sent
    res["breakouts_sent"] = breakout_sent
    return res


if __name__ == "__main__":
    print(json.dumps(check_and_notify(), indent=2, default=str))
