# Phase 6 report: opportunity age, timing and exhaustion

Date: built 2026-11-06 (IST, evening). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, phase-0…5 reports. Phase 5 is still awaiting your review.

## 0. Owner decisions taken during this phase (2026-11-06)

| Question | Decision |
|---|---|
| Which events are "candidate setups" | **All four**: Phase 5 accepted breakouts/breakdowns, sweeps, defended zones; Phase 4 CONFIRMED positioning events |
| Structural stop (Phase 5 detections carry none) | **Far side**: breakout = opposite consolidation edge; sweep = wick extreme; zone = far zone edge; positioning = Phase 4 PRICE_THROUGH_FIRST_OBSERVED level. Fixed at creation |
| Thresholds (no verified source) | **As proposed**, `config/engine/v7.yaml` → `opportunity` (v7 = v6 + `opportunity`; global default stays v4) |
| "First executable time" and "target" | **First TIMELY evaluation** (no TIMELY by the close ⇒ UNAVAILABLE); target = obstacle in the trade direction at confirmation, fixed |

Interpretations chosen (rule 16: the more conservative reading), flagged:
- **Evaluation points.** A setup is evaluated at every 1m close from its confirmation until 15:40, invalidation or retest expiry. Expiry of the retest plan ends the setup, not just the plan.
- **Invalidation.** A 1m close at or through the structural stop (equality counts, Q-OPP-2). Phase 4 setups also end at their own INVALIDATED row.
- **Precedence.** UNKNOWN > EXHAUSTED > TIMELY / VALID_BUT_LATE. Exhaustion overrides passing rules.
- **No obstacle counts as missing.** No obstacle in the trade direction (price above every known level) ⇒ R:R undefined ⇒ UNKNOWN, as with a missing LevelMap.
- **Retest.** The zone is entered by a 1m **close** inside it, not by a wick. TIMELY with reason RETEST needs every rule to pass at that close. Only one plan exists at a time; TIMELY clears it, and a later LATE makes a new one.
- **Retest zone.** It sits at the nearer of the broken level and the setup-timeframe VWAP, among those strictly between the stop and price. If neither qualifies, a plan with no zone is recorded (NO_VALID_LEVEL) and the setup can only become TIMELY by the rules.
- **Pre-signal move.** pre_signal_move_atr = (price at first detection − the 1m close 5 setup bars earlier) / ATR at first detection, signed. UNAVAILABLE if that 1m bar is unusable.
- **Exhaustion: OI progress.** Fut price % change ÷ combined OI % change in each of 3 consecutive 15m windows. It flags only when OI expanded in all three windows and progress fell strictly each time.
- **Exhaustion: RVOL.** rvol_15m falls strictly over the three window ends while the price (trade direction) rises strictly.
- **Exhaustion: repeated failure.** At least 3 Phase 5 SWING / SWEEP / BREAKOUT_FAILED detections on the setup's own timeframe (avoids counting one pivot three times), within 0.1 ATR of the current obstacle.
- **Exhaustion: high-volume zone.** Always skipped with a note: there is no volume profile yet.
- **Time to target / invalidation.** Measured to the close of the 1m bar that hits (intrabar timing unknown). An unusable bar before any hit ⇒ UNAVAILABLE. Computed for each anchor; for the first-detection anchor, the target fixed at confirmation is used.
- **Background job.** The recorder is a pure function of `as_of`. The CLI runs it once after the close with as_of = 15:40. Nothing is scheduled (Q-OPP-6).

## 1. Files

| File | Purpose |
|---|---|
| `engine/opportunity.py` | `Setup`, `Snapshot`, `RetestPlan`, `Evaluation`; setup adapters (Phase 5 / Phase 4), `pre_signal`, `exhaustion`, `opportunity_age`, `retest_plan`, `track`, `anchors`, `timing_rows`, `Context`, `run_setups`, store, report, CLI |
| `config/engine/v7.yaml` | v6 unchanged + `opportunity` (13 required keys; the loader fails on a missing one) |
| `tests/engine_tests/test_opportunity.py` | 13 tests (scripted snapshots; Phase 5 random-day fixture reused from `test_structure`) |
| docs | architecture §13, open-questions (Q-OPP-1..7), this report, `phase-6-evidence/` |

