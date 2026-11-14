"""Read-only Kite broker adapter. There are NO order methods here, by design.

Session source (reuses the dashboard's existing auth):
  1. env KITE_API_KEY + KITE_ACCESS_TOKEN, if both set;
  2. else dashboard/kite_config.json, written daily by dashboard/scripts/refresh_kite_token.py.
The access token is never logged or printed.

Endpoints/headers: F-AUTH-1/2, F-INST-1, F-QUOTE-1, F-HIST-1/2. Expiry: F-AUTH-6/7/8. WebSocket: F-WS-1/2, F-WS-8.
The KiteConnect REST class from the kiteconnect library is deliberately NOT used (it carries order
methods); only its KiteTicker is.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .config import REPO, EngineConfig

ROOT = "https://api.kite.trade"
KITE_CONFIG = REPO / "dashboard" / "kite_config.json"


class TokenExpired(RuntimeError):
    """F-AUTH-7: HTTP 403 TokenException. Fix: run the refresh flow, then restart."""


@dataclass
class KiteSession:
    api_key: str
    access_token: str
    source: str  # 'env' | 'kite_config.json'
    _last_quote: float = field(default=float("-inf"), repr=False)

    @classmethod
    def load(cls, config_file: Path = KITE_CONFIG) -> "KiteSession":
        key, tok = os.environ.get("KITE_API_KEY"), os.environ.get("KITE_ACCESS_TOKEN")
        if key and tok:
            return cls(key, tok, "env")
        try:
            kc = json.loads(Path(config_file).read_text())
        except (OSError, ValueError) as e:
            raise TokenExpired(f"no session: env KITE_API_KEY/KITE_ACCESS_TOKEN unset and {config_file} unreadable ({e})")
        if not (kc.get("api_key") and kc.get("access_token")):
            raise TokenExpired(f"no session: {config_file} has no api_key/access_token")
        return cls(kc["api_key"], kc["access_token"], "kite_config.json")

    def _headers(self) -> dict:
        return {"X-Kite-Version": "3", "Authorization": f"token {self.api_key}:{self.access_token}"}

    def _get(self, path: str, **params) -> requests.Response:
        r = requests.get(f"{ROOT}{path}", headers=self._headers(), params=params, timeout=60)
        if r.status_code == 403 or "TokenException" in r.text[:300]:
            raise TokenExpired(f"{path}: HTTP {r.status_code} TokenException; access token expired or invalidated "
                               f"(source={self.source}). Run: python3 dashboard/scripts/refresh_kite_token.py")
        r.raise_for_status()
        return r

    def check(self) -> None:
        """Cheap authenticated call (one /quote key). Raises TokenExpired cleanly."""
        self._get("/quote", i="NSE:NIFTY 50")

    def quote(self, keys: list[str], batch: int, rate_per_s: float, sleep=time.sleep, clock=time.monotonic) -> dict:
        """GET /quote for 'EXCHANGE:TRADINGSYMBOL' keys, read-only (F-QUOTE-1: <= 500 per request; F-RATE-1: 1 req/s),
        batched and paced here. -> {key: (payload as served, receive_ns of its batch)}."""
        out = {}

        def fetch(ks: list[str]) -> None:
            wait = self._last_quote + 1 / rate_per_s - clock()
            if wait > 0:
                sleep(wait)
            self._last_quote = clock()
            try:
                data = self._get("/quote", i=ks).json()["data"]
            except requests.HTTPError as e:
                # Kite's front end sometimes answers a full batch with a bare HTML 400 (long request); halve and retry
                if e.response is not None and e.response.status_code == 400 and len(ks) > 1:
                    fetch(ks[:len(ks) // 2])
                    fetch(ks[len(ks) // 2:])
                    return
                raise
            rns = time.time_ns()
            out.update({k: (v, rns) for k, v in data.items()})

        for i in range(0, len(keys), batch):
            fetch(keys[i:i + batch])
        return out

    def instruments_csv(self) -> bytes:
        """Full instrument master dump (all exchanges), CSV bytes as served (F-INST-1/2)."""
        return self._get("/instruments").content

    def historical(self, token: int, interval: str, start: str, end: str, oi: bool) -> list[list]:
        """GET /instruments/historical/:token/:interval (F-HIST-1/2); start/end 'YYYY-MM-DD HH:MM:SS' IST.
        Rows [ts, open, high, low, close, volume(, oi)] as served. Callers rate-limit (F-RATE-2) and cap ranges (F-HIST-5)."""
        params = {"from": start, "to": end, **({"oi": 1} if oi else {})}
        return self._get(f"/instruments/historical/{token}/{interval}", **params).json()["data"]["candles"]

    def refresh(self) -> "KiteSession":
        """Token refresh flow: reuse the dashboard's headless login, then reload the session."""
        if self.source == "env":
            raise TokenExpired("session came from env vars; refresh them yourself (the refresh flow writes kite_config.json)")
        from dashboard.scripts.refresh_kite_token import refresh  # protected module: imported, never edited
        rc = refresh()
        if rc != 0:
            raise TokenExpired(f"refresh_kite_token.refresh() exited {rc}; see dashboard/logs/kite_refresh.log")
        return KiteSession.load()

    def ticker(self, cfg: EngineConfig):
        from kiteconnect import KiteTicker
        return KiteTicker(self.api_key, self.access_token,
                          reconnect_max_tries=cfg.get("ws.reconnect_max_tries"),
                          reconnect_max_delay=cfg.get("ws.reconnect_max_delay_s"))
