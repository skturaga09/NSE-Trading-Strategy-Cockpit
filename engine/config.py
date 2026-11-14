"""Versioned engine config. Every key is required; nothing has a default in code."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO / "config" / "engine" / "v4.yaml"

REQUIRED = [
    "version",
    "ws.max_tokens_per_connection", "ws.max_connections", "ws.reconnect_max_tries", "ws.reconnect_max_delay_s", "ws.stall_after_s",
    "universe.indices", "universe.index_spots", "universe.constituents_max_age_days",
    "tiers.A.spot_mode", "tiers.A.futures_mode", "tiers.B.mode", "tiers.C.mode", "tiers.executor_interval_s",
    "restrictions.ban_list_url", "restrictions.holiday_circulars", "restrictions.holiday_years",
    "restrictions.holidays", "restrictions.special_sessions",
    "http.user_agent", "http.timeout_s",
    "writer.queue_max", "writer.flush_interval_s", "writer.status_interval_s",
    "depth_min_interval_s",
    "storage.root",
    "market_hours.open", "market_hours.close",
    "sessions.fno.open", "sessions.fno.close", "sessions.cash.open", "sessions.cash.close",
    "candles.intervals_min", "candles.out_of_order_window_s", "candles.idle_clock_margin_s", "candles.finalize_delay_s",
    "quality.stale_price_s", "quality.stale_volume_s", "quality.stale_depth_s", "quality.stale_oi_s",
    "baselines.sessions", "baselines.oi_change_windows_min",
    "historical.rate_per_s", "historical.max_days", "historical.oi_intervals",
    "retention.raw_sessions_local", "retention.archive_target",
    "disk_guard.check_interval_s", "disk_guard.alert_below_gb",
    "disk_guard.stop_depth_below_gb", "disk_guard.stop_ticks_below_gb",
]


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class EngineConfig:
    version: str
    sha256: str
    values: Mapping[str, Any]

    def get(self, dotted: str) -> Any:
        v: Any = self.values
        for part in dotted.split("."):
            v = v[part]
        return v

    @property
    def root(self) -> Path:
        p = Path(self.get("storage.root")).expanduser()
        return p if p.is_absolute() else REPO / p


def load_config(path: Path | str = DEFAULT_PATH) -> EngineConfig:
    raw = Path(path).read_bytes()
    values = yaml.safe_load(raw) or {}
    for key in REQUIRED:
        v: Any = values
        for part in key.split("."):
            if not isinstance(v, dict) or v.get(part) in (None, ""):
                raise ConfigError(f"config {path}: required key '{key}' is missing or empty")
            v = v[part]
    return EngineConfig(str(values["version"]), hashlib.sha256(raw).hexdigest(), values)