No earlier interface or module changed. Outside the engine paths, `git diff --stat defa774` shows only Phase 1's `.gitignore`.

## 2. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| 1 | age since first_observed and since confirmation | DONE | `test_unavailable_fields_are_explicit` (360 s / 0 s) |
| 2 | extension_atr since first detection (signed) and since confirmation | DONE | `test_late_breakout_…` (2.0 ATR) |
| 3 | obstacle_distance_atr from LevelMap, UNAVAILABLE without one | DONE | `test_late_breakout_…` (0.5), `test_missing_level_map_is_unknown_never_timely` |
| 4 | structural_stop = the setup's original level, never recomputed | DONE | `test_structural_stop_identical_across_reevaluations` (60 re-evaluations + setups rebuilt at every 3m prefix of a random day equal the full-day objects); real data: 0 of 961 setups with a changed stop (`real-data-checks-2026-11-06.txt`) |
| 5 | stop_distance_atr | DONE | `test_late_breakout_…` (3.0) |
| 6 | current_rr gross; current_rr_net NET_UNAVAILABLE | DONE | `test_late_breakout_…`, `test_unavailable_fields_are_explicit` |
| 7 | option premium / IV change UNAVAILABLE | DONE | `test_unavailable_fields_are_explicit` |
| 8 | pre_signal_move_atr (N bars before first detection) | DONE | `Setup.pre_signal_move_atr`; positioning fixture UNAVAILABLE path; real distribution §5 |
| 9 | age_vs_half_life UNAVAILABLE, rule disabled | DONE | `test_unavailable_fields_are_explicit`; no rule reads it |
| C | TIMELY / VALID_BUT_LATE (failed rules) / EXHAUSTED / UNKNOWN; UNKNOWN never TIMELY | DONE | `test_late_breakout_…` (RR_BELOW_MIN, EXTENDED, STOP_TOO_WIDE), `test_missing_level_map_…`, `test_each_flag_individually` |
| W | WAIT_FOR_RETEST: zone, invalidation, expiry, R:R if filled; RETEST ⇒ TIMELY; expiry / invalidation end it | DONE | `test_late_breakout_…`, `test_return_to_zone_is_timely_with_reason_retest`, `test_invalidation_and_retest_expiry_end_the_setup` |
| E | Exhaustion flags, each explained; POSSIBLE_EXHAUSTION, never "reversal" | DONE (volume profile flag skipped and noted, no volume profile yet) | `test_each_flag_individually` (VWAP, OI progress, RVOL, repeated failure, opposing positioning), `test_no_flags_without_evidence_and_skipped_checks_are_noted` |
| T | MFE/MAE at 1/3/5/10/15/30/60 min after first detection, confirmation, first executable; after-anchor data only; time to target / invalidation; written only once the horizon passed | DONE | `test_mfe_mae_not_written_before_horizon_elapses_in_replay_time` (every minute 10:00–15:40), `test_unusable_bar_makes_the_horizon_unavailable`; real data: `prefix-vs-full-2026-11-06.txt` |
| AT1 | Breakout, 2 ATR run, obstacle 0.5 ATR ⇒ VALID_BUT_LATE with RR_BELOW_MIN, retest plan | DONE | `test_late_breakout_rr_below_min_creates_retest_plan` |
| AT2 | Same fixture, price back in zone ⇒ TIMELY reason RETEST | DONE | `test_return_to_zone_is_timely_with_reason_retest` |
| AT3 | Missing LevelMap ⇒ UNKNOWN, never TIMELY | DONE | `test_missing_level_map_is_unknown_never_timely` (incl. a price inside the retest zone) |
| AT4 | Structural stop identical across re-evaluations | DONE | see 4 |
| AT5 | MFE/MAE not written before the horizon elapses in replay time | DONE | see T. **Mutation check:** writing one minute early fails it; recomputing the stop from price fails AT1 and AT4 |
| R | Report on recorded sessions: share per class, pre_signal_move_atr per class | DONE for the 1 recorded session (2026-11-06, partial) | §5 |

