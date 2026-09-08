#!/usr/bin/env python3
"""Isolated MCX configuration. Defaults live here; a saved override file (mcx_config.json)
can patch them. Numeric thresholds are configurable defaults, NOT validated trading values."""

import json
from pathlib import Path
from typing import Any, Dict

_FILE = Path(__file__).parent / "mcx_config.json"

DEFAULTS: Dict[str, Any] = {
    "mcx_enabled": True,
    "mcx_watchlist_default": ["CRUDEOIL", "NATURALGAS", "GOLD", "SILVER"],
    "mcx_supported_roots": [
        "CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM",
        "SILVER", "SILVERM", "COPPER", "ZINC", "LEAD", "ALUMINIUM", "NICKEL",
    ],
    "mcx_show_base_metals_default": False,
    "mcx_show_minis_default": False,
    "mcx_instrument_master_ttl_seconds": 21600,
    "mcx_quote_stale_seconds": {"future": 10, "option": 30, "context": 900},
    "mcx_new_entry_min_option_dte": 5,
    "mcx_new_entry_min_future_dte": 3,
    "mcx_roll_transition_warning_days": 7,
    "mcx_disable_new_entries_in_expiry_risk": True,
    "mcx_require_two_sided_option_quote": True,
    "mcx_min_option_liquidity_grade_for_entry": "B",
    "mcx_max_option_spread_pct": {"CRUDEOIL": 8.0, "NATURALGAS": 12.0, "GOLD": 6.0, "SILVER": 8.0},
    "mcx_atr_mult": {"CRUDEOIL": 1.8, "NATURALGAS": 2.5, "GOLD": 2.0, "SILVER": 2.2, "base_metals_default": 1.75},
    "mcx_event_guard_hours": 6,
    "mcx_event_post_release_cooldown_minutes": 30,
    "mcx_block_new_naked_short_options_before_high_event": True,
    "mcx_max_risk_per_trade_pct_equity": 0.5,
    "mcx_max_total_commodity_risk_pct_equity": 2.0,
    "mcx_short_option_requires_defined_risk": True,
    "mcx_option_model": "black76",
    "mcx_probability_use_bid_ask_iv_band": True,
    "breakeven_arm_by_exchange": {"MCX": 8.0},
    # C0.5 expiry / devolvement guards
    "mcx_expiry_risk_enabled": True,
    "mcx_expiry_warning_dte_days": 5,
    "mcx_expiry_critical_dte_days": 1,
    "mcx_expiry_itm_buffer_atr_fraction": 0.15,
    "mcx_block_new_entries_near_option_expiry": True,
    "mcx_block_new_entries_before_tender_period": True,
    "mcx_tender_period_guard_days": 5,
    "mcx_require_settlement_profile_for_enabled_roots": True,
    "mcx_require_manual_review_if_broker_cutoff_unknown": True,
    "mcx_auto_squareoff_enabled": False,
    "mcx_auto_contrary_instruction_enabled": False,
    "mcx_auto_roll_enabled": False,
    # C6a setup radar (intraday evening lane, trend+breakout, ATM leg). Screen, not an edge.
    "mcx_setups_enabled": True,
    "mcx_setup_intraday_interval": "15minute",
    "mcx_setup_min_score": 55,
    "mcx_setup_ema_fast": 9,
    "mcx_setup_ema_slow": 20,
    "mcx_setup_breakout_atr_mult": 1.0,
    "mcx_setup_volume_mult": 1.3,
    "mcx_setup_min_liquidity_grade": "B",
}


def get() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        if _FILE.exists():
            cfg.update(json.loads(_FILE.read_text()))
    except Exception:
        pass
    return cfg
