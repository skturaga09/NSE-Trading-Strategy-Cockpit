"""scripts/sync_launchd.py (owner D-66): auto-install changed launchd jobs, rebuild, restart; never during the session."""

import importlib.util
import os
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_spec = importlib.util.spec_from_file_location("sync_launchd", Path(__file__).resolve().parents[2] / "scripts" / "sync_launchd.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)
IST = ZoneInfo("Asia/Kolkata")
SAT_NOON = datetime(2026, 11, 7, 12, 0, tzinfo=IST)


class Sync(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.repo, self.agents = Path(self.td.name) / "repo", Path(self.td.name) / "agents"
        for d in ("scripts/launchd", "dashboard/web/src", "dashboard/web/fo-engine", "dashboard/web/dist", "engine", "dashboard/api"):
            (self.repo / d).mkdir(parents=True)
        self.agents.mkdir()
        self.calls, self.running, self.server_age_s, self.fail = [], set(), 10_000, set()
        old = time.time() - 50_000
        for f in ("dashboard/web/src/App.tsx", "dashboard/web/dist/index.html", "engine/x.py"):
            (self.repo / f).write_text("x")
            os.utime(self.repo / f, (old, old))
        os.utime(self.repo / "dashboard/web/dist/index.html", (old + 10, old + 10))   # bundle newer than source

    def tearDown(self):
        self.td.cleanup()

    def run_(self, argv, **kw):
        self.calls.append(argv)
        if argv[:2] == ["launchctl", "list"]:
            label = argv[2]
            up = label in self.running or label == S.SERVER
            return subprocess.CompletedProcess(argv, 0, f'{{\n\t"PID" = 4242;\n}}' if up else "", "")
        if argv[0] == "ps":
            return subprocess.CompletedProcess(argv, 0, f"{self.server_age_s // 60:02d}:{self.server_age_s % 60:02d}\n", "")
        bad = any(x in self.fail for x in argv)
        return subprocess.CompletedProcess(argv, 1 if bad else 0, "", "boom" if bad else "")

    def plist(self, name, text="a"):
        (self.repo / "scripts/launchd" / name).write_text(text)

    def sync(self, now=SAT_NOON, alerts=None):
        return S.sync(now, self.repo, self.agents, run=self.run_, alert=(alerts.append if alerts is not None else None))

    def test_never_acts_during_the_session(self):
        self.plist("com.clade.engine-recorder.plist")
        did = self.sync(datetime(2026, 11, 9, 10, 0, tzinfo=IST))
        self.assertTrue(did[0].startswith("skipped"))
        self.assertEqual(self.calls, [])
        self.assertFalse((self.agents / "com.clade.engine-recorder.plist").exists())

    def test_changed_or_missing_plists_are_copied_and_reloaded_identical_ones_untouched(self):
        self.plist("com.clade.engine-intraday.plist", "new")
        self.plist("com.clade.engine-eod.plist", "same")
        (self.agents / "com.clade.engine-eod.plist").write_text("same")
        self.plist("com.clade.muhurat-2026.plist")                    # not an engine-* job: left alone
        did = self.sync()
        self.assertIn("reloaded com.clade.engine-intraday", did)
        self.assertEqual((self.agents / "com.clade.engine-intraday.plist").read_text(), "new")
        self.assertNotIn("bootstrap", str([c for c in self.calls if "com.clade.engine-eod" in str(c)]))
        self.assertFalse((self.agents / "com.clade.muhurat-2026.plist").exists())

    def test_own_plist_is_copied_never_reloaded_and_running_jobs_are_deferred(self):
        self.plist(S.SELF)
        self.plist("com.clade.engine-eod.plist", "v2")
        self.running.add("com.clade.engine-eod")                      # EOD still compacting
        did = self.sync()
        self.assertTrue((self.agents / S.SELF).exists())
        self.assertFalse((self.agents / "com.clade.engine-eod.plist").exists())   # next run still sees it as changed
        self.assertIn("deferred com.clade.engine-eod: running now (next sync reloads it)", did)
        self.assertFalse(any(c[:2] == ["launchctl", "bootout"] for c in self.calls))

    def test_source_newer_than_bundle_rebuilds_then_restarts_and_a_failed_build_alerts(self):
        (self.repo / "dashboard/web/fo-engine/panel.tsx").write_text("y")          # fresh source
        did = self.sync()
        self.assertEqual(did, ["rebuilt dashboard bundle", "restarted dashboard server"])
        self.fail.add("build")
        alerts = []
        did = self.sync(alerts=alerts)
        self.assertTrue(did[0].startswith("error: npm run build"))
        self.assertNotIn("restarted dashboard server", did)
        self.assertEqual(len(alerts), 1)

    def test_server_restarted_only_when_python_changed_after_it_started(self):
        self.assertEqual(self.sync(), ["nothing to do"])                           # code older than the server
        os.utime(self.repo / "engine/x.py")                                          # changed now; server up an hour
        self.server_age_s = 3_600
        self.assertEqual(self.sync(), ["restarted dashboard server"])

    def test_alerts_from_mid_december_until_next_years_holiday_list_is_added(self):
        from unittest import mock
        dec = datetime(2026, 12, 20, 16, 15, tzinfo=IST)
        with mock.patch.object(S, "holiday_years", return_value=[2026]):
            alerts = []
            self.assertTrue(any("2027" in d for d in self.sync(dec, alerts=alerts)))
            self.assertTrue(alerts and "2027" in alerts[0])
            self.assertEqual(self.sync(datetime(2026, 12, 14, 16, 15, tzinfo=IST)), ["nothing to do"])
        with mock.patch.object(S, "holiday_years", return_value=[2026, 2027]):
            self.assertEqual(self.sync(dec), ["nothing to do"])
        self.assertIn(2026, S.holiday_years(S.REPO))                     # the real config is readable

    def test_etime_parser(self):
        self.assertEqual([S.etime_seconds(x) for x in ("05", "01:05", "02:01:05", "3-02:01:05")],
                         [5, 65, 7265, 3 * 86400 + 7265])


if __name__ == "__main__":
    unittest.main()