## 3. Facts used

No new external facts and no kiteconnect calls (pure logic over stored data). F-NSE-1 (15:40 close), F-QUOTE-6 (VWAP = atp, via Phase 5).

## 4. Open questions

Q-OPP-1 (VWAP_EXTENSION on 3m ATR fires on most trend-day evaluations), Q-OPP-2 (close = stop invalidates), Q-OPP-3 (no cost model, Q-NSE-3),
Q-OPP-4 (guardrail 8 timestamps missing on Phase 5 detections; interface change), Q-OPP-5 (strict MFE/MAE usability), Q-OPP-6 (schedule the
recorder in EOD; DECIDED, §10), Q-OPP-7 (no positioning setups yet: OI windows disabled, no cadence doc, Q-EOD-1). Still open from Phase 5: Q-CNDL-1, Q-STR-1..6.

## 5. Real data: 2026-11-06 (1 partial session; outage 09:03–11:26)

`python3 -m engine.opportunity 2026-11-06` (config v7 sha256 `e75656b5`, 2 min 12 s): 961 setups, 25,639 evaluations, 25,947 timing rows,
52,547 rows written; a second run wrote 0. Full output: [phase-6-evidence/opportunity-report-2026-11-06.md](phase-6-evidence/opportunity-report-2026-11-06.md).
Phase 4 produced 0 events this day, so every setup comes from Phase 5.

