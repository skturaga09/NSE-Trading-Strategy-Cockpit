"""Intraday refresh: re-run the append-only part of the EOD dashboard chain (option chain, Phase 8 signals, dashboard export)
on today's live day directory, so the F&O Engine tab shows today's recommendations during the session, not only after 15:50.

  python3 -m engine.intraday [--config config/engine/v24.yaml]

Runs only while the recorder holds its lock (a live session); otherwise it does nothing. Every step is INSERT OR IGNORE and
reads only data received by the time it runs, so each run's rows are a prefix of the end-of-day run's rows (the EOD job
re-runs these steps for today to add the tail). The paper ledger is NOT run here: it is not re-runnable (it would see its
own earlier trades); paper trades appear after the EOD job. launchd: scripts/launchd/com.clade.engine-intraday.plist.
"""

import argparse
import json
import sys
from datetime import datetime

from .alerts import alert_once
from .config import load_config
from .eod import RERUNNABLE, dashboard_chain
from .health import IST
from .recorder import acquire_lock


def run(cfg, now: datetime, chain=dashboard_chain) -> dict:
    day_dir = cfg.root / now.date().isoformat()
    probe = acquire_lock(cfg.root)
    if probe is not None:                       # nobody holds it: no live session (or EOD running) -> leave the day alone
        probe.close()
        return {"skipped": "recorder not running"}
    if not (day_dir / "buffer.sqlite").exists():
        return {"skipped": f"no buffer for {day_dir.name}"}
    return chain([day_dir], rerun={day_dir.name}, only=RERUNNABLE, live=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.intraday")
    ap.add_argument("--config", default="config/engine/v24.yaml")
    cfg = load_config(ap.parse_args(argv).config)
    out = run(cfg, datetime.now(IST))
    print(json.dumps({"at": datetime.now(IST).isoformat(timespec="seconds"), **out}, default=str))
    errors = [v for r in out.values() if isinstance(r, dict) for v in r.values() if str(v).startswith("error")]
    if errors:   # once a day: the Radar would silently stop updating
        alert_once(cfg.root, "intraday", "Engine intraday signals FAILED", str(errors[0])[:400])
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
