"""Phone alerts for the engine, through the dashboard's existing ntfy/Telegram channel
(dashboard.exit_monitor.notify, configured in dashboard/exit_config.json).

Each (IST date, key) is sent at most once, so a 15-minute launchd retry can't spam. An alert
never raises: a failed send is printed to stderr and the recorder carries on.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _send(title: str, message: str) -> dict:
    from dashboard.exit_monitor import notify  # protected module: imported, never edited
    return notify(title, message, tags=["rotating_light"], priority=5)


def alert_once(root: Path, key: str, title: str, message: str, send=None) -> bool:
    """-> True if sent now, False if already sent today (or the send failed)."""
    print(f"[engine] ALERT {title}: {message}", file=sys.stderr, flush=True)
    root = Path(root)
    p = root / "alerts_sent.json"
    today = datetime.now(IST).date().isoformat()
    try:
        sent = json.loads(p.read_text()) if p.exists() else {}
    except ValueError:
        sent = {}
    if key in sent.get(today, []):
        return False
    try:
        res = (send or _send)(title, message)
    except Exception as e:
        res = {"success": False, "message": repr(e)}
    if not res.get("success"):
        print(f"[engine] alert not delivered: {res.get('message')}", file=sys.stderr, flush=True)
        return False
    root.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({today: sent.get(today, []) + [key]}))  # keeps only today's keys
    return True
