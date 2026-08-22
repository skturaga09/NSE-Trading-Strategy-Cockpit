#!/usr/bin/env python3
"""
Refresh the Zerodha Kite Connect access_token — run daily by launchd.

Zerodha forces the access_token to expire every day (~7:30 AM). This script
performs the official Kite Connect login flow headlessly using credentials read
from the macOS Keychain, generating the 2FA code from your TOTP seed, then writes
the fresh token into dashboard/kite_config.json so the dashboard picks it up.

Flow (all against Zerodha's own endpoints):
  1. POST /api/login        (user_id, password)      -> request_id
  2. POST /api/twofa        (request_id, TOTP)        -> authenticated session
  3. GET  /connect/login    (api_key)                 -> redirect carrying request_token
  4. POST /session/token    (api_key, request_token, sha256 checksum) -> access_token

Requires: requests, pyotp. Secrets in Keychain (see kite_secrets.py / README.md).
Exit code 0 on success, non-zero on failure (visible in the launchd log).
"""

import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin

BASE_DIR = Path(__file__).resolve().parent.parent          # dashboard/
CONFIG_FILE = BASE_DIR / "kite_config.json"
LOG_FILE = BASE_DIR / "logs" / "kite_refresh.log"

sys.path.insert(0, str(Path(__file__).resolve().parent))   # for kite_secrets
from kite_secrets import load_all, missing                  # noqa: E402


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def refresh() -> int:
    try:
        import requests
        import pyotp
    except ImportError as e:
        log(f"FATAL: missing dependency ({e}). Run: pip install requests pyotp")
        return 2

    secrets = load_all()
    miss = missing(secrets)
    if miss:
        log(f"FATAL: missing Keychain secrets: {', '.join(miss)}. See README.md")
        return 3

    api_key = secrets["api_key"]
    api_secret = secrets["api_secret"]
    user_id = secrets["user_id"]
    password = secrets["password"]
    totp_secret = secrets["totp_secret"]

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "X-Kite-Version": "3",
    })

    try:
        # 1. Password login
        r = s.post("https://kite.zerodha.com/api/login",
                   data={"user_id": user_id, "password": password}, timeout=15)
        j = r.json()
        if j.get("status") != "success":
            log(f"FATAL: login failed: {j.get('message', r.text[:200])}")
            return 4
        request_id = j["data"]["request_id"]

        # 2. TOTP 2FA
        otp = pyotp.TOTP(totp_secret).now()
        r = s.post("https://kite.zerodha.com/api/twofa",
                   data={"user_id": user_id, "request_id": request_id,
                         "twofa_value": otp, "twofa_type": "totp"}, timeout=15)
        j = r.json()
        if j.get("status") != "success":
            log(f"FATAL: TOTP 2FA failed: {j.get('message', r.text[:200])}")
            return 5

        # 3. Kite Connect login -> capture request_token from the redirect chain
        # Walk the redirect chain manually. The final hop points at the app's
        # redirect URL (e.g. http://127.0.0.1:8000/?...request_token=...), which is
        # NOT served — so we must read request_token out of the Location header
        # rather than let requests follow it (that would raise ConnectionError).
        request_token = None
        url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
        for _ in range(10):
            qs = parse_qs(urlparse(url).query)
            if "request_token" in qs:
                request_token = qs["request_token"][0]
                break
            r = s.get(url, allow_redirects=False, timeout=15)
            loc = r.headers.get("Location")
            if not loc:
                break
            url = urljoin(url, loc)  # resolve relative redirects
        if not request_token:
            log("FATAL: could not capture request_token. Check that the app's "
                "redirect URL is set in the Kite developer console.")
            return 6

        # 4. Exchange request_token for access_token (SHA-256 checksum)
        checksum = hashlib.sha256(
            (api_key + request_token + api_secret).encode("utf-8")
        ).hexdigest()
        r = requests.post("https://api.kite.trade/session/token",
                          data={"api_key": api_key, "request_token": request_token,
                                "checksum": checksum},
                          headers={"X-Kite-Version": "3"}, timeout=15)
        j = r.json()
        if j.get("status") != "success":
            log(f"FATAL: session/token exchange failed: {j.get('message', r.text[:200])}")
            return 7
        access_token = j["data"]["access_token"]

    except Exception as e:
        log(f"FATAL: unexpected error during login: {e!r}")
        return 8

    # Write config (preserve any existing enctoken)
    config = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            config = {}
    config.update({
        "api_key": api_key,
        "access_token": access_token,
        "enctoken": config.get("enctoken", ""),
        "is_connected": True,
        "token_refreshed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    log(f"SUCCESS: access_token refreshed and written to {CONFIG_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(refresh())
