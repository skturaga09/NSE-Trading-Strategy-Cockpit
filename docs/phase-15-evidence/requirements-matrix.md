| phase | # | requirement | status (report) | files cited | proving tests | latest result | GAP |
|---|---|---|---|---|---|---|---|
| 0 | T1 | Inventory each component: path, purpose, works?, reusability for auth, instruments, WebSocket, historical, indicators, storage, backtesting … | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T1b | Locate the 5-year NIFTY data: location, format, granularity, OI?, range | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T2 | List strategies, configs, live/paper records as Protected assets in architecture.md | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3 | verified-facts.md with URL + access date + short quote for each listed topic | DONE, with gaps | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3a | KiteTicker modes and fields (OI, OI day high/low, depth, timestamps) | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3b | Max instruments per connection, max connections per key | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3c | Historical: intervals, max days per request, `oi=1` support, rate limits | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3d | Quote/LTP limits and rate limits | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3e | Instrument master endpoint and fields | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3f | Session/token expiry | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T3h | SEBI retail algo framework status (context) | DONE (context only) | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T4 | `scripts/verify_kite.py`, read-only, env credentials, no subscriptions/orders | DONE (owner to run) | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T5 | architecture.md: module map, data flow, storage choice, raw-observation schema, process model, interfaces, reuse marks | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | T6 | build-plan.md: phases 1–14, file-level for 1 and 2, a paragraph for the rest | PARTIAL | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 0 | A1 | The five docs exist | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | A2 | Every fact has URL + access date | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | A3 | Protected assets untouched (git diff) | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 0 | A4 | No new production modules | DONE | scripts/verify_kite.py | — | NO TEST (evidence / run log only) | NO TEST |
| 1 | 1 | Broker adapter: session from env, token refresh flow, clean failure on expired token, no order methods | DONE | — | test_expired_token_fails_cleanly_without_leaking_token, test_session_prefers_env_then_config_file | PASS (2 engine) | — |
| 1 | 2 | SubscriptionProvider, config-listed symbols resolved via the master at startup | DONE | — | test_near_future_and_spot_resolve, test_unknown_symbol_fails_loudly | PASS (2 engine) | — |
| 1 | 3a | KiteTicker, limits read from config (F-WS-2) | DONE | — | test_connection_limits_from_config | PASS (1 engine) | — |
| 1 | 3b | Every tick as received + receive_ts, exchange_ts, last_trade_ts, token, mode, connection_id, per-connection seq | DONE | — | test_out_of_order_and_duplicates_stored_as_received_and_replay_deterministic | PASS (1 engine) | — |
| 1 | 3c | OI change log, a row only when OI changes, with the exchange ts of the change | DONE | — | test_oi_change_log_only_on_change | PASS (1 engine) | — |
| 1 | 3d | Depth snapshots for full-mode instruments | DONE | — | test_change_only_ticks_and_rate_limited_depth | PASS (1 engine) | — |
| 1 | 3e | Connection events; gaps detectable from data alone | DONE | — | test_disconnect_open_at_session_end_is_closed_as_gap, test_disconnect_produces_gap_and_no_synthetic_ticks, test_own_shutdown_close_is_not_a_gap | PASS (3 engine) | — |
| 1 | 3f | Daily full instrument master snapshot with the date | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 1 | 3g | Append-only, partitioned by date; buffered writes; bounded queue; queue metric; drops logged as a gap | DONE | — | test_queue_overflow_logs_gap_not_crash | PASS (1 engine) | — |
| 1 | 4 | Replay in (exchange_ts, receive_ts, seq) order through the live interface; ReplayClock; AsOfStore; max speed or real-time multiple | DONE | — | test_get_latest_never_returns_future_data_property, test_live_consumers_get_same_events_as_replay, test_real_time_speed_sleeps_by_clock_delta | PASS (3 engine) | — |
| 1 | 5 | Health CLI: ticks/s, instruments live, last tick age, queue depth, gaps today | DONE | — | test_health_from_status_files | PASS (1 engine) | — |
| 1 | 6 | OI cadence measurement → docs/measured-oi-cadence.md | PARTIAL | — | test_intervals_from_change_log_excluding_gaps | PASS (1 engine) | PARTIAL |
| 1 | 7 | Bytes/day per table on one recorded session | PARTIAL | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 1 | 8 | Parquet zstd typed + raw-frames alternative, prototyped on the same session, size + replay speed, pick one, record in architecture.md | PARTIAL | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 1 | 9 | Change-only depth (≤1/s/instrument, config) and ticks; determinism tests still pass | DONE | — | test_change_only_ticks_and_rate_limited_depth, test_intervals_from_change_log_excluding_gaps | PASS (2 engine) | — |
| 1 | 10 | Retention: derived data forever, raw for N sessions then archive (local/S3), checksum-verified before delete | DONE | — | test_archive_then_delete_only_with_verified_checksum, test_mismatch_or_failure_never_deletes, test_uncompacted_day_is_skipped | PASS (3 engine) | — |
| 1 | 11 | Disk guard: alert, then stop depth, then ticks; each logged as a gap | DONE | — | test_disk_guard_degrades_depth_then_ticks_with_gap_records | PASS (1 engine) | — |
| 1 | AT1 | Out-of-order/duplicates stored as received, deterministic order, byte-identical replays | DONE | — | test_out_of_order_and_duplicates_stored_as_received_and_replay_deterministic | PASS (1 engine) | — |
| 1 | AT2 | AsOfStore never returns receive_ts > as_of (property test) | DONE | — | test_get_latest_never_returns_future_data_property | PASS (1 engine) | — |
| 1 | AT3 | Disconnect → gap record, no synthetic ticks | DONE | — | test_disconnect_open_at_session_end_is_closed_as_gap, test_disconnect_produces_gap_and_no_synthetic_ticks, test_own_shutdown_close_is_not_a_gap | PASS (3 engine) | — |
| 1 | AT4 | OI log only on change | DONE | — | test_oi_change_log_only_on_change | PASS (1 engine) | — |
| 1 | AT5 | Queue overflow → logged gap, no crash | DONE | — | test_queue_overflow_logs_gap_not_crash | PASS (1 engine) | — |
| 1 | AT6 | No order code (grep test in CI) | DONE | — | test_engine_never_uses_kiteconnect_rest_class, test_no_order_methods_in_repo_code | PASS (2 engine) | — |
| 1 | AT7 | Size per day before and after optimization | PARTIAL | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 1 | AT8 | Replay of the compacted day identical to the raw buffer | DONE | — | test_compacted_replay_identical_to_raw_buffer_and_sizes_reported | PASS (1 engine) | — |
| 1 | AT9 | Archive-then-delete never removes a file without a verified checksum | DONE | — | test_archive_then_delete_only_with_verified_checksum, test_mismatch_or_failure_never_deletes, test_uncompacted_day_is_skipped | PASS (3 engine) | — |
| 1 | AT10 | Disk-guard degradation → gap records | DONE | — | test_disk_guard_degrades_depth_then_ticks_with_gap_records | PASS (1 engine) | — |
| 2 | 1 | Constituents from official source, URL in verified-facts, stored daily with source + fetch time | DONE | — | test_stale_constituents_flagged_then_blocked | PASS (1 engine) | — |
| 2 | 1b | Failed fetch → last good list only if ≤ N days old, flagged STALE_CONSTITUENTS; older → block | DONE | — | test_index_tradable_without_any_constituent_list, test_stale_constituents_flagged_then_blocked | PASS (2 engine) | — |
| 2 | 2 | Universe = (N50 ∪ N100) ∩ active NFO futures; dedup; INDEX family; F&O derived, never assumed | DONE | — | test_no_duplicate_underlying_and_fno_derived_from_master | PASS (1 engine) | — |
| 2 | 3 | Registry: underlying, spot token, futures (all active expiries), option tokens, tradingsymbol, type, expiry, strike, lot, tick, segment, act… | DONE | — | test_historical_lookup_and_daily_diff | PASS (1 engine) | — |
| 2 | 3b | Strike intervals derived from listed strikes | DONE | — | test_strike_intervals_derived_from_listed_strikes | PASS (1 engine) | — |
| 2 | 4 | Daily pre-open job: download, diff vs yesterday, log added/removed/lot changes/rollovers; keep history | DONE | — | test_historical_lookup_and_daily_diff, test_refresh_is_idempotent_and_refuses_out_of_order, test_token_reused_for_another_contract_resolves_by_date | PASS (3 engine) | — |
| 2 | 5a | Ban list from official source daily, source + time | DONE | — | test_banned_security_not_tradable | PASS (1 engine) | — |
| 2 | 5b | Expiries from master; holidays from official source | DONE | — | test_holidays_weekends_and_unverified_circulars | PASS (1 engine) | — |
| 2 | 5c | Source not fetched/verified today → RESTRICTION_UNVERIFIED, not tradable | DONE | — | test_ban_list_for_another_trade_date_does_not_verify_today, test_missing_ban_list_is_restriction_unverified | PASS (2 engine) | — |
| 2 | 6 | UniverseSubscriptionProvider: spot + near + next futures, quote mode | DONE | — | test_provider_subscribes_spot_near_and_next_in_quote_mode | PASS (1 engine) | — |
| 2 | 7 | API get_universe / get_contracts / get_contract / is_tradable | DONE | — | test_provider_subscribes_spot_near_and_next_in_quote_mode | PASS (1 engine) | — |
| 2 | AT1 | No duplicate underlying | DONE | — | test_no_duplicate_underlying_and_fno_derived_from_master | PASS (1 engine) | — |
| 2 | AT2 | Constituent without NFO never in universe | DONE | — | test_no_duplicate_underlying_and_fno_derived_from_master | PASS (1 engine) | — |
| 2 | AT3 | Expired contracts never active after expiry | DONE | — | test_expired_contract_never_active_after_expiry | PASS (1 engine) | — |
| 2 | AT4 | Banned → False, BANNED | DONE | — | test_banned_security_not_tradable | PASS (1 engine) | — |
| 2 | AT5 | Missing ban list → RESTRICTION_UNVERIFIED | DONE | — | test_ban_list_for_another_trade_date_does_not_verify_today, test_missing_ban_list_is_restriction_unverified | PASS (2 engine) | — |
| 2 | AT6 | Grep test: no numeric lot sizes or date literals in logic modules | DONE | engine/*.py | test_grep_logic_modules | PASS (1 engine) | — |
| 2 | AT7 | get_contract(token, past_date) returns that date's mapping | DONE | — | test_token_reused_for_another_contract_resolves_by_date | PASS (1 engine) | — |
| 3 | 1 | Tier A/B/C allocator: pure planning function with limits as inputs + executor | DONE | — | test_assign_keeps_tokens_on_their_connection, test_never_exceeds_limits_for_any_input_size_property, test_priority_upgrade_and_drop_reason, test_promote_ttl_demote_and_executor_ops | PASS (4 engine) | — |
| 3 | 1b | Over the limit: lowest priority dropped, drop logged with reason | DONE | — | test_assign_keeps_tokens_on_their_connection, test_never_exceeds_limits_for_any_input_size_property, test_priority_upgrade_and_drop_reason, test_promote_ttl_demote_and_executor_ops | PASS (4 engine) | — |
| 3 | 1c | promote/demote API for later phases | DONE (in-process) | — | test_promote_ttl_demote_and_executor_ops | PASS (1 engine) | — |
| 3 | 2a | 1/3/5/15-min + daily candles: OHLC, volume from cumulative deltas with resets, trade-count proxy, session VWAP, first/last tick ts, tick cou… | DONE | — | test_ohlc_volume_trades_and_rollups, test_out_of_order_late_duplicate_and_backwards, test_session_edges_holiday_and_non_trading_instrument | PASS (3 engine) | — |
| 3 | 2b | COMPLETE / PARTIAL / EMPTY | DONE | — | test_gap_inside_candle_is_partial_with_nothing_interpolated | PASS (1 engine) | — |
| 3 | 2c | OI at candle close from the change log: oi_at_close, oi_last_change_ts, oi_age; never assumed fresh | DONE | — | test_oi_age_when_oi_unchanged_for_minutes | PASS (1 engine) | — |
| 3 | 2d | Combined futures OI per underlying, component ages, combined age = max | DONE | — | test_rollover_combined_oi_is_continuous | PASS (1 engine) | — |
| 3 | 2e | Spread, mid, top of book, 5-level depth for Tier B | DONE (fixtures) | — | test_depth_snapshots_for_tier_b_only | PASS (1 engine) | — |
| 3 | 3 | Out-of-order window, late log, duplicates, volume backwards, reconnects (no bridging), pre-open/post-close, holidays, non-trading | DONE | — | test_half_open_socket_becomes_a_stall_gap_once_and_clears_on_reconnect | PASS (1 engine) | — |
| 3 | 4 | DataQuality on every snapshot; staleness per field from config | DONE | — | test_disconnect_goes_stale_within_threshold_and_ok_only_on_fresh_data | PASS (1 engine) | — |
| 3 | 5 | Backfill with Kite historical (oi=1 where verified), labelled, never mixed, token bucket | DONE | — | test_backfill_labels_source_records_failures_and_builds_baselines, test_token_bucket_never_exceeds_rate, test_window_respects_the_measured_range_cap | PASS (3 engine) | — |
| 3 | 6 | Baselines: same-minute volume median over N sessions; rolling OI-change distribution per window | DONE | — | test_readers | PASS (1 engine) | — |
| 3 | 7 | Publish to the live store and the event stream | DONE | — | test_report_then_compact_snapshots_losslessly | PASS (1 engine) | — |
| 3 | AT1 | Live and replay of the same session give identical candles (golden file) | DONE (fixture) + checked live | — | test_live_and_replay_identical_golden | PASS (1 engine) | — |
| 3 | AT2 | Gap in a candle ⇒ PARTIAL, nothing interpolated | DONE | — | test_gap_inside_candle_is_partial_with_nothing_interpolated | PASS (1 engine) | — |
| 3 | AT3 | OI age correct when OI is unchanged for minutes | DONE | — | test_oi_age_when_oi_unchanged_for_minutes | PASS (1 engine) | — |
| 3 | AT4 | Disconnect ⇒ STALE within threshold, back to OK only on fresh data | DONE | — | test_disconnect_goes_stale_within_threshold_and_ok_only_on_fresh_data | PASS (1 engine) | — |
| 3 | AT5 | Allocator never exceeds limits (property test) | DONE | — | test_allocator_never_exceeds_limits_with_option_tier, test_never_exceeds_limits_for_any_input_size_property | PASS (2 engine) | — |
| 3 | AT6 | Rollover: combined OI continuous while near-month falls and next rises | DONE | — | test_rollover_combined_oi_is_continuous | PASS (1 engine) | — |
| 3 | R1 | Measured median/p90 latency from a live session | PARTIAL (midday) | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 3 | R2 | Staleness incidents | PARTIAL (midday) | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 3 | R3 | Allocator usage per tier | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 4 | In | Pure functions over snapshot objects + config | DONE (+ history store, owner) | — | test_pure_modules_do_no_io_and_read_no_clock | PASS (1 engine) | — |
| 4 | F1 | Price change 1/3/5/15/30 min, futures and spot | DONE | — | test_each_quadrant | PASS (1 engine) | — |
| 4 | F2 | OI change 5/15/30 min + vs previous session close, combined default, near-month secondary; windows shorter than the measured cadence disable… | DONE | — | test_window_shorter_than_measured_cadence_is_disabled | PASS (1 engine) | — |
| 4 | F3 | RVOL vs same-time baseline | DONE (Q-HIST-6) | — | — | NO TEST (evidence / run log only) | NO TEST |
| 4 | F4 | Volume vs OI-change ratio | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 4 | F5 | VWAP deviation in ATR, ATR-normalized move, momentum | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 4 | F6 | Basis, its change, abnormal flag | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 4 | F7 | OI-change percentile vs own rolling distribution | DONE | — | test_low_sample_history | PASS (1 engine) | — |
| 4 | F8 | Rolling beta vs NIFTY futures, residual per window; optional sector residual | DONE / sector **skipped** (Q-POS-3) | — | test_move_with_beta_times_index_is_index_driven | PASS (1 engine) | — |
| 4 | DQ | Each feature has its own DataQuality; UNAVAILABLE if any input not OK | DONE | — | test_stale_oi_suppressed | PASS (1 engine) | — |
| 4 | C1 | 4 quadrants on residual price × combined OI, significant | DONE | — | test_each_quadrant | PASS (1 engine) | — |
| 4 | C2 | NEUTRAL_OR_MIXED: not significant, conflicting windows, insufficient data | DONE | — | test_mixed_windows_are_neutral, test_oi_up_with_flat_price_is_not_a_buildup | PASS (2 engine) | — |
| 4 | C3 | Percentiles vs own history, fixed % floor, min sample ⇒ LOW_SAMPLE | DONE | — | test_low_sample_history | PASS (1 engine) | — |
| 4 | C4 | Raw classification too, residual primary | DONE | — | test_index_itself_uses_raw_price | PASS (1 engine) | — |
| 4 | N | Filters OI_STALE, OI_JUMP_INVALID, ROLLOVER_WINDOW, EXPIRY_DAY, ILLIQUID_FUTURE, INDEX_DRIVEN, LOW_SAMPLE, each named | DONE | — | test_expiry_day_suppresses_every_view, test_illiquid_future, test_implausible_oi_jump, test_low_sample_history, test_move_with_beta_times_index_is_index_driven, test_rollover_combined_oi_is_continuous… | PASS (8 engine) | — |
| 4 | E | Events after N confirmations with every listed field; append-only, state changes = new rows | DONE | — | test_confirmation_evidence_and_invalidation, test_replay_gives_the_same_events_every_run | PASS (2 engine) | — |
| 4 | L | "positioning hypothesis" wording; no "institution" except the disclaimer | DONE | — | test_no_output_text_says_institution_except_the_disclaimer | PASS (1 engine) | — |
| 4 | AT1–7 | Acceptance tests | DONE | — | test_cadence_parser_takes_the_max_over_dates, test_confirmation_evidence_and_invalidation, test_each_quadrant, test_expiry_day_suppresses_every_view, test_illiquid_future, test_implausible_oi_jump, te… | PASS (17 engine) | — |
| 5 | R1 | Only complete candles; in-progress candle only where stated, labelled PROVISIONAL | DONE (no in-progress use) | — | test_gap_breaks_the_pivot_window | PASS (1 engine) | — |
| 5 | R2 | Swing confirmed after N right bars; confirmed_ts stored; not usable before (replay test) | DONE | — | test_nearest_obstacles_and_no_lookahead, test_prefix_equals_batch_filtered_and_nothing_before_confirmed_ts, test_swing_confirmed_after_right_bars_with_labels | PASS (3 engine) | — |
| 5 | R3 | Objects carry type, level, created_ts, confirmed_ts, source candles, config version | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 5 | B1 | PDH/PDL/PDC, PWH/PWL, ORH/ORL (window config), intraday confirmed swings | DONE | — | test_history_and_opening_range_levels | PASS (1 engine) | — |
| 5 | B2 | Structure per 3/5/15m: HH/HL/LH/LL, trend, BOS, CHoCH (HEURISTIC) | DONE | — | test_bos_in_trend_direction, test_choch_is_first_break_against_structure_and_heuristic, test_swing_confirmed_after_right_bars_with_labels | PASS (3 engine) | — |
| 5 | B3 | Consolidation (width in ATR over N bars); acceptance N closes or hold M min; failed = back inside within K | DONE | — | test_accepted_breakdown_by_hold_when_closes_threshold_is_higher, test_consolidation_then_accepted_breakout, test_failed_breakout_back_inside | PASS (3 engine) | — |
| 5 | B4 | Supply/demand zones: base before impulse (ATR), tests, defended/broken, reaction ATR and RVOL, invalidated on close through | DONE | — | test_demand_zone_test_defended_then_invalidated | PASS (1 engine) | — |
| 5 | B5 | Equal highs/lows; sweep = wick beyond swing/cluster + close back inside within K; quality = depth ATR, reclaim speed, rejection RVOL; reclai… | DONE | — | test_bearish_sweep_and_rejection, test_bullish_sweep_and_reclaim, test_equal_lows_cluster, test_reclaim_and_loss_of_key_levels, test_sweep_reclaimed_on_second_bar_and_not_after_k | PASS (5 engine) | — |
| 5 | B6 | VWAP: session VWAP, distance ATR, slope over N, reclaim/loss, extension flag | DONE | — | test_bullish_sweep_and_reclaim | PASS (1 engine) | — |
| 5 | B7 | LevelMap per underlying at any as_of: nearest obstacle above/below, distance in ATR | DONE | — | test_nearest_obstacles_and_no_lookahead | PASS (1 engine) | — |
| 5 | AT1 | Swing never visible before confirmed_ts in replay | DONE | — | test_prefix_equals_batch_filtered_and_nothing_before_confirmed_ts | PASS (1 engine) | — |
| 5 | AT2 | Same day twice ⇒ identical; candle-by-candle == batch | DONE | — | test_store_is_append_only_and_idempotent | PASS (1 engine) | — |
| 5 | AT3 | Fixtures: BOS, CHoCH, failed breakout, accepted breakout, bullish sweep + reclaim, bearish sweep + rejection, zone invalidation | DONE | — | test_store_is_append_only_and_idempotent | PASS (1 engine) | — |
| 5 | AT4 | LevelMap correct for a fixture | DONE | — | test_nearest_obstacles_and_no_lookahead | PASS (1 engine) | — |
| 5 | Rep | Level maps + sweeps for 3 recorded sessions; charts optional | PARTIAL (owner decision) | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 6 | 1 | age since first_observed and since confirmation | DONE | — | test_unavailable_fields_are_explicit | PASS (1 engine) | — |
| 6 | 2 | extension_atr since first detection (signed) and since confirmation | DONE | — | test_late_breakout_rr_below_min_creates_retest_plan | PASS (1 engine) | — |
| 6 | 3 | obstacle_distance_atr from LevelMap, UNAVAILABLE without one | DONE | — | test_late_breakout_rr_below_min_creates_retest_plan, test_missing_level_map_is_unknown_never_timely | PASS (2 engine) | — |
| 6 | 4 | structural_stop = the setup's original level, never recomputed | DONE | — | test_structural_stop_identical_across_reevaluations | PASS (1 engine) | — |
| 6 | 5 | stop_distance_atr | DONE | — | test_late_breakout_rr_below_min_creates_retest_plan | PASS (1 engine) | — |
| 6 | 6 | current_rr gross; current_rr_net NET_UNAVAILABLE | DONE | — | test_late_breakout_rr_below_min_creates_retest_plan, test_unavailable_fields_are_explicit | PASS (2 engine) | — |
| 6 | 7 | option premium / IV change UNAVAILABLE | DONE | — | test_unavailable_fields_are_explicit | PASS (1 engine) | — |
| 6 | 8 | pre_signal_move_atr (N bars before first detection) | DONE | — | test_phase4_event_becomes_a_setup_and_its_invalidation_ends_it | PASS (1 engine) | — |
| 6 | 9 | age_vs_half_life UNAVAILABLE, rule disabled | DONE | — | test_unavailable_fields_are_explicit | PASS (1 engine) | — |
| 6 | C | TIMELY / VALID_BUT_LATE (failed rules) / EXHAUSTED / UNKNOWN; UNKNOWN never TIMELY | DONE | — | test_each_flag_individually, test_late_breakout_rr_below_min_creates_retest_plan, test_missing_level_map_is_unknown_never_timely | PASS (3 engine) | — |
| 6 | W | WAIT_FOR_RETEST: zone, invalidation, expiry, R:R if filled; RETEST ⇒ TIMELY; expiry / invalidation end it | DONE | — | test_invalidation_and_retest_expiry_end_the_setup, test_late_breakout_rr_below_min_creates_retest_plan, test_return_to_zone_is_timely_with_reason_retest | PASS (3 engine) | — |
| 6 | E | Exhaustion flags, each explained; POSSIBLE_EXHAUSTION, never "reversal" | DONE (volume profile flag skipped and noted, no volume profi… | — | test_each_flag_individually, test_no_flags_without_evidence_and_skipped_checks_are_noted | PASS (2 engine) | — |
| 6 | T | MFE/MAE at 1/3/5/10/15/30/60 min after first detection, confirmation, first executable; after-anchor data only; time to target / invalidatio… | DONE | — | test_mfe_mae_not_written_before_horizon_elapses_in_replay_time, test_unusable_bar_makes_the_horizon_unavailable | PASS (2 engine) | — |
| 6 | AT1 | Breakout, 2 ATR run, obstacle 0.5 ATR ⇒ VALID_BUT_LATE with RR_BELOW_MIN, retest plan | DONE | — | test_late_breakout_rr_below_min_creates_retest_plan | PASS (1 engine) | — |
| 6 | AT2 | Same fixture, price back in zone ⇒ TIMELY reason RETEST | DONE | — | test_return_to_zone_is_timely_with_reason_retest | PASS (1 engine) | — |
| 6 | AT3 | Missing LevelMap ⇒ UNKNOWN, never TIMELY | DONE | — | test_missing_level_map_is_unknown_never_timely | PASS (1 engine) | — |
| 6 | AT4 | Structural stop identical across re-evaluations | DONE | — | test_structural_stop_identical_across_reevaluations | PASS (1 engine) | — |
| 6 | AT5 | MFE/MAE not written before the horizon elapses in replay time | DONE | — | test_mfe_mae_not_written_before_horizon_elapses_in_replay_time | PASS (1 engine) | — |
| 6 | R | Report on recorded sessions: share per class, pre_signal_move_atr per class | DONE for the 1 recorded session (2026-11-06, partial) | — | — | NO TEST (evidence / run log only) | NO TEST |
| 7 | C1 | Reuse backtest-expert costs if correct, else build | DONE (built: backtest-expert is stale, F-COST-2/3) | — | test_round_trip_matches_hand_computation_from_verified_rates | PASS (1 engine) | — |
| 7 | C1a | Every charge a versioned config entry with effective-from + source URL in verified-facts; futures / options, buy / sell separate; no hardcod… | PARTIAL: all 7 components are entries with a fact ID and URL… | config/engine/v9.yaml | test_pure_modules_do_no_io_and_read_no_clock | PASS (1 engine) | PARTIAL |
| 7 | C1b | Unverified rate ⇒ cost estimate UNVERIFIED | DONE (also: no rate in force on the date) | — | test_unverified_rate_or_no_rate_in_force_sets_unverified | PASS (1 engine) | — |
| 7 | C2 | Slippage = half-spread + depth impact for the size; no depth ⇒ config multiple of spread, ESTIMATED | DONE | — | test_slippage_walks_depth_or_is_estimated_without_depth | PASS (1 engine) | — |
| 7 | S0 | Selector is a pure function of explicit inputs | DONE | — | test_pure_modules_do_no_io_and_read_no_clock | PASS (1 engine) | — |
| 7 | S1 | Futures: near month, next month in the rollover window | DONE | — | test_strikes_expiries_and_rollover_come_from_the_registry | PASS (1 engine) | — |
| 7 | S2 | Long call (bull) / long put (bear), ATM + 1 ITM, nearest expiry ≥ min DTE, next as alternative, strikes from the registry | DONE | — | test_strikes_expiries_and_rollover_come_from_the_registry | PASS (1 engine) | — |
| 7 | S3 | Per candidate: lot, qty, executable entry, spread %, spread % of move to T1, top / depth qty, capital, stop / targets on contract, net R:R | DONE | — | test_risk_measures_options_full_premium_futures_gap | PASS (1 engine) | — |
| 7 | S4 | Margin via Kite API if verified available, else MARGIN_ESTIMATED with a conservative config method | PARTIAL: API documented (F-MARGIN-1) but not wired (POST, ba… | — | test_exclusions_are_named, test_missing_premium_model_option_no_trade_futures_still_evaluated | PASS (2 engine) | PARTIAL |
| 7 | S5 | Option premium at stop / target labelled; no defensible estimate ⇒ NO_TRADE NO_PREMIUM_MODEL; never invent a delta | DONE | — | test_empirical_delta_recovered_and_rejected_when_not_defensible | PASS (1 engine) | — |
| 7 | S6 | Exclusions with reasons: illiquid, spread, spread vs move, data not OK, restricted, capital, expiry too close | DONE | — | test_exclusions_are_named, test_strikes_expiries_and_rollover_come_from_the_registry, test_wide_spread_option_excluded | PASS (3 engine) | — |
| 7 | S7 | Rank by net R:R × liquidity, ties by lower capital; cheap premium never a factor | DONE | — | test_ranking_is_net_rr_times_liquidity_never_cheap_premium | PASS (1 engine) | — |
| 7 | S8 | Short options not supported (explicit test) | DONE | — | test_no_short_option_candidate_is_ever_generated | PASS (1 engine) | — |
| 7 | R0 | Single entry point `risk_check(candidate, portfolio_state, config)` → APPROVED / REJECTED with reasons | DONE | engine/risk.py | test_no_short_option_candidate_is_ever_generated | PASS (1 engine) | — |
| 7 | R1 | Capital, risk per trade, daily loss, open positions, daily trades, consecutive losses + cooldown, spread, net R:R, slippage, option volume /… | DONE (event days from config only, Q-RISK-3) | — | test_capital_above_limit_rejected, test_daily_loss_breach_rejects_every_candidate_for_the_day, test_every_check_is_named | PASS (3 engine) | — |
| 7 | R2 | Long options: planned_risk sizes; full_premium_at_risk reported; capital check uses full premium | DONE | — | test_capital_above_limit_rejected, test_risk_measures_options_full_premium_futures_gap | PASS (2 engine) | — |
| 7 | R3 | Futures: planned_risk and gap risk (ATR multiple beyond the stop), both reported | DONE | — | test_risk_measures_options_full_premium_futures_gap | PASS (1 engine) | — |
| 7 | R4 | Every check returns a named reason; config version recorded | DONE | — | test_every_check_is_named | PASS (1 engine) | — |
| 7 | R5 | No recommendation without risk_check APPROVED (token only risk_check can create) | DONE (paper trades do not exist yet, Phase 11) | — | test_recommendation_requires_an_approval_token_from_risk_check | PASS (1 engine) | — |
| 7 | AT1 | Contract needing more capital than permitted ⇒ REJECTED | DONE | — | test_capital_above_limit_rejected | PASS (1 engine) | — |
| 7 | AT2 | Wide-spread option ⇒ excluded SPREAD_TOO_WIDE | DONE | — | test_wide_spread_option_excluded | PASS (1 engine) | — |
| 7 | AT3 | Daily loss limit breached ⇒ every later candidate REJECTED for the day | DONE (incl. after P&L recovers) | — | test_daily_loss_breach_rejects_every_candidate_for_the_day | PASS (1 engine) | — |
| 7 | AT4 | Missing premium model ⇒ option NO_TRADE, futures still evaluated | DONE | — | test_missing_premium_model_option_no_trade_futures_still_evaluated | PASS (1 engine) | — |
| 7 | AT5 | Cost model with an unverified rate ⇒ UNVERIFIED flag | DONE | — | test_unverified_rate_or_no_rate_in_force_sets_unverified | PASS (1 engine) | — |
| 7 | AT6 | Recommendation without approval token raises | DONE | — | test_recommendation_requires_an_approval_token_from_risk_check | PASS (1 engine) | — |
| 7 | AT7 | No short-option candidate ever generated | DONE | — | test_no_short_option_candidate_is_ever_generated | PASS (1 engine) | — |
| 7 | RPT | 10 recorded setups: full candidate table with exclusions and risk decision | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 8 | F-A | Fresh long buildup breakout (resistance, LONG_BUILDUP residual, RVOL elevated, above VWAP, acceptance) | DONE | — | test_A_fresh_long_buildup_breakout | PASS (1 engine) | — |
| 8 | F-B | Short buildup breakdown (symmetric) | DONE | — | test_B_fresh_short_buildup_breakdown | PASS (1 engine) | — |
| 8 | F-C | Short-covering momentum; exhaustion check always run; "covering, not confirmed new buying" | DONE | — | test_C_short_covering_momentum_is_labelled_and_exhaustion_checked | PASS (1 engine) | — |
| 8 | F-D | Long-unwinding continuation, persistent volume | DONE | — | test_D_long_unwinding_continuation_needs_persistent_volume | PASS (1 engine) | — |
| 8 | F-E/F | Liquidity-sweep reversals: sweep + reclaim + rejection RVOL + structure confirmation | DONE | — | test_E_F_liquidity_sweep_reversals | PASS (1 engine) | — |
| 8 | F-G | Exhaustion = warning on other setups + standalone observation, never an entry | DONE | — | test_G_exhaustion_is_an_observation_and_a_warning_never_an_entry | PASS (1 engine) | — |
| 8 | OPT | Option-chain evidence slot UNAVAILABLE | DONE | — | test_missing_option_data_scores_zero_listed_missing_and_max_available_reported | PASS (1 engine) | — |
| 8 | LBL | 12 state labels incl. SUSPECTED_ACCUMULATION / _DISTRIBUTION, NO_TRADE, UNCERTAIN | DONE (list assumed, Q-8-2) | — | test_all_twelve_state_labels_exist_and_are_reachable, test_suspected_accumulation_and_distribution | PASS (2 engine) | — |
| 8 | GATE | 10 mandatory gates before scoring; failure ⇒ REJECTED with reasons, setup + score still stored | DONE | — | test_high_score_with_a_failed_gate_is_rejected_never_entry_eligible, test_late_waits_for_retest_unknown_is_rejected, test_stale_critical_data_cannot_reach_entry_eligible | PASS (3 engine) | — |
| 8 | GATE-T | TIMELY required; VALID_BUT_LATE ⇒ WAIT_FOR_RETEST; UNKNOWN ⇒ REJECTED | DONE | — | test_driver_retest_then_eligible_then_expired, test_late_waits_for_retest_unknown_is_rejected | PASS (2 engine) | — |
| 8 | SC1 | Config weights, versioned; default 25/20/20/15/10/10 | DONE | — | test_v10_loads_missing_key_and_bad_weights_fail | PASS (1 engine) | — |
| 8 | SC2 | Each factor: points + explanation + inputs; UNAVAILABLE ⇒ 0 and listed; max achievable reported | DONE | — | test_missing_option_data_scores_zero_listed_missing_and_max_available_reported | PASS (1 engine) | — |
| 8 | SC3 | Separate bullish, bearish, reversal, continuation scores | DONE | — | test_scores_are_separate_and_counter_direction_scores_lower | PASS (1 engine) | — |
| 8 | SC4 | Broad market: NIFTY trend/structure, breadth (share above VWAP), index futures positioning | DONE (on real data, trend and index positioning were UNAVAIL… | — | — | NO TEST (evidence / run log only) | NO TEST |
| 8 | SC5 | Bands 80+/60–79/<60 labelled RESEARCH_PRIORITY, "not a probability" | DONE | — | test_scores_are_separate_and_counter_direction_scores_lower | PASS (1 engine) | — |
| 8 | REC | Recommendation object with the spec's fields | DONE | — | test_recommendation_has_every_field_and_prices_from_quotes | PASS (1 engine) | — |
| 8 | REC-P | Prices only from actual quotes; no defensible stop or R:R ⇒ NO_TRADE | DONE | — | test_no_defensible_stop_is_no_trade, test_recommendation_has_every_field_and_prices_from_quotes | PASS (2 engine) | — |
| 8 | LC1 | State machine with the 13 states; only allowed transitions; each an appended row (ts + cause) | DONE | — | test_illegal_transitions_raise_and_rows_are_appended | PASS (1 engine) | — |
| 8 | LC2 | Illegal transitions raise | DONE | — | test_illegal_transitions_raise_and_rows_are_appended | PASS (1 engine) | — |
| 8 | TIER | ENTRY_ELIGIBLE ⇒ promote the underlying + candidate contracts to Tier B via the Phase 3 API | DONE (not wired into the live recorder, Q-8-4) | — | test_entry_eligible_promotes_underlying_and_candidates_to_tier_b | PASS (1 engine) | — |
| 8 | AT1 | High score with a failed gate ⇒ REJECTED, never ENTRY_ELIGIBLE | DONE | — | test_high_score_with_a_failed_gate_is_rejected_never_entry_eligible | PASS (1 engine) | — |
| 8 | AT2 | Stale critical data ⇒ cannot reach ENTRY_ELIGIBLE | DONE | — | test_stale_critical_data_cannot_reach_entry_eligible | PASS (1 engine) | — |
| 8 | AT3 | Illegal lifecycle transitions raise | DONE | — | test_illegal_transitions_raise_and_rows_are_appended | PASS (1 engine) | — |
| 8 | AT4 | Each family: positive and negative fixtures; negatives produce no setup | DONE | — | test_A_fresh_long_buildup_breakout, test_B_fresh_short_buildup_breakdown, test_C_short_covering_momentum_is_labelled_and_exhaustion_checked, test_D_long_unwinding_continuation_needs_persistent_volume,… | PASS (6 engine) | — |
| 8 | AT5 | Missing option data ⇒ options factor 0, listed missing, max-available reported | DONE | — | test_missing_option_data_scores_zero_listed_missing_and_max_available_reported | PASS (1 engine) | — |
| 8 | AT6 | Replaying stored inputs regenerates an identical object | DONE | — | test_replaying_stored_inputs_regenerates_an_identical_object | PASS (1 engine) | — |
| 8 | RPT | Per-day counts by family and status; top 10 rejected-for-reason examples | DONE (1 recorded day) | — | — | NO TEST (evidence / run log only) | NO TEST |
| 9 | B1 | Paper fills from executable quotes at decision time: buy at ask, sell at bid, + slippage model | DONE | — | test_buy_at_ask_sell_at_bid_with_quote_snapshot_and_label, test_touch_only_quote_fills_touch_qty_with_estimated_slippage | PASS (2 engine) | — |
| 9 | B1 | Partial fills when depth < quantity | DONE | — | test_partial_fill_when_visible_depth_is_short | PASS (1 engine) | — |
| 9 | B1 | No fill if no quote | DONE | — | test_no_quote_no_fill | PASS (1 engine) | — |
| 9 | B1 | Every fill stores the quote snapshot; labelled SIMULATED | DONE | — | test_no_quote_no_fill | PASS (1 engine) | — |
| 9 | B2 | Actual-trade journal: taken with fill price / qty / time, or skipped with reason; labelled ACTUAL | DONE (API + CLI; UI is Phase 10, Q-9-12) | — | test_ledgers_are_separate_tables_and_queryable_separately | PASS (1 engine) | — |
| 9 | B2 | Two ledgers in separate tables; analytics never sum them | DONE | — | test_daily_loss_is_per_ledger_never_summed, test_ledgers_are_separate_tables_and_queryable_separately, test_no_query_joins_the_ledgers_or_reads_shared_tables_without_a_ledger_filter | PASS (3 engine) | — |
| 9 | B3 | Every tick: hard protective stop (contract and underlying) ⇒ EXIT_REQUIRED immediately with the triggering observation | DONE (option contract stop = warning, Q-9-15) | — | test_futures_contract_stop_is_a_hard_stop, test_short_trade_stop_is_above, test_stop_breach_exits_on_the_breaching_tick_not_at_the_review, test_tick_equal_to_stop_exits | PASS (4 engine) | — |
| 9 | B3 | Intraday square-off cutoff | DONE (15:10, Q-9-3) | — | test_squareoff_cutoff | PASS (1 engine) | — |
| 9 | B3 | Max loss ⇒ EXIT_REQUIRED | DONE (Q-9-4) | — | test_daily_loss_limit_on_the_ledger, test_max_loss_per_trade_on_net_pnl | PASS (2 engine) | — |
| 9 | B3 | Every 5 min (config) and on fresh OI change: thesis re-evaluation (positioning, VWAP, structure, spread/liquidity, opposite signals, exhaust… | DONE (positioning is UNAVAILABLE on real data: Q-4-6 / Q-6-5… | — | test_fresh_oi_change_triggers_a_review, test_positioning_family_needs_positioning, test_review_rules | PASS (3 engine) | — |
| 9 | B3 | Outputs HOLD / TIGHTEN_STOP (breakeven after +1R, trail behind a confirmed swing) / PARTIAL_EXIT_CANDIDATE (T1) / EXIT_REQUIRED (hard, time,… | DONE | — | test_review_rules, test_tighten_breakeven_trail_and_t1 | PASS (2 engine) | — |
| 9 | B3 | Pullback vs invalidation: premium decline without structural invalidation ⇒ not EXIT_REQUIRED | DONE | — | test_brief_premium_dip_with_intact_structure_holds | PASS (1 engine) | — |
| 9 | B3 | Gross and estimated net P&L live | DONE | — | test_max_loss_per_trade_on_net_pnl | PASS (1 engine) | — |
| 9 | B4 | Every decision change emits an alert with the exact triggering observations (values + timestamps) and rule id | DONE | — | test_alerts_only_on_change_with_observations_and_rule | PASS (1 engine) | — |
| 9 | B4 | In-app delivery; interface for later channels | DONE | — | test_alert_sink_interface, test_run_results_are_stored_per_ledger | PASS (2 engine) | — |
| 9 | B5 | Feedback: taken/skipped, actual entry/exit, slippage, execution quality, behaved yes/no/partly, notes; stored only | DONE (API + CLI) | — | test_feedback_is_stored_and_changes_no_config | PASS (1 engine) | — |
| 9 | B6 | Data STALE ⇒ DATA_UNAVAILABLE, the alert says so, nothing inferred | DONE | — | test_disconnect_with_a_fresh_book_still_shows_no_pnl, test_feed_disconnect_is_data_unavailable_without_pnl, test_silent_feed_goes_stale | PASS (3 engine) | — |
| 9 | AT1 | Stop breach fixture ⇒ EXIT_REQUIRED on the breaching tick, not at the next 5-minute review | DONE | — | test_stop_breach_exits_on_the_breaching_tick_not_at_the_review | PASS (1 engine) | — |
| 9 | AT2 | Brief premium dip with intact structure ⇒ HOLD | DONE | — | test_brief_premium_dip_with_intact_structure_holds | PASS (1 engine) | — |
| 9 | AT3 | Paper fill with no quote ⇒ no fill | DONE | — | test_no_quote_no_fill | PASS (1 engine) | — |
| 9 | AT4 | Feed disconnect ⇒ DATA_UNAVAILABLE, no fabricated P&L | DONE | — | test_disconnect_with_a_fresh_book_still_shows_no_pnl, test_feed_disconnect_is_data_unavailable_without_pnl | PASS (2 engine) | — |
| 9 | AT5 | Ledgers queryable separately; a test asserts no analytics query joins them without a type filter | DONE | — | test_ledgers_are_separate_tables_and_queryable_separately, test_no_query_joins_the_ledgers_or_reads_shared_tables_without_a_ledger_filter | PASS (2 engine) | — |
| 9 | AT6 | Feedback submission does not change any config | DONE | — | test_feedback_is_stored_and_changes_no_config | PASS (1 engine) | — |
| 9 | RPT | Paper trading over all recorded sessions; trade list with fills, decisions and alerts for 5 trades | PARTIAL | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 10 | INT | New tab inside the existing app; existing app inspected | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | STK | React + TS + Tailwind at the app's versions; chart library verified; FastAPI REST + SSE | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | SEC | No Kite credentials to the frontend; local authenticated user only | DONE | — | test_loopback_same_origin_only, test_no_secret_is_read_or_returned, test_router_requires_the_check_on_every_route | PASS (3 engine) | — |
| 10 | R1 | No trading logic in the frontend; UNAVAILABLE ⇒ "—" + reason; no mock numbers | DONE (unit formatting only, Q-10-13) | — | — | PASS (0 engine + vitest) | — |
| 10 | R2 | Every panel shows data age; stale panels visibly marked | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | R3 | SIMULATED and ACTUAL visually distinct everywhere | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | R4 | "Positioning hypothesis" language | DONE | — | test_no_output_text_says_institution_except_the_disclaimer | PASS (1 engine) | — |
| 10 | D1 | Global CSS / Tailwind config / theme / fonts / shared components untouched | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | D2 | One scoped root, no global selectors | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | D3 | Separate Tailwind config, prefix, important scoped, preflight off | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | D4 | Portals inside the root | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | D5 | Fonts only for the module | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | D6 | Tokens in one file + scoped CSS variables, light and dark, semantic tokens | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | D7 | Distinct look; tabular numerals; colour never the only signal | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | D8 | Radar first, screenshot next to an existing tab | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | D9 | `docs/design-system.md` with an app-wide adoption guide | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | A | Market overview | DONE (trend, positioning, VIX UNAVAILABLE on this data) | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | B | Opportunity Radar: sortable, filterable, all columns, score with available max, timeliness, rejected behind a filter with reasons | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | C | Positioning map: quadrants, suspected acc./dist., history scrubber, residual vs raw | DONE (all cells not evaluated on this data) | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | D | Option chain placeholder, no fake data | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | E | Signal detail: chart with VWAP / levels / zones / sweeps / structure marks; OI history with ages; confirmation timeline; score breakdown; op… | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | F | Active trades: entry, qty/lots, current premium, P&L gross/net, stop, targets, decision, thesis, alerts | DONE (0 trades in the replay; rendering proven on fixtures) | — | test_trades_and_performance_are_per_ledger | PASS (1 engine + vitest) | — |
| 10 | G | Performance: daily/cumulative, win rate, expectancy, PF, drawdown, slippage, charges, breakdowns by strategy / time / instrument / score ban… | DONE (regime UNAVAILABLE: no classifier; not as-of, Q-10-15) | — | test_metrics_for_one_ledger, test_never_mixes_ledgers | PASS (2 engine) | — |
| 10 | H | Feedback forms (Phase 9) | DONE (POST, Q-10-14) | — | test_feedback_post_stores_and_changes_no_config | PASS (1 engine) | — |
| 10 | SYS | Feed status, ticks/sec, stale instruments, gaps, allocator usage | DONE (UNAVAILABLE in replay of 2026-11-06: look-ahead, Q-10-… | — | test_health_from_status_files | PASS (1 engine) | — |
| 10 | AT1 | Component test: UNAVAILABLE ⇒ "—" with reason | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | AT2 | Stale indicator when backend marks STALE | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | AT3 | Simulated and actual never in the same total | DONE | — | test_never_mixes_ledgers | PASS (1 engine) | — |
| 10 | AT4 | Visual regression of every existing tab (pixel-identical or differences explained) | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | AT5 | Grep test: no global selectors / unprefixed classes; no edits to global style files | DONE | — | — | PASS (0 engine + vitest) | — |
| 10 | AT6 | Strict type-check; no secrets in the bundle | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 10 | RPT | Screenshots of each panel against a replayed session | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 11 | B1 | Option subscription planner, which covers:<ul><li>ATM ± N strikes</li><li>strikes near LevelMap levels</li><li>top-OI and unusual-OI-change … | DONE. Live from the first session after the plist reinstall … | — | test_allocator_never_exceeds_limits_with_option_tier, test_planner_respects_cap_priority_and_reasons, test_tier_c_planner_promotes_within_the_cap_and_writes_its_plan | PASS (3 engine) | — |
| 11 | B2 | Chain metrics, which cover:<ul><li>CE/PE OI, OI change with OI ages</li><li>volume, premium change, spread, depth</li><li>PCR over the strik… | DONE | — | test_chain_snapshot_metrics_hedge_and_missing_oi, test_snapshots_context_and_iv_history_from_recorded_rows | PASS (2 engine) | — |
| 11 | B3a | IV from mid via Black-76; trading-calendar T; rate from config with its source; dividends documented | DONE | — | test_iv_recovered_from_a_fresh_narrow_book_mid, test_trading_years_and_rate | PASS (2 engine) | — |
| 11 | B3b | Compute only with bid and ask, spread below the threshold, mid inside the bounds, and a converging solver; otherwise UNAVAILABLE; never from… | DONE | — | test_iv_unavailable_reasons, test_wide_spread_option_iv_unavailable_not_computed_from_ltp | PASS (2 engine) | — |
| 11 | B3c | Unit tests against textbook values (cited) | DONE | — | test_greeks_match_finite_differences, test_iv_solver_matches_reference_values_within_tolerance | PASS (2 engine) | — |
| 11 | B3d | IV percentile vs the underlying's own recorded history; UNAVAILABLE until enough history | DONE (history store starts empty) | — | test_iv_percentile_needs_history_and_ignores_the_same_day | PASS (1 engine) | — |
| 11 | B4 | Positioning hypotheses from all four inputs; never from OI and premium alone; concentration shown as a hypothesis | DONE | — | test_each_label_needs_all_four_inputs, test_rising_call_oi_without_corroboration_is_uncertain_not_call_writing | PASS (2 engine) | — |
| 11 | B5 | Options factor (supportive / neutral / contradicting) replaces the UNAVAILABLE slot | DONE | — | test_options_factor_scored_from_the_chain_and_opportunity_age_option_fields_filled, test_options_factor_states | PASS (2 engine) | — |
| 11 | B6a | Results / board-meeting calendar from an official NSE source (URL verified); option buying within N days ⇒ REJECTED EVENT_IV_RISK; futures g… | DONE | — | test_event_window_and_calendar_store, test_option_within_results_window_rejected_event_iv_risk_futures_warned | PASS (2 engine) | — |
| 11 | B6b | Gate on IV percentile above a maximum for long options | DONE | — | test_iv_percentile_gate_for_long_options | PASS (1 engine) | — |
| 11 | B6c | Calendar unavailable ⇒ EVENT_UNVERIFIED, option candidates rejected | DONE | — | test_missing_or_stale_calendar_rejects_every_option_event_unverified | PASS (1 engine) | — |
| 11 | B7 | Selector V2: nearby OTM alternative; delta from computed Greeks; premium at stop/target by delta-gamma (method labelled); theta cost over th… | DONE | — | test_otm_alternative_greeks_premium_theta_and_expiry_sensitivity, test_strikes_expiries_and_rollover_come_from_the_registry | PASS (2 engine) | — |
| 11 | B8 | Dashboard panel D: OI distribution, OI change, premium change, IV, concentrations, liquidity, hypotheses, selected-contract comparison | DONE (built and unit-tested; not deployed, owner rebuilds `d… | — | test_chain_panel_reads_options_store_with_no_look_ahead | PASS (1 engine + vitest) | — |
| 11 | AT1 | Wide-spread option ⇒ IV UNAVAILABLE, not computed from LTP | DONE | — | test_wide_spread_option_iv_unavailable_not_computed_from_ltp | PASS (1 engine) | — |
| 11 | AT2 | IV solver matches reference values within tolerance | DONE | — | test_iv_solver_matches_reference_values_within_tolerance | PASS (1 engine) | — |
| 11 | AT3 | Rising call OI with no premium / IV / underlying corroboration ⇒ UNCERTAIN, not call writing | DONE | — | test_rising_call_oi_without_corroboration_is_uncertain_not_call_writing | PASS (1 engine) | — |
| 11 | AT4 | Option within the results window ⇒ REJECTED EVENT_IV_RISK | DONE | — | test_option_within_results_window_rejected_event_iv_risk_futures_warned | PASS (1 engine) | — |
| 11 | AT5 | Missing calendar ⇒ option candidates rejected EVENT_UNVERIFIED | DONE | — | test_missing_or_stale_calendar_rejects_every_option_event_unverified | PASS (1 engine) | — |
| 11 | AT6 | Allocator never exceeds limits with the option tier added | DONE | — | test_allocator_never_exceeds_limits_with_option_tier | PASS (1 engine) | — |
| 11 | R | Report: chain snapshots for 3 underlyings with hypotheses, IV coverage %, rejected-for-event counts | PARTIAL: real data exists only as an after-hours snapshot (e… | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 12 | Data-1 | Intraday OI, depth and option logic are tested only on recorded sessions | DONE: only the RECORDED path can reach them; HISTORICAL list… | — | test_event_rows_three_anchors_and_not_representable_families | PASS (1 engine) | — |
| 12 | Data-2 | State the historical granularity; every table names its dataset | DONE: §4.1; every table header | — | test_every_table_is_titled_with_its_dataset_stage_and_good_sessions | PASS (1 engine) | — |
| 12 | Data-3 | Universe per date from stored snapshots; survivorship warning | PARTIAL:<ul><li>RECORDED uses each day's own stored master a… | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 12 | Eng-1 | Phase 1 replay engine; the same pure strategy, selector, risk and paper-broker code as live | DONE:<ul><li>`ledger.run_day` is unchanged</li><li>compacted… | — | test_buffer_rebuilt_from_parquet_equals_the_original | PASS (1 engine) | — |
| 12 | Eng-2 | Fills: executable side, slippage, partial fills; gap-through-stop at the first price beyond the stop | DONE:<ul><li>Phase 9 `paper_fill` walks the book; partial fi… | — | test_gap_through_stop_exits_at_the_first_price_beyond_not_at_the_stop, test_partial_fill_when_visible_depth_is_short, test_stop_gap_paper_exit_fills_beyond_the_stop_and_costs_are_date_effective | PASS (3 engine) | — |
| 12 | Eng-3 | Full Phase 7 costs at the rates in force on each date | DONE. A date with no verified rate is flagged `cost_unverifi… | — | test_stop_gap_paper_exit_fills_beyond_the_stop_and_costs_are_date_effective, test_unverified_rate_or_no_rate_in_force_sets_unverified | PASS (2 engine) | — |
| 12 | Eng-4 | Simultaneous signals resolved by live ranking and risk | DONE as built live (Q-12-14) | — | test_simultaneous_signals_resolved_by_the_live_risk_rules | PASS (1 engine) | — |
| 12 | St-1 | Event study: MFE/MAE at 1/3/5/10/15/30/60 min from detection, confirmation and first executable; pre-signal move share; time to target / inv… | DONE:<ul><li>HISTORICAL: real tables H2/H3, where 1 and 3 mi… | — | test_excursions_below_resolution_are_unavailable, test_segments_come_from_each_events_measured_exit | PASS (2 engine) | — |
| 12 | St-2 | Edge half-life per family → a versioned file Phase 6 reads to enable age_vs_half_life | DONE:<ul><li>`config/engine/half_life/v1.json` exists</li><l… | — | test_half_life_file_is_versioned_and_partial_runs_carry_other_datasets, test_half_life_measured_and_conservative_statuses, test_phase6_reads_only_recorded_measured_tentative_entries, test_rule_disable… | PASS (4 engine) | — |
| 12 | St-3 | TIMELY vs VALID_BUT_LATE vs RETEST expectancy | DONE (HISTORICAL table H5); RECORDED is waiting for sessions | — | — | NO TEST (evidence / run log only) | NO TEST |
| 12 | St-4 | OI publication delay: OI at decision time vs OI as eventually reported (diagnostic) | PARTIAL:<ul><li>The decision-level diagnostic is built and w… | — | test_oi_publication_delay_decision_uses_only_received_oi | PASS (1 engine) | PARTIAL |
| 12 | St-5 | Segments: regime (NIFTY structure), VIX bucket, time of day, expiry proximity, instrument, score band | PARTIAL:<ul><li>HISTORICAL: regime, time of day, timeframe</… | — | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 12 | Val-1 | GOOD sessions (coverage ≥ 95%, no long gap in the first/last 30 min); good vs excluded with reasons; stage chosen automatically; every table… | DONE | — | test_full_session_is_good, test_low_coverage_and_edge_gap_exclude_and_say_why, test_real_2026_11_06_control_rows_shape_is_excluded, test_stages_from_good_session_count, test_stall_ends_a_connection_an… | PASS (5 engine) | — |
| 12 | Val-2 | Development / validation / final holdout. The holdout (last 30 of the first 125 good sessions) is written to config before analysis, never r… | DONE | — | test_holdout_is_the_last_30_of_the_first_125_good_sessions, test_holdout_read_only_at_final_once_and_logged, test_holdout_rule_is_in_versioned_config | PASS (3 engine) | — |
| 12 | Val-3 | 5-year historical candle backtest runs now, in its own section labelled HISTORICAL_CANDLES | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 12 | Val-4 | Walk-forward: tune on rolling train windows, evaluate on the following window only | DONE:<ul><li>HISTORICAL: 18 windows (table H7)</li><li>RECOR… | — | test_walk_forward_chooses_on_train_and_scores_on_test_only | PASS (1 engine) | — |
| 12 | Val-5 | Per family: trades, precision, win rate, average win/loss, expectancy in R and rupees after costs, profit factor, max drawdown, slippage sha… | DONE for RECORDED trades (INR and net R tables, slippage sha… | — | test_costs_and_slippage_share, test_figures_and_day_clustered_bootstrap_are_deterministic | PASS (2 engine) | — |
| 12 | Val-6 | Every table titled SIMULATED / HYPOTHETICAL | DONE: 21 headers in the evidence report | — | test_every_table_is_titled_with_its_dataset_stage_and_good_sessions | PASS (1 engine) | — |
| 12 | Sc | Required scenario tests (15) | DONE (§5) | — | test_costs_and_slippage_share, test_daily_loss_limit_blocks_the_next_signal_in_the_backtest_ledger, test_data_interruption_excludes_the_session_and_breaks_the_path, test_excursions_below_resolution_ar… | PASS (21 engine) | — |
| 12 | LA | Look-ahead guard: a future sentinel observation must change nothing | DONE, and shown to be sensitive | — | test_look_ahead_guard_sentinel_future_bar_changes_nothing_known_before_it | PASS (1 engine) | — |
| 12 | Rep | This report: tables, the half-life file, a plain-language verdict per family | DONE | — | — | NO TEST (evidence / run log only) | NO TEST |
| 13 | 1 | Session profile per underlying: POC, VAH, VAL (value-area % in config), HVNs, LVNs | DONE | — | test_bin_is_bps_of_the_first_price_rounded_up_to_the_tick, test_hvn_and_lvn, test_poc_and_value_area_match_the_hand_computation, test_poc_tie_goes_to_the_bin_nearest_the_middle_then_the_lower | PASS (4 engine) | — |
| 13 | 1a | Tick-based where recorded ticks exist, labelled TICK_BASED | DONE | — | test_minute_tick_volume_equals_its_candle_volume_or_the_minute_is_not_used, test_no_look_ahead, test_partial_or_missing_minutes_make_the_profile_unavailable, test_tick_profile_matches_the_hand_compute… | PASS (4 engine) | — |
| 13 | 1b | Candle-based fallback labelled APPROXIMATE, never presented as trade-at-price | DONE (data, detections, score details) | — | test_candle_based_profile_is_labelled_approximate_in_data, test_candle_volume_is_spread_evenly_over_the_range, test_no_ticks_for_the_token_falls_back_to_approximate, test_profile_part_value_and_label | PASS (4 engine) | — |
| 13 | 1c | APPROXIMATE label in the UI | PARTIAL | SignalDetail.tsx | — | NO TEST (evidence / run log only) | PARTIAL, NO TEST |
| 13 | 2 | Profile levels in the LevelMap | DONE | — | test_level_map_uses_only_the_latest_profile_snapshot | PASS (1 engine) | — |
| 13 | 2a | Exhaustion flag "rejection at high-volume zone" | DONE | — | test_configs_before_v17_keep_the_old_note, test_hvz_rejection_detection_and_exhaustion_flag | PASS (2 engine) | — |
| 13 | 3 | Depth behaviour (Tier B only): spread, imbalance, replenishment, withdrawals, possible absorption, labelled "observed in 5-level depth" | DONE (fixtures) / no real data | — | test_imbalance_from_visible_pending_quantity, test_no_tier_b_snapshots_is_unavailable, test_replenishment_and_possible_absorption_at_the_offer, test_withdrawal_needs_no_trade_at_the_price_and_less_vol… | PASS (4 engine) | — |
| 13 | 3a | Spoofing / iceberg / aggressor never labelled confirmed | DONE | — | test_no_depth_field_claims_confirmed_spoofing_iceberg_or_aggressor | PASS (1 engine) | — |
| 13 | 4 | Fill the profile+depth score factor | DONE (weight 0) | — | test_profile_part_value_and_label, test_v17_profile_depth_parts_carry_weight_zero_and_scores_do_not_change | PASS (2 engine) | — |
| 13 | 5 | Re-run the Phase 12 study; weights stay 0 without out-of-sample value | DONE | — | test_below_final_or_small_samples_are_insufficient_and_weights_stay_zero, test_final_with_separated_cis_adds_value_else_no_evidence, test_historical_dataset_lists_the_profile_as_not_representable | PASS (3 engine) | — |
| 13 | — | Acceptance: fixture profile matches hand-computed POC/VA | DONE | — | test_poc_and_value_area_match_the_hand_computation, test_tick_profile_matches_the_hand_computed_poc_and_value_area | PASS (2 engine) | — |
| 13 | — | Acceptance: candle-based output carries APPROXIMATE | DONE | — | test_candle_based_profile_is_labelled_approximate_in_data | PASS (1 engine) | — |
| 13 | — | Acceptance: no depth field labelled confirmed spoofing/iceberg (string test) | DONE | — | test_no_depth_field_claims_confirmed_spoofing_iceberg_or_aggressor | PASS (1 engine) | — |
| 13 | — | Pure core, time as input | DONE | — | test_profile_core_reads_no_clock | PASS (1 engine) | — |
