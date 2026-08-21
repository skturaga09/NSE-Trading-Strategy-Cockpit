#!/usr/bin/env python3
"""
Read Kite automation secrets from the macOS login Keychain.

Nothing sensitive is ever written to disk by this project. You store each
secret once with `security add-generic-password` (see dashboard/scripts/README.md),
and this helper reads them at runtime via the `security` CLI.

Service names (account is always "kite"):
    kite-api-key       Kite Connect API key
    kite-api-secret    Kite Connect API secret
    kite-user-id       Zerodha user id (e.g. AB1234)
    kite-password      Zerodha login password
    kite-totp-secret   TOTP seed (base32) behind your authenticator app
"""

import subprocess
from typing import Optional, Dict

ACCOUNT = "kite"
SERVICES = {
    "api_key": "kite-api-key",
    "api_secret": "kite-api-secret",
    "user_id": "kite-user-id",
    "password": "kite-password",
    "totp_secret": "kite-totp-secret",
}


def read_secret(service: str, account: str = ACCOUNT) -> Optional[str]:
    """Return one secret from the Keychain, or None if it is not set."""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def load_all() -> Dict[str, Optional[str]]:
    """Read every Kite secret. Missing ones come back as None."""
    return {key: read_secret(service) for key, service in SERVICES.items()}


def missing(secrets: Dict[str, Optional[str]]) -> list:
    """Names of any secrets that are not yet stored in the Keychain."""
    return [k for k, v in secrets.items() if not v]


if __name__ == "__main__":
    s = load_all()
    print("Kite Keychain secrets:")
    for k in SERVICES:
        print(f"  {k:12s}: {'set' if s[k] else 'MISSING'}")
    miss = missing(s)
    if miss:
        print("\nMissing:", ", ".join(miss))
        print("See dashboard/scripts/README.md to store them.")
