#!/usr/bin/env python3
"""
Verify the morning Kite token refresh actually caught, and pop a macOS notification.

Runs shortly after the 08:00 refresh job. Checks that kite_config.json's
token_refreshed_at is from today; notifies PASS or FAIL and appends to a log so
you never have to remember to check manually.
"""

import json
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # dashboard/
CONFIG_FILE = BASE_DIR / "kite_config.json"
REFRESH_LOG = BASE_DIR / "logs" / "kite_refresh.log"
VERIFY_LOG = BASE_DIR / "logs" / "kite_verify.log"


def notify(title: str, message: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}"'],
            timeout=10,
        )
    except Exception:
        pass


def log(line: str) -> None:
    print(line)
    try:
        VERIFY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFY_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
    except Exception:
        pass


def last_refresh_log_line() -> str:
    try:
        lines = REFRESH_LOG.read_text(encoding="utf-8").strip().splitlines()
        return lines[-1] if lines else "(refresh log empty)"
    except Exception:
        return "(no refresh log yet)"


def main() -> int:
    today = time.strftime("%Y-%m-%d")
    refreshed_at = None
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            refreshed_at = cfg.get("token_refreshed_at")
        except Exception:
            pass

    if refreshed_at and refreshed_at.startswith(today):
        log(f"PASS: Kite token refreshed today at {refreshed_at}")
        notify("Kite token ✅", f"Refreshed today at {refreshed_at.split(' ')[-1]}")
        return 0

    tail = last_refresh_log_line()
    log(f"FAIL: token_refreshed_at={refreshed_at or 'missing'} (expected {today}). "
        f"Last refresh log: {tail}")
    notify("Kite token ⚠ NOT refreshed",
           "Check dashboard/logs/kite_refresh.log — token is stale today.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
