# Phase 3 report: live data engine (tiered subscriptions, aggregation, data quality)

Dates: built 2026-11-05 evening and 2026-11-06 (IST), first market-hours session 2026-11-06.
Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, phase-0/1/2 reports.

## 0. Owner decisions taken during this phase

| Question | Decision |
|---|---|
| Tier A mode (quote has no OI / exchange ts, F-WS-6) | **futures full, spot + index quote** (2026-11-05) |
| Live store (Redis not installed, Q-OPS-4) | **no Redis**: event stream + in-process map + per-day SQLite (2026-11-05) |
| Event stream needs gaps/connection events | **approved**: Event kinds `conn`, `gap`; aggregators in arrival order (2026-11-05) |
| Unverified thresholds | **as proposed**: out-of-order window 2 s; stale price/volume 10 s, depth 5 s, OI 300 s; baselines N = 20; OI windows 5/15/60 min; cash session 09:15–15:30 (2026-11-05). **The cash close now looks wrong, see Q-NSE-7** |
| Recorder stuck on a dead socket since 09:03 | **restart now** (2026-11-06 11:26; SIGKILL on purpose, so the real hole became a `restart` gap) |
| Feed watchdog | **add it, N = 10 s** (2026-11-06) |
| Snapshot storage (~810 B/row) | **compact to Parquet at EOD** (2026-11-06) |
| Deploy the watchdog mid-session | **restart now** (2026-11-06 11:34; clean, 8.4 s gap) |

Chosen and flagged, not asked: `candles.finalize_delay_s: 15`, derived from the approved values (it must exceed watchdog 10 s + executor 1 s + writer 1 s); candle quality measured at the candle close; EOD archives a full replay, not the live rows; VWAP = the exchange's `atp`, not recomputed; trade-count proxy = ticks where the cumulative volume rose; OI-change baseline in % (OI ≤ 0 skipped).

## 1. Files

| File | Purpose |
|---|---|
| `engine/tiers.py` | `allocate` (pure plan, limits as inputs), `assign` (stable per-connection placement + ops), `tier_a_requests`, `TierBook` (`promote(token, reason, ttl, tier="B")`, `demote(token)`) |
| `engine/candles.py` | `Aggregator` (candles, OI at close, combined OI, depth snapshots, DataQuality, LateTick, QualityChange), `aggregate()` replay helper |
| `engine/snapshots.py` | `Publisher` (stream + latest map + `snapshots.sqlite`), `Pipeline` (recorder consumer + idle hook), `read_snapshots`, `compact_snapshots` (EOD Parquet = replay; live diff) |
| `engine/backfill.py`, `engine/baselines.py` | Kite historical → `history.sqlite` (`HISTORICAL_API`), token bucket, range cap; volume-by-minute median, OI-change distributions, readers |
| `engine/feed_report.py` | latency, staleness incidents, allocator usage, gaps, max frame gap |
| `engine/recorder.py` | `TierExecutor`; conn/gap events delivered to consumers; `on_idle`; stall watchdog (`check_stall`, `stall` gap, force reconnect); warm start of the pipeline from the day's buffer |
| `engine/store.py`, `engine/replay.py` | `conn_event`, `gap_event`, `arrival_key`; `day_events(..., control=True)` for buffer and Parquet |
| `engine/broker.py` | + `historical()` (read-only GET) |
| `engine/eod.py` | + feed report, snapshot replay archive (before compaction) |
| `engine/config.py`, `config/engine/v3.yaml`, `config/engine/v4.yaml` | v4 default (watchdog + finalize delay); v3 = the bytes run 09:00–11:34 on 2026-11-06; v2 unchanged |
| `engine/provider.py` | docstring only (providers now unused by the recorder) |
| tests | `test_tiers.py` (4), `test_candles.py` (9), `test_phase3_golden.py` (3) + `golden/phase3_session.jsonl`, `test_backfill.py` (4); `test_edges.py` config test → v3 |
| docs | verified-facts §11 (F-WS-13..15, F-HIST-9/10), open-questions (Q-NSE-7, Q-STORE-4, Q-HIST-6, Q-CFG-1, Q-QUAL-1, Q-OPS-3/4, Q-WS-1), architecture §10 |
| `docs/phase-3-evidence/` | raw tests, live feed report, live vs replay check, live backfill |