Classification at confirmation (each setup's first evaluation):

| family | setups | TIMELY | VALID_BUT_LATE | EXHAUSTED | UNKNOWN | invalidated at confirmation | ever TIMELY (by retest) |
|---|---|---|---|---|---|---|---|
| BREAKOUT | 2 | 0 | 1 | 1 | 0 | 0 | 0 (0) |
| SWEEP | 863 | 187 | 480 | 195 | 1 | 0 | 382 (113) |
| ZONE | 96 | 3 | 37 | 49 | 5 | 2 | 13 (1) |
| **all** | 961 | 190 (19.8 %) | 518 (53.9 %) | 245 (25.5 %) | 6 (0.6 %) | 2 (0.2 %) | 395 (114) |

Failed rules at confirmation (LATE): RR_BELOW_MIN 513, STOP_TOO_WIDE 83, EXTENDED 45. All 6 UNKNOWN: no obstacle in the trade direction.
How setups ended: INVALIDATED 588, RETEST_EXPIRED 206, still ACTIVE at the close 167.
Exhaustion flags over all evaluations: VWAP_EXTENSION 14,029 (median 6.1 ATR, Q-OPP-1), REPEATED_FAILURE 703, RVOL_DECLINING_WHILE_EXTENDING 350.
OI_PROGRESS_DECLINING 0 and OPPOSING_POSITIONING 0: the combined-OI features and the primary view were unavailable or neutral. **Correction (§10):** the cause is OI_WINDOW_DISABLED (no `docs/measured-oi-cadence.md`, Q-EOD-1), not OI_STALE.

pre_signal_move_atr at confirmation (ATR, signed in the trade direction; negative = price moved against the trade before detection):

| class | n | p25 | median | p75 | mean |
|---|---|---|---|---|---|
| TIMELY | 184 | −1.456 | −0.905 | −0.557 | −1.101 |
| VALID_BUT_LATE | 476 | −1.524 | −0.922 | −0.265 | −0.899 |
| EXHAUSTED | 226 | −1.461 | −0.725 | −0.103 | −0.721 |
| UNKNOWN | 6 | −1.351 | −0.491 | 0.693 | −0.408 |

67 setups have no pre_signal value (the reference 1m bar was unusable). Sweeps are counter-moves by construction, so their pre-signal move is
negative. Per family: [phase-6-evidence/opportunity-report-2026-11-06.md](phase-6-evidence/opportunity-report-2026-11-06.md).
This is one partial day; it says nothing about an edge.

Timing rows: MFE/MAE 20,181 (9,814 with values; UNAVAILABLE: 5,265 unusable bar in the horizon, 3,962 never TIMELY, 1,140 past the close);
time to target / invalidation 5,766 (2,211 with values or NOT_REACHED_BY_CLOSE).

Real-data checks (`phase-6-evidence/`):
- `real-data-checks-2026-11-06.txt`: stop never changes; no MFE/MAE value past 15:40; the 2 setups invalidated at confirmation (close = stop).
- `prefix-vs-full-2026-11-06.txt`: 6 underlyings × 3 cut times. Input truncated at t gives the same setups, evaluations (as_of ≤ t) and timing rows as the full day: 0 differences. Phase 4 states are left out on both sides there for speed; the fixture tests cover them.

## 6. Limitations

- One recorded session with a 2 h 23 min outage. Positioning setups are not exercised on real data (0 events).
- Time to target / invalidation has 1-minute resolution (bar close).
- The CLI recomputes Phase 4 (~100 s) and Phase 5 (~10 s) for the date instead of reading their stores. Both are deterministic, but Phase 4 states are then stamped v7 (same values as v5).
- `exhaustion` window features exist only for `window_min` = Phase 4's `feature_window_min` / its price and OI windows (15). Another value makes those flags "not checked".
- Evaluations are batch only, not live (as Q-POS-5 / Q-STR-6).

## 7. Raw test output

### 7.1 `python3 -m unittest discover -s tests/engine_tests -t . -v` (full file: phase-6-evidence/engine-tests.txt; module paths trimmed)
```
test_backfill_labels_source_records_failures_and_builds_baselines ... ok
test_readers ... ok
test_token_bucket_never_exceeds_rate ... ok
test_window_respects_the_measured_range_cap ... ok
test_depth_snapshots_for_tier_b_only ... ok
test_disconnect_goes_stale_within_threshold_and_ok_only_on_fresh_data ... ok
test_gap_inside_candle_is_partial_with_nothing_interpolated ... ok
test_ohlc_volume_trades_and_rollups ... ok
test_oi_age_when_oi_unchanged_for_minutes ... ok
test_out_of_order_late_duplicate_and_backwards ... ok
test_rollover_combined_oi_is_continuous ... ok
test_session_edges_holiday_and_non_trading_instrument ... ok
test_window_must_exceed_flush_interval ... ok
test_expired_token_fails_cleanly_without_leaking_token ... ok
test_session_prefers_env_then_config_file ... ok
test_v4_loads_and_missing_key_fails ... ok
test_engine_never_uses_kiteconnect_rest_class ... ok
test_no_order_methods_in_repo_code ... ok
test_connection_limits_from_config ... ok
test_near_future_and_spot_resolve ... ok
test_unknown_symbol_fails_loudly ... ok
test_missing_opportunity_key_fails ... /Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/yaml/scanner.py:286: ResourceWarning: unclosed database in <sqlite3.Connection object at 0x108d06980>
  for level in list(self.possible_simple_keys):
ResourceWarning: Enable tracemalloc to get the object allocation traceback
ok
test_each_flag_individually ... ok
test_no_flags_without_evidence_and_skipped_checks_are_noted ... ok
test_phase4_event_becomes_a_setup_and_its_invalidation_ends_it ... ok
test_append_only_and_idempotent ... ok
test_invalidation_and_retest_expiry_end_the_setup ... ok
test_late_breakout_rr_below_min_creates_retest_plan ... ok
test_missing_level_map_is_unknown_never_timely ... ok
test_return_to_zone_is_timely_with_reason_retest ... ok
test_structural_stop_identical_across_reevaluations ... ok
test_unavailable_fields_are_explicit ... ok
test_mfe_mae_not_written_before_horizon_elapses_in_replay_time ... ok
test_unusable_bar_makes_the_horizon_unavailable ... ok
test_report_then_compact_snapshots_losslessly ... ok
test_live_and_replay_identical_golden ... ok
test_half_open_socket_becomes_a_stall_gap_once_and_clears_on_reconnect ... ok
test_cadence_parser_takes_the_max_over_dates ... ok
test_v5_loads_and_missing_positioning_key_fails ... ok
test_confirmation_evidence_and_invalidation ... ok
test_replay_gives_the_same_events_every_run ... ok
test_expiry_day_suppresses_every_view ... ok
test_illiquid_future ... ok
test_implausible_oi_jump ... ok
test_low_sample_history ... ok
test_rollover_near_falls_next_rises_combined_flat_is_not_long_unwinding ... ok
test_stale_oi_suppressed ... ok
test_window_shorter_than_measured_cadence_is_disabled ... ok
test_no_output_text_says_institution_except_the_disclaimer ... ok
test_each_quadrant ... ok
test_index_itself_uses_raw_price ... ok
test_mixed_windows_are_neutral ... ok
test_move_with_beta_times_index_is_index_driven ... ok
test_oi_up_with_flat_price_is_not_a_buildup ... ok
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
[engine] ALERT T: m
[engine] ALERT T2: m
[engine] alert not delivered: OSError('offline')
[engine] ALERT T2: m
ok
test_eod_day_checks ... [engine] ALERT Engine: NOTHING recorded today: No recording for today (ignore if NSE was closed). Check dashboard/logs/engine_recorder.err.log
[engine] ALERT Engine recorder DIED and did not restart: Last data 09:15:20 IST; no clean shutdown logged.
ok
test_eod_no_data_alert_suppressed_only_on_verified_holiday ... [engine] ALERT Engine: NOTHING recorded today: No recording for today (ignore if NSE was closed). Check dashboard/logs/engine_recorder.err.log
[engine] ALERT Engine: NOTHING recorded today: No recording for today (ignore if NSE was closed). Check dashboard/logs/engine_recorder.err.log
ok
test_unclean_stop_detected_only_without_shutdown ... ok
test_eod_compacts_writes_cadence_and_runs_retention ... [engine] ALERT Engine recorder DIED and did not restart: Last data 09:19:50 IST; no clean shutdown logged.
ok
test_restart_records_gap_and_uses_new_connection_id ... ok
test_single_recorder_lock_and_eod_refuses_while_held ... /Users/turagasanthoshkumar/Clade-NSE-Skills/tests/engine_tests/test_storage.py:253: ResourceWarning: unclosed file <_io.TextIOWrapper name='/tmp/tmpsmz_7366/recorder.lock' mode='a' encoding='utf-8'>
  self.assertIsNotNone(acquire_lock(root))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
ok
test_compacted_replay_identical_to_raw_buffer_and_sizes_reported ... ok
test_intervals_from_change_log_excluding_gaps ... ok
test_archive_then_delete_only_with_verified_checksum ... ok
test_mismatch_or_failure_never_deletes ... ok
test_uncompacted_day_is_skipped ... ok
test_accepted_breakdown_by_hold_when_closes_threshold_is_higher ... ok
test_consolidation_then_accepted_breakout ... ok
test_failed_breakout_back_inside ... ok
test_missing_structure_key_fails ... ok
test_nearest_obstacles_and_no_lookahead ... ok
test_atr_seed_continues_from_the_cut_last_bucket ... ok
test_history_and_opening_range_levels ... ok
test_bearish_sweep_and_rejection ... ok
test_bullish_sweep_and_reclaim ... ok
test_equal_lows_cluster ... ok
test_reclaim_and_loss_of_key_levels ... ok
test_sweep_reclaimed_on_second_bar_and_not_after_k ... ok
test_prefix_equals_batch_filtered_and_nothing_before_confirmed_ts
Look-ahead + non-repainting: candle-by-candle (every 1m close) == full-day batch cut at confirmed_ts. ... ok
test_store_is_append_only_and_idempotent ... ok
test_bos_in_trend_direction ... ok
test_choch_is_first_break_against_structure_and_heuristic ... ok
test_gap_breaks_the_pivot_window ... ok
test_swing_confirmed_after_right_bars_with_labels ... ok
test_demand_zone_test_defended_then_invalidated ... ok
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

----------------------------------------------------------------------
Ran 118 tests in 36.616s

OK

fixture storage report: {"before_bytes": {"ticks": 20480, "depth": 8192, "oi_changes": 8192, "events": 8192, "gaps": 8192, "meta": 8192, "frames.bin": 21659, "buffer.sqlite(file)": 40960, "instrument_master(csv.gz)": 235}, "A_parquet_bytes": {"ticks": 19537, "depth": 19721, "oi_changes": 4732, "events": 1298, "gaps": 1113, "meta": 481}, "B_frames_zst_bytes": 1300, "replay": {"events_buffer": 202, "events_parquet": 202, "events_frames": 252, "seconds_buffer": 0.0013, "seconds_parquet_A": 0.0044, "seconds_frames_B": 0.0011}}
exit=0
```

### 7.2 Whole repo `python3 -m unittest discover -s tests -v` (phase-6-evidence/full-suite.txt)
```
Ran 181 tests in 36.549s
OK
exit=0
```

### 7.3 Real-data checks
```
rows: {'setups': 961, 'evaluations': 25639, 'timing': 25947}
setups whose structural_stop differs between evaluations: 0 of 961
setups vs stored setup stop mismatch: 0
first evaluation not ACTIVE: [('2d6476bcd0934564', 'ZONE', 'INVALIDATED', 'CLOSE_THROUGH_STOP: 56905 vs 56905'), ('4f604c38fe6e78d3', 'ZONE', 'INVALIDATED', 'CLOSE_THROUGH_STOP: 177200 vs 177200')]
UNKNOWN at confirmation, missing: Counter({'obstacle: NO_OBSTACLE_IN_TRADE_DIRECTION': 6, 'rr: NO_OBSTACLE_IN_TRADE_DIRECTION': 6})
VWAP_EXTENSION flagged evaluations: 14029 median distance ATR 6.09 p90 9.45
MFE/MAE rows with a value whose horizon ends after 15:40: 0
timing values: Counter({('MFE', True): 10367, ('MFE', False): 9814, ('TIME', True): 3555, ('TIME', False): 2211})
config v7 sha256 e75656b5
NIFTY     : 7 setups; 3 cut times, 13 setup-runs; cut times differing: 0 (0.4s)
RELIANCE  : 25 setups; 3 cut times, 30 setup-runs; cut times differing: 0 (0.4s)
HDFCBANK  : 12 setups; 3 cut times, 20 setup-runs; cut times differing: 0 (0.5s)
ICICIBANK : 11 setups; 3 cut times, 16 setup-runs; cut times differing: 0 (0.3s)
INFY      : 20 setups; 3 cut times, 32 setup-runs; cut times differing: 0 (0.5s)
TCS       : 20 setups; 3 cut times, 23 setup-runs; cut times differing: 0 (0.5s)
```

## 8. Addendum 2026-11-06: Q-OPP-1 decided (VWAP extension in 15m ATR), config v8

Owner decision: the VWAP_EXTENSION flag uses the **15m ATR** whatever the setup timeframe. v7 had already produced stored rows
(sha256 `e75656b5`), so the change is a new config, `config/engine/v8.yaml` (sha256 `8626c7c3`) = v7 +
`opportunity.exhaustion.vwap_atr_timeframe_min: 15`, now the default of `engine.opportunity`. v7 is unchanged; its rows stay in
`opportunity.sqlite` under `v7`, and the v8 rows sit beside them (key includes the config version).

Code: `Snapshot.vwap_atr` (ATR of the configured timeframe; not given ⇒ the check is noted "not checked", no flag),
`exhaustion()` divides by it, `Context.snapshot(tf, t, vwap_atr_tf)` fills it from Phase 5's 15m ATR. Test
`test_each_flag_individually` now also proves it: a 2.15 × setup-ATR distance is 1.07 × a 15m ATR twice as large ⇒ no flag,
and a missing 15m ATR ⇒ no flag + a note.

Re-run 2026-11-06 under v8 (`cli-run-2026-11-06-v8.json`, `opportunity-report-2026-11-06-v8.md`, `v7-vs-v8-2026-11-06.txt`):
961 setups, 22,594 evaluations, 25,947 timing rows.

| at confirmation | v7 | v8 |
|---|---|---|
| TIMELY | 190 (19.8 %) | 209 (21.7 %) |
| VALID_BUT_LATE | 518 (53.9 %) | 590 (61.4 %) |
| EXHAUSTED | 245 (25.5 %) | 154 (16.0 %) |
| UNKNOWN | 6 (0.6 %) | 6 (0.6 %) |
| invalidated at confirmation | 2 | 2 |
| ever TIMELY (by retest) | 395 (114) | 439 (124) |
| VWAP_EXTENSION flags over evaluations, median distance | 14,029, 6.09 × 3m ATR | 8,599, 3.47 × 15m ATR |

v8 failed rules at confirmation (LATE): RR_BELOW_MIN 586, STOP_TOO_WIDE 96, EXTENDED 55.
v8 pre_signal_move_atr at confirmation: TIMELY n 201, median −0.919 (p25 −1.461, p75 −0.516); VALID_BUT_LATE n 539, median −0.886
(−1.562 / −0.197); EXHAUSTED n 146, median −0.664 (−1.369 / −0.122); UNKNOWN n 6, median −0.491.
Even in 15m ATR, VWAP_EXTENSION is the most frequent flag on this trending day. That is the approved 2.0 multiple, reported and not tuned.
No-look-ahead re-check under v8 (`prefix-vs-full-2026-11-06-v8.txt`): 6 underlyings × 3 cut times, 0 differences.
Tests under v8: engine suite 118 OK, whole repo 181 OK (`engine-tests-v8.txt`, `full-suite-v8.txt`, raw lines below).

```
test_each_flag_individually (tests.engine_tests.test_opportunity.Exhaustion.test_each_flag_individually) ... ok
Ran 118 tests in 36.747s
OK
exit=0
test_each_flag_individually (engine_tests.test_opportunity.Exhaustion.test_each_flag_individually) ... ok
Ran 181 tests in 36.964s
OK
exit=0
```

## 9. Addendum 2026-11-06: Q-OPP-2 decided (close equal to the stop invalidates)

Owner decision: **keep** the conservative reading. A 1m close at the structural stop invalidates the setup, the same as a close
through it, for both directions. No code or config change (`track`: `(price - stop) x direction <= 0`), so the stored v7/v8 rows
stand. Test `test_invalidation_and_retest_expiry_end_the_setup` now pins it: long close 99.00 = stop 99.00 ⇒ INVALIDATED
`CLOSE_THROUGH_STOP: 9900 vs 9900`; short close = stop ⇒ INVALIDATED. Real effect on 2026-11-06: the 2 defended zones invalidated at
confirmation stay that way.

## 10. Addendum 2026-11-06: Q-OPP-6 decided (timing recorder in the EOD job)

Owner decision: run the Phase 6 timing recorder in the EOD job.

| File | Change |
|---|---|
| `engine/opportunity.py` | `process()` (one date: run + store; shared by the CLI and EOD), `load_cadence()`, `done(day_dir, version)`, `eod(root, cadence_path, cfg=None)`; `write()` adds a `runs` row (config version, counts) **in the same transaction**, so a date counts as done only when all its rows are stored |
| `engine/eod.py` | after the OI cadence doc and before retention: `out["opportunity"] = opportunity_eod(cfg.root, oi_out or DEFAULT_OUT)` in its own try/except; `failed(out)` (exit code 1) now also covers opportunity errors |
| `scripts/launchd/com.clade.engine-eod.plist` | comment only; the job already runs `python3 -m engine.eod` from the repo, so nothing needs reinstalling |
| `tests/engine_tests/test_opportunity.py` | `test_each_recorded_day_once_failures_isolated_and_retried`; store test counts the `runs` row |

Rules: every recorded day (`snapshots.sqlite` or `parquet/snapshots`) without a `runs` row for the current opportunity config (v8) is processed, so a
missed or failed evening is caught up the next night. A failing day is recorded as `{"error": ...}` and the other days still run. Days with
nothing recorded are skipped. The EOD job runs after 15:40, so every timing horizon up to the close is due (no horizon is written early).
The step uses the opportunity config (v8) with the EOD job's own storage root.

Proof:
- Fixture: the new test (2 recorded days, one failing, one without data; second night re-runs only the failed day; `failed()`), the existing
  EOD fixture test (`opportunity: {}`: its days have no snapshots).
- Real data (`eod-step-real-2026-11-06.txt`): the exact EOD call on the real root. Run 1 processed 2026-11-06 in 119 s: 961 setups, 22,594
  evaluations, 25,947 timing rows; it wrote 1 row (the `runs` row), because the data rows were already there from the v8 CLI run, identically.
  Run 2 did nothing (`{}`).

**Not proven end to end: the EOD job itself dies before reaching the step (Q-EOD-1).** Today's 15:50 launchd run, and two manual runs at
21:24 and 21:33 (`eod-run-1.txt`, `eod-run-2.txt`), were all SIGKILLed (exit 137, no traceback, after ~6–9 min). Each died in the Phase 1 raw
compaction of 2026-11-06 (buffer.sqlite 385 MB + frames.bin 446 MB on an 8 GB Mac with heavy paging). Consequences today:
- the raw buffer is not compacted, and `eod_last.json` is still from 2026-11-05;
- `docs/measured-oi-cadence.md` was never written. Phase 4 therefore disables every OI window, and 37,238 of 37,248 primary evaluations
  are OI_WINDOW_DISABLED. **This corrects §5 and my earlier statement**: today's Phase 4 neutrality is not mainly OI_STALE (Q-POS-1);
- the stored Phase 6 rows for 2026-11-06 (v7 and v8) were computed without a cadence doc. Their OI-based exhaustion checks are recorded as
  "not checked", not as wrong values. Because the date is now marked done for v8, the EOD step will not recompute it once the cadence doc
  exists. Re-running it would need a new config version, or deleting that date's `runs` row (owner's call).

