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
  exit_seen.json    last signal per symbol (so an alert fires once, not every poll)
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
    "trail_pct": 20.0,      # once in profit, exit if it gives back 20% from the peak
    "trail_arm_pct": 15.0,  # only start trailing after +15% has been reached
    "time_exit": "",        # e.g. "15:15" — flag positions to flatten before cut-off (never assumed)
    "notify": {"channel": "none", "ntfy_topic": "", "telegram_token": "", "telegram_chat_id": ""},
}


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

        signal, reason = "HOLD", ""
        if pnl_pct <= -cfg["stop_pct"]:
            signal, reason = "STOP", f"{pnl_pct}% ≤ −{cfg['stop_pct']}% stop"
        elif pnl_pct >= cfg["target_pct"]:
            signal, reason = "TARGET", f"{pnl_pct}% ≥ +{cfg['target_pct']}% target"
        elif peak >= cfg["trail_arm_pct"] and pnl_pct <= peak - cfg["trail_pct"]:
            signal, reason = "TRAIL", f"gave back {round(peak - pnl_pct, 1)}% from +{round(peak,1)}% peak"
        elif cfg["time_exit"] and now.strftime("%H:%M") >= cfg["time_exit"]:
            signal, reason = "TIME", f"past {cfg['time_exit']} cut-off"

        rows.append({"symbol": sym, "qty": qty, "is_option": _is_option(sym),
                     "entry": round(entry, 2), "ltp": round(ltp, 2), "pnl": round(pnl, 2),
                     "pnl_pct": pnl_pct, "peak_pct": round(peak, 2), "product": p.get("product"),
                     "signal": signal, "reason": reason})
    _save(_PEAKS, peaks)
    rows.sort(key=lambda r: ({"STOP": 0, "TIME": 1, "TARGET": 2, "TRAIL": 3, "HOLD": 4}[r["signal"]], -abs(r["pnl"])))
    return {"timestamp": ts, "config": cfg, "positions": rows,
            "actionable": [r for r in rows if r["signal"] != "HOLD"]}


KITE_URL = "https://kite.zerodha.com/positions"


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
                "click": KITE_URL,
                "actions": actions or [{"action": "view", "label": "Open Kite", "url": KITE_URL, "clear": True}],
            }
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
        "STOP": ("🛑", ["octagonal_sign"], 5),
        "TARGET": ("🎯", ["dart", "tada"], 4),
        "TRAIL": ("📉", ["chart_with_downwards_trend"], 4),
        "TIME": ("⏰", ["alarm_clock"], 4),
    }
    for r in res["actionable"]:
        key = r["symbol"]
        if seen.get(key) == r["signal"]:
            continue  # already alerted for this signal
        emoji, tags, prio = SIG.get(r["signal"], ("•", ["bell"], 4))
        body = (
            f"P&L: {r['pnl_pct']:+.1f}%  (₹{r['pnl']:+,.0f})\n"
            f"Now ₹{r['ltp']} · entry ₹{r['entry']} · peak {r['peak_pct']:+.1f}%\n"
            f"Rule: {r['reason']}\n"
            f"{_portfolio_line(res)}\n"
            f"Your rule triggered — you decide."
        )
        notify(f"{emoji} EXIT {r['signal']} · {r['symbol']}", body, res["config"], tags=tags, priority=prio)
        seen[key] = r["signal"]
        sent += 1
    # clear seen entries for symbols no longer actionable, so a re-trigger alerts again
    live = {r["symbol"] for r in res["actionable"]}
    seen = {k: v for k, v in seen.items() if k in live}
    _save(_SEEN, seen)
    res["alerts_sent"] = sent
    return res


if __name__ == "__main__":
    print(json.dumps(check_and_notify(), indent=2, default=str))