## 2. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| 1 | Tier A/B/C allocator: pure planning function with limits as inputs + executor | DONE | `test_never_exceeds_limits_for_any_input_size_property`, `test_priority_upgrade_and_drop_reason`, `test_assign_keeps_tokens_on_their_connection`, `test_promote_ttl_demote_and_executor_ops`. Live: 388 tokens tier A (291 full, 97 quote), limit 9000, 0 drops |
| 1b | Over the limit: lowest priority dropped, drop logged with reason | DONE | same tests; `tier_drop` events |
| 1c | promote/demote API for later phases | DONE (in-process) | `TierBook`; nothing calls it yet, so live Tier B/C are empty |
| 2a | 1/3/5/15-min + daily candles: OHLC, volume from cumulative deltas with resets, trade-count proxy, session VWAP, first/last tick ts, tick count | DONE | `test_ohlc_volume_trades_and_rollups`, `test_out_of_order_late_duplicate_and_backwards`, `test_session_edges_holiday_and_non_trading_instrument` |
| 2b | COMPLETE / PARTIAL / EMPTY | DONE | `test_gap_inside_candle_is_partial_with_nothing_interpolated`, golden |
| 2c | OI at candle close from the change log: oi_at_close, oi_last_change_ts, oi_age; never assumed fresh | DONE | `test_oi_age_when_oi_unchanged_for_minutes` |
| 2d | Combined futures OI per underlying, component ages, combined age = max | DONE | `test_rollover_combined_oi_is_continuous` |
| 2e | Spread, mid, top of book, 5-level depth for Tier B | DONE (fixtures) | `test_depth_snapshots_for_tier_b_only`, golden. Live: no Tier B tokens yet |
| 3 | Out-of-order window, late log, duplicates, volume backwards, reconnects (no bridging), pre-open/post-close, holidays, non-trading | DONE | tests above + `test_half_open_socket_becomes_a_stall_gap_once_and_clears_on_reconnect` |
| 4 | DataQuality on every snapshot; staleness per field from config | DONE | every snapshot type carries it; `test_disconnect_goes_stale_within_threshold_and_ok_only_on_fresh_data` |
| 5 | Backfill with Kite historical (oi=1 where verified), labelled, never mixed, token bucket | DONE | `test_backfill_labels_source_records_failures_and_builds_baselines`, `test_token_bucket_never_exceeds_rate`, `test_window_respects_the_measured_range_cap`. Live: 387/387 tokens, 2,953,133 rows, 194 s, 0 failures |
| 6 | Baselines: same-minute volume median over N sessions; rolling OI-change distribution per window | DONE | `test_readers` + backfill test. Live: 387 volume, 291 OI baselines. Jan-2027 futures have only 0–7 sessions (recent listing, F-HIST-7); stored with their true `n_sessions` |
| 7 | Publish to the live store and the event stream | DONE | `Publisher`; live `snapshots.sqlite` (123k rows by 11:40) |
| AT1 | Live and replay of the same session give identical candles (golden file) | DONE (fixture) + checked live | `test_live_and_replay_identical_golden` (2 live delivery patterns = buffer replay = Parquet replay = golden). **Real data:** 0 differing rows after the 11:34 restart (`live-vs-replay-midday.txt`); EOD repeats it for the whole day |
| AT2 | Gap in a candle ⇒ PARTIAL, nothing interpolated | DONE | `test_gap_inside_candle_is_partial_with_nothing_interpolated` |
| AT3 | OI age correct when OI is unchanged for minutes | DONE | `test_oi_age_when_oi_unchanged_for_minutes` (410 s ⇒ DEGRADED) |
| AT4 | Disconnect ⇒ STALE within threshold, back to OK only on fresh data | DONE | `test_disconnect_goes_stale_…` (STALE at exactly last + 10 s; reconnect alone stays STALE) |
| AT5 | Allocator never exceeds limits (property test) | DONE | 300 seeded trials up to 5,000 requests (stdlib `random`; hypothesis not installed) |
| AT6 | Rollover: combined OI continuous while near-month falls and next rises | DONE | `test_rollover_combined_oi_is_continuous` |
| R1 | Measured median/p90 latency from a live session | PARTIAL (midday) | 120,088 packets to 11:40: median 0.784 s, p90 1.171 s, p99 19.6 s. The p99 is snapshot packets with old exchange ts (F-WS-14), not delay. All values biased up 0–1 s (whole-second exchange ts). Full day: EOD `feed_report.json` |
| R2 | Staleness incidents | PARTIAL (midday) | 5,896 recovered incidents, median 17.7 s; mostly far/next-month futures (Q-QUAL-1). One real outage: 09:03:08–11:26:38 (F-WS-15) |
| R3 | Allocator usage per tier | DONE | A 388, B 0, C 0, limit 9000, 0 drops, 1 connection |

