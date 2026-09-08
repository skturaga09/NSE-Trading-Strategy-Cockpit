#!/usr/bin/env python3
"""Contract-specification registry loader (C0.5). The instrument master is authoritative for
live fields; THIS registry is authoritative for settlement/tender/devolvement semantics. A
root is trusted for expiry-sensitive states only when its profile exists AND verified==true."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

_PROFILES = Path(__file__).parent.parent / "config" / "mcx_contract_profiles.json"
_BROKER = Path(__file__).parent.parent / "config" / "broker_mcx_operations.json"


def _load(path: Path, key: Optional[str] = None) -> Dict[str, Any]:
    try:
        d = json.loads(path.read_text())
        return d.get(key, {}) if key else d
    except Exception:
        return {}


def all_profiles() -> Dict[str, Any]:
    return _load(_PROFILES, "profiles")


def profile_for(economic_root: str) -> Optional[Dict[str, Any]]:
    """Profile by economic root (case-insensitive). None if absent."""
    return all_profiles().get((economic_root or "").upper())


def is_verified(economic_root: str) -> bool:
    p = profile_for(economic_root)
    return bool(p and p.get("verified") is True)


def settlement_mode(economic_root: str) -> str:
    """Trusted settlement mode, or 'unknown' when the profile is missing/unverified —
    so downstream expiry logic degrades to HIGH risk / manual review."""
    p = profile_for(economic_root)
    if not p or p.get("verified") is not True:
        return "unknown"
    return p.get("option_settlement_mode", "unknown")


def broker_ops() -> Dict[str, Any]:
    return _load(_BROKER, "broker_mcx_operations")


def broker_cutoff_known() -> bool:
    b = broker_ops()
    return bool(b.get("expiry_devolvement_policy_verified") is True and b.get("last_verified_at"))


def registry_diagnostics() -> Dict[str, Any]:
    """Staleness / verification summary for /api/mcx/health diagnostics."""
    profs = all_profiles()
    return {
        "profiles_present": sorted(profs.keys()),
        "verified_roots": [r for r, p in profs.items() if p.get("verified") is True],
        "unverified_roots": [r for r, p in profs.items() if p.get("verified") is not True],
        "broker_cutoff_verified": broker_cutoff_known(),
        "broker_last_verified_at": broker_ops().get("last_verified_at"),
    }
