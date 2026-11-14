"""Keep the engine's launchd jobs, the dashboard bundle and the dashboard server in step with the repo, so nothing is
installed, rebuilt or restarted by hand (owner D-66).

  python3 scripts/sync_launchd.py [--dry-run]

Run by com.clade.engine-sync (daily 08:15 and 16:15, and at login). It does nothing on a weekday between 08:55 and
15:55 IST: reloading the recorder's plist would stop the recorder, and a rebuild or server restart would blank the
dashboard mid-session. Steps:
1. Every scripts/launchd/com.clade.engine-*.plist that is missing from ~/Library/LaunchAgents or differs from it is
   copied and reloaded (bootout + bootstrap). Its own plist is only copied: reloading itself would kill this run.
2. If any file under dashboard/web/src or dashboard/web/fo-engine is newer than dashboard/web/dist/index.html,
   `npm run build` (type-check + build) runs; on failure the old bundle stays and a phone alert is sent.
3. If any engine/ or dashboard/ Python file changed after the dashboard server started, the server is restarted.
Each action and failure is printed (log: dashboard/logs/engine_sync.*.log).
"""

import argparse
import filecmp
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
AGENTS = Path.home() / "Library" / "LaunchAgents"
SELF = "com.clade.engine-sync.plist"
SERVER = "com.clade.dashboard-server"
NPM = "/usr/local/bin/npm"
IST = ZoneInfo("Asia/Kolkata")


def in_session(now: datetime) -> bool:
    return now.isoweekday() <= 5 and "08:55" <= now.strftime("%H:%M") < "15:55"


def changed_plists(src: Path, dst: Path) -> list[Path]:
    return [p for p in sorted(src.glob("com.clade.engine-*.plist"))
            if not (dst / p.name).exists() or not filecmp.cmp(p, dst / p.name, shallow=False)]


def newest_mtime(paths) -> float:
    return max((p.stat().st_mtime for p in paths if p.is_file()), default=0.0)


def etime_seconds(text: str) -> int:
    """ps etime '[[dd-]hh:]mm:ss' -> seconds."""
    days, _, rest = text.strip().rpartition("-")
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return int(days or 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def pid(label: str, run=subprocess.run) -> str | None:
    m = re.search(r'"PID" = (\d+);', run(["launchctl", "list", label], capture_output=True, text=True).stdout)
    return m.group(1) if m else None


def server_started(run=subprocess.run) -> float | None:
    p = pid(SERVER, run)
    if p is None:
        return None
    et = run(["ps", "-o", "etime=", "-p", p], capture_output=True, text=True).stdout
    return time.time() - etime_seconds(et) if et.strip() else None


def holiday_years(repo: Path) -> list[int]:
    """restrictions.holiday_years of the config every engine job uses (engine.signals.DEFAULT_CONFIG)."""
    import yaml
    sys.path.insert(0, str(repo))
    from engine.signals import DEFAULT_CONFIG
    return yaml.safe_load(Path(DEFAULT_CONFIG).read_text())["restrictions"]["holiday_years"]


def sync(now: datetime, repo: Path = REPO, agents: Path = AGENTS, run=subprocess.run, alert=None, dry=False) -> list[str]:
    if in_session(now):
        return ["skipped: market session (weekday 08:55-15:55); nothing reloaded, rebuilt or restarted"]
    did, uid = [], os.getuid()
    act = (lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")) if dry else run
    for p in changed_plists(repo / "scripts" / "launchd", agents):
        label, dst = p.stem, agents / p.name
        if p.name != SELF and pid(label, run):   # e.g. EOD still compacting at 16:15: bootout would kill it
            did.append(f"deferred {label}: running now (next sync reloads it)")
            continue
        if not dry:
            shutil.copy2(p, dst)
        if p.name == SELF:
            did.append(f"copied {p.name} (takes effect at next login or load)")
            continue
        act(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True, text=True)   # not loaded yet: fine
        r = act(["launchctl", "bootstrap", f"gui/{uid}", str(dst)], capture_output=True, text=True)
        did.append(f"reloaded {label}" if r.returncode == 0 else f"error: bootstrap {label}: {r.stderr.strip()}")
    web = repo / "dashboard" / "web"
    src = [p for d in ("src", "fo-engine") for p in (web / d).rglob("*") if "__screenshots__" not in p.parts]
    if newest_mtime(src) > newest_mtime([web / "dist" / "index.html"]):
        r = act([NPM, "run", "build"], cwd=web, capture_output=True, text=True,
                env={**os.environ, "PATH": f"/usr/local/bin:{os.environ.get('PATH', '/usr/bin:/bin')}"})
        did.append("rebuilt dashboard bundle" if r.returncode == 0 else f"error: npm run build: {(r.stderr or r.stdout)[-300:]}")
    py = [p for p in (repo / "engine").rglob("*.py")] + list((repo / "dashboard").glob("*.py")) + \
        list((repo / "dashboard" / "api").glob("*.py"))
    started = server_started(run)
    if (started is not None and newest_mtime(py) > started) or any(d.startswith("rebuilt") for d in did):
        r = act(["launchctl", "kickstart", "-k", f"gui/{uid}/{SERVER}"], capture_output=True, text=True)
        did.append("restarted dashboard server" if r.returncode == 0 else f"error: restart server: {r.stderr.strip()}")
    if now.month == 12 and now.day >= 15 and now.year + 1 not in holiday_years(repo):
        did.append(f"error: no verified NSE holiday list for {now.year + 1} (config restrictions.holiday_years): add "
                   "the exchange's new holiday circular, or the header and engine treat its holidays as trading days")
    errors = [d for d in did if d.startswith("error")]
    if errors and alert:
        alert("; ".join(errors)[:500])
    return did or ["nothing to do"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sync_launchd")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(REPO))
    from engine.alerts import alert_once
    now = datetime.now(IST)
    alert = lambda msg: alert_once(REPO / "data" / "engine", "sync", "Engine auto-setup FAILED", msg)  # noqa: E731
    did = sync(now, run=subprocess.run, alert=alert, dry=a.dry_run)
    print(now.isoformat(timespec="seconds"), *did, sep="\n  ")
    return 1 if any(d.startswith("error") for d in did) else 0


if __name__ == "__main__":
    sys.exit(main())