Tests after this change: engine suite and whole repo, raw lines:

```
test_each_recorded_day_once_failures_isolated_and_retried (tests.engine_tests.test_opportunity.EodStep.test_each_recorded_day_once_failures_isolated_and_retried) ... ok
test_append_only_and_idempotent (tests.engine_tests.test_opportunity.Store.test_append_only_and_idempotent) ... ok
test_eod_compacts_writes_cadence_and_runs_retention (tests.engine_tests.test_storage.TestAutomation.test_eod_compacts_writes_cadence_and_runs_retention) ... [engine] ALERT Engine recorder DIED and did not restart: Last data 09:19:50 IST; no clean shutdown logged.
Ran 119 tests in 36.671s
OK
exit=0
test_each_recorded_day_once_failures_isolated_and_retried (engine_tests.test_opportunity.EodStep.test_each_recorded_day_once_failures_isolated_and_retried) ... ok
test_append_only_and_idempotent (engine_tests.test_opportunity.Store.test_append_only_and_idempotent) ... ok
test_eod_compacts_writes_cadence_and_runs_retention (engine_tests.test_storage.TestAutomation.test_eod_compacts_writes_cadence_and_runs_retention) ... [engine] ALERT Engine recorder DIED and did not restart: Last data 09:19:50 IST; no clean shutdown logged.
Ran 182 tests in 35.935s
OK
exit=0
```