## 3. The 2026-11-06 incident (measured)

The Mac was on battery and slept 09:00–09:57 (`pmset -g log`); `caffeinate -s` holds only on AC. Ticks stopped at 09:03:08. After wake, the
KiteTicker socket stayed `connected` with no frames and no close callback, so no gap was written. The live store
filled with EMPTY candles ("no trades") that were wrong. Restarted at 11:26:38 (restart gap logged), then the watchdog was added
and deployed at 11:34 (8.4 s gap). The EOD replay archive replaces the wrong rows; `snapshots_diff.json` will list them.

## 4. Facts used

F-WS-2/4/5/6/7/8/9 (limits, packet fields, library reconnect), F-QUOTE-6/7 (VWAP, pending depth), F-RATE-2, F-HIST-1/2/3/5/7,
F-NSE-1/5 (F&O hours, holidays), F-INST-5. New measured: F-WS-13..15, F-HIST-9/10.

## 5. Open questions (need you)

- **Q-NSE-7, session hours.** Verified (F-NSE-7/9): F&O stocks' continuous trading ends 15:15 now (CAS to 15:35); from 2026-12-07 it ends 15:30 and derivatives trade to 15:45. Config needs date-effective sessions; awaiting your decision.
- Q-CFG-1: DONE, split into v3 (morning bytes, sha verified) and v4 (default).
- **Q-QUAL-1**: 10 s price staleness for far-month futures (very frequent STALE).
- **Q-OPS-3**: charger rule or always-on host (today's outage).
- Q-STORE-4, Q-HIST-6, Q-WS-1: measured at the first EOD.

## 6. Limitations and assumptions

- Every gap marks every instrument's overlapping candles PARTIAL, whatever its connection (one connection today; conservative). `shortcut:` noted for >1 connection.
- Candle windows are in exchange time; gaps are in receive time (latency ≈ 1 s). Quote-mode candles (spot, index) use receive time.
- Change-only ticks (Phase 1 step 9): "no change for 10 s" counts as stale even when the socket is alive.
- A gap that becomes known only after a crash can make earlier live rows wrong. Since the watchdog, that needs a hard crash mid-minute; the EOD replay archive corrects it and counts it.
- The golden file comes from a scripted fixture session. The real-data equivalent is the daily `snapshots_diff.json`.
- `connections_for()` and both providers are no longer used by the recorder (kept, tested).
- Baselines with fewer than N sessions are stored as they are; consumers must read `n_sessions`.
- Historical vs tick-built volume equivalence is unverified (Q-HIST-6).
- Protected assets: `git diff --stat defa774` outside the engine paths shows only Phase 1's `.gitignore`.

## 7. Raw test output

### 7.1 `python3 -m unittest discover -s tests/engine_tests -t . -v` (full file: phase-3-evidence/engine-tests.txt; module paths trimmed)
```
test_backfill_labels_source_records_failures_and_builds_baselines ... ok
test_readers ... ok
test_token_bucket_never_exceeds_rate ... ok
test_window_respects_the_measured_range_cap ... ok
test_depth_snapshots_for_tier_b_only ... ok
test_disconnect_goes_stale_within_threshold_and_ok_only_on_fresh_data ... /Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/yaml/tokens.py:98: ResourceWarning: unclosed database in <sqlite3.Connection object at 0x10d194a90>
test_gap_inside_candle_is_partial_with_nothing_interpolated ... ok
test_ohlc_volume_trades_and_rollups ... ok
test_oi_age_when_oi_unchanged_for_minutes ... ok
test_out_of_order_late_duplicate_and_backwards ... ok
test_rollover_combined_oi_is_continuous ... ok
test_session_edges_holiday_and_non_trading_instrument ... ok
test_window_must_exceed_flush_interval ... ok
test_expired_token_fails_cleanly_without_leaking_token ... ok
test_session_prefers_env_then_config_file ... ok
test_v3_loads_and_missing_key_fails ... ok
test_engine_never_uses_kiteconnect_rest_class ... ok
test_no_order_methods_in_repo_code ... ok
test_connection_limits_from_config ... ok
test_near_future_and_spot_resolve ... ok
test_unknown_symbol_fails_loudly ... ok
test_report_then_compact_snapshots_losslessly ... ok
test_live_and_replay_identical_golden ... ok
test_half_open_socket_becomes_a_stall_gap_once_and_clears_on_reconnect ... ok
test_get_latest_never_returns_future_data_property ... ok
test_real_time_speed_sleeps_by_clock_delta ... ok
test_full_and_index_decode_raw_ints ... ok
test_heartbeat_has_no_packets ... ok
test_unknown_length_is_flagged_not_guessed ... ok
test_change_only_ticks_and_rate_limited_depth ... ok
test_disconnect_open_at_session_end_is_closed_as_gap ... ok
test_disconnect_produces_gap_and_no_synthetic_ticks ... ok
test_disk_guard_degrades_depth_then_ticks_with_gap_records ... ok
test_live_consumers_get_same_events_as_replay ... ok
test_oi_change_log_only_on_change ... ok
test_out_of_order_and_duplicates_stored_as_received_and_replay_deterministic ... ok
test_own_shutdown_close_is_not_a_gap ... ok
test_queue_overflow_logs_gap_not_crash ... ok
test_alert_once_per_day_and_failed_send_is_retried ... [engine] ALERT T: m
test_eod_day_checks ... [engine] ALERT Engine: NOTHING recorded today: No recording for today (ignore if NSE was closed). Check dashboard/logs/engine_recorder.err.log
test_eod_no_data_alert_suppressed_only_on_verified_holiday ... [engine] ALERT Engine: NOTHING recorded today: No recording for today (ignore if NSE was closed). Check dashboard/logs/engine_recorder.err.log
test_unclean_stop_detected_only_without_shutdown ... ok
test_eod_compacts_writes_cadence_and_runs_retention ... [engine] ALERT Engine recorder DIED and did not restart: Last data 09:19:50 IST; no clean shutdown logged.
test_restart_records_gap_and_uses_new_connection_id ... ok
test_single_recorder_lock_and_eod_refuses_while_held ... /Users/turagasanthoshkumar/Clade-NSE-Skills/tests/engine_tests/test_storage.py:251: ResourceWarning: unclosed file <_io.TextIOWrapper name='/tmp/tmpgp13uj5u/recorder.lock' mode='a' encoding='utf-8'>
test_compacted_replay_identical_to_raw_buffer_and_sizes_reported ... ok
test_intervals_from_change_log_excluding_gaps ... ok
test_archive_then_delete_only_with_verified_checksum ... ok
test_mismatch_or_failure_never_deletes ... ok
test_uncompacted_day_is_skipped ... ok
test_assign_keeps_tokens_on_their_connection ... ok
test_never_exceeds_limits_for_any_input_size_property ... ok
test_priority_upgrade_and_drop_reason ... ok
test_promote_ttl_demote_and_executor_ops ... ok
test_grep_logic_modules ... ok
test_parsers_accept_measured_format_only ... ok
test_ban_list_for_another_trade_date_does_not_verify_today ... ok
test_banned_security_not_tradable ... ok
test_expired_contract_never_active_after_expiry ... ok
test_historical_lookup_and_daily_diff ... ok
test_holidays_weekends_and_unverified_circulars ... ok
test_index_tradable_without_any_constituent_list ... ok
test_missing_ban_list_is_restriction_unverified ... ok
test_no_duplicate_underlying_and_fno_derived_from_master ... ok
test_provider_subscribes_spot_near_and_next_in_quote_mode ... ok
test_refresh_is_idempotent_and_refuses_out_of_order ... ok
test_stale_constituents_flagged_then_blocked ... ok
test_strike_intervals_derived_from_listed_strikes ... ok
test_token_reused_for_another_contract_resolves_by_date ... ok

Ran 69 tests

OK
exit=0
```

### 7.2 Whole repo `python3 -m unittest discover -s tests -v` (phase-3-evidence/full-suite.txt)
```
Ran 132 tests in 7.340s

OK
exit=0
```

### 7.3 Live evidence
`feed-report-midday.json`, `live-vs-replay-midday.txt`, `live-backfill-smoke.txt`, `live-backfill.txt`.
