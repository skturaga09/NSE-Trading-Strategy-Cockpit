#!/usr/bin/env python3
"""
EOD 'catcher' job: near close, push the overnight OI-buildup board to the phone so a
hold-tonight decision can be made without opening the dashboard.

Run by the com.clade.swing-eod launchd job at ~15:10 IST on weekdays (a few minutes
before the 15:30 close, when today's OI is essentially complete). It warms the
full-universe OI map, scans, and pushes the ranked Long/Short buildups via the same
ntfy channel the exit monitor uses. A screen, NOT advice — carries overnight gap risk.
"""

import json
import time
from pathlib import Path

from dashboard import exit_monitor


def main() -> int:
    res = exit_monitor.send_overnight()
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {json.dumps(res)}"
    print(line)
    try:
        log_file = Path(__file__).parent / "logs" / "swing_eod.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
