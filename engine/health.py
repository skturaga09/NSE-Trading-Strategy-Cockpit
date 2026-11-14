"""Recorder health (step 5): ticks/sec, instruments live, last tick age per instrument, queue depth, gaps today.

  python3 -m engine.health [YYYY-MM-DD]      (default: today, IST)

Reads <date>/status.json (written by the recorder every status interval) and the day's gaps table.
"""

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import load_config

IST = ZoneInfo("Asia/Kolkata")


def summary(day_dir, now_ns: int | None = None) -> str:
    now_ns = now_ns or time.time_ns()
    st = json.loads((day_dir / "status.json").read_text())
    lines = [f"recorder status @ {datetime.fromtimestamp(st['ts_ns'] / 1e9, IST):%Y-%m-%d %H:%M:%S} IST "
             f"(status age {(now_ns - st['ts_ns']) / 1e9:.1f}s, config {st['config_version']})",
             f"ticks/sec {st['ticks_per_s']}  instruments live {len(st['instruments'])}  "
             f"queue {st['queue_depth']}/{st['queue_max']}  dropped {st['dropped_total']}  gaps today {st['gaps_today']}",
             f"connections {st['connections']}  degraded {st['degraded']}  counts {st['counts']}",
             f"{'instrument':<24}{'token':>10}{'packets':>10}{'last tick age s':>17}{'exchange ts':>22}"]
    for tok, s in sorted(st["instruments"].items(), key=lambda kv: kv[1]["symbol"]):
        ex = s.get("last_exchange_ts")
        lines.append(f"{s['symbol']:<24}{tok:>10}{s['packets']:>10}{(now_ns - s['last_receive_ns']) / 1e9:>17.1f}"
                     f"{datetime.fromtimestamp(ex, IST).strftime('%H:%M:%S') if ex else '-':>22}")
    db = day_dir / "buffer.sqlite"
    if db.exists():
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for start, end, conn, kind, reason, count in c.execute("SELECT * FROM gaps ORDER BY start_ns"):
            f = lambda ns: datetime.fromtimestamp(ns / 1e9, IST).strftime("%H:%M:%S.%f")[:-3]  # noqa: E731
            lines.append(f"GAP {kind:<12} conn {conn:>2}  {f(start)} -> {f(end)}  count {count}  {reason}")
        c.close()
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.health")
    ap.add_argument("date", nargs="?", default=None)
    a = ap.parse_args(argv)
    d = load_config().root / (a.date or datetime.now(IST).date().isoformat())
    if not (d / "status.json").exists():
        print(f"no recorder status at {d}", file=sys.stderr)
        return 1
    print(summary(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
