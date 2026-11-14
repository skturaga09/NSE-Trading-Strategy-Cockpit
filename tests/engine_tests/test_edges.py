import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import yaml

from engine.broker import KiteSession, TokenExpired
from engine.config import DEFAULT_PATH, REPO, ConfigError, load_config
from engine.provider import ConfigSubscriptionProvider, parse_master
from engine.recorder import connections_for

from .fixtures import make_config

MASTER = b"""instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
1,1,NIFTY26OCTFUT,NIFTY,0,2026-10-27,0,0.1,65,FUT,NFO-FUT,NFO
2,2,NIFTY26NOVFUT,NIFTY,0,2026-11-24,0,0.1,65,FUT,NFO-FUT,NFO
3,3,NIFTY26DECFUT,NIFTY,0,2026-12-29,0,0.1,65,FUT,NFO-FUT,NFO
4,4,NIFTY26N2424000CE,NIFTY,0,2026-11-24,24000,0.05,65,CE,NFO-OPT,NFO
256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE
738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.1,1,EQ,NSE,NSE
"""


class TestConfig(unittest.TestCase):
    def test_v4_loads_and_missing_key_fails(self):
        cfg = load_config()
        self.assertEqual(cfg.version, "v4")
        self.assertEqual(cfg.get("ws.stall_after_s"), 10)          # owner decision 2026-11-06
        self.assertEqual(cfg.get("tiers.A.futures_mode"), "full")  # owner decision 2026-11-05
        self.assertEqual(cfg.get("universe.constituents_max_age_days"), 3)
        self.assertEqual(cfg.get("ws.max_tokens_per_connection"), 3000)
        v = yaml.safe_load(DEFAULT_PATH.read_text())
        v["disk_guard"]["stop_ticks_below_gb"] = None
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as f:
            yaml.safe_dump(v, f)
            with self.assertRaises(ConfigError):
                load_config(f.name)


class TestProvider(unittest.TestCase):
    def test_near_future_and_spot_resolve(self):
        p = ConfigSubscriptionProvider(
            [{"exchange": "NFO", "name": "NIFTY", "select": "near_future", "mode": "full"},
             {"exchange": "NSE", "tradingsymbol": "NIFTY 50", "mode": "full"},
             {"exchange": "NSE", "tradingsymbol": "RELIANCE", "mode": "quote"}],
            parse_master(MASTER), date(2026, 11, 5))
        self.assertEqual(p.subscriptions(), {2: "full", 256265: "full", 738561: "quote"})
        p.day = date(2026, 11, 25)
        self.assertEqual(min(p.subscriptions()), 3)  # rolls to DEC after NOV expiry

    def test_unknown_symbol_fails_loudly(self):
        p = ConfigSubscriptionProvider([{"exchange": "NSE", "tradingsymbol": "NOPE", "mode": "full"}],
                                       parse_master(MASTER), date(2026, 11, 5))
        with self.assertRaises(LookupError):
            p.subscriptions()

    def test_connection_limits_from_config(self):
        cfg = make_config(Path("/tmp"), **{"ws.max_tokens_per_connection": 2, "ws.max_connections": 2})
        self.assertEqual(len(connections_for({1: "full", 2: "full", 3: "full"}, cfg)), 2)
        with self.assertRaises(ValueError):
            connections_for({i: "full" for i in range(5)}, cfg)


class TestBroker(unittest.TestCase):
    def test_quote_batch_rejected_with_400_is_halved_and_retried(self):   # Kite front end on long requests
        import requests
        from engine.broker import KiteSession
        s, sizes = KiteSession("k", "t", "env"), []

        class R:
            def __init__(self, ks):
                self.ks = ks

            def json(self):
                return {"data": {k: {"last_price": 1} for k in self.ks}}

        def get(path, i):
            sizes.append(len(i))
            if len(i) > 2:
                resp = requests.Response()
                resp.status_code = 400
                raise requests.HTTPError("400 Bad Request", response=resp)
            return R(i)
        s._get, s._last_quote = get, 0.0
        out = s.quote([f"NFO:K{n}" for n in range(8)], 8, 1000.0, sleep=lambda x: None, clock=lambda: 1e9)
        self.assertEqual(sorted(out), sorted(f"NFO:K{n}" for n in range(8)))
        self.assertEqual(sizes, [8, 4, 2, 2, 4, 2, 2])


    def test_expired_token_fails_cleanly_without_leaking_token(self):
        s = KiteSession("key", "SECRET-TOKEN", "env")
        r = mock.Mock(status_code=403, text='{"status":"error","error_type":"TokenException"}')
        with mock.patch("engine.broker.requests.get", return_value=r):
            with self.assertRaises(TokenExpired) as cm:
                s.check()
        self.assertNotIn("SECRET-TOKEN", str(cm.exception))

    def test_session_prefers_env_then_config_file(self):
        with mock.patch.dict("os.environ", {"KITE_API_KEY": "k", "KITE_ACCESS_TOKEN": "t"}):
            self.assertEqual(KiteSession.load().source, "env")
        with mock.patch.dict("os.environ", {}, clear=True), tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            f.write('{"api_key": "k", "access_token": "t"}')
            f.flush()
            self.assertEqual(KiteSession.load(Path(f.name)).source, "kite_config.json")
            with self.assertRaises(TokenExpired):
                KiteSession.load(Path(f.name + ".missing"))


class TestNoOrderCode(unittest.TestCase):
    """Fails if order placement/modification/cancellation names appear in any tracked or new code file
    outside this test (which asserts their absence)."""

    NAMES = ("place_order", "modify_order", "cancel_order")

    def test_no_order_methods_in_repo_code(self):
        files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard",
                                "*.py", "*.ts", "*.tsx", "*.js", "*.sh"],
                               cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
        me = Path(__file__).resolve()
        hits = [f"{f}: {n}" for f in files if (REPO / f).resolve() != me and (REPO / f).exists()
                for n in self.NAMES if n in (REPO / f).read_text(errors="ignore")]
        self.assertEqual(hits, [])

    def test_engine_never_uses_kiteconnect_rest_class(self):
        for f in (REPO / "engine").rglob("*.py"):
            self.assertNotIn("KiteConnect(", f.read_text(), f)


if __name__ == "__main__":
    unittest.main()
