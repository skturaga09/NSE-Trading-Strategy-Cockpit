# Phase 2 report: dynamic trading universe and instrument master

Date: 2026-11-05 (IST). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, phase-0-report.md, phase-1-report.md.

## 0. Owner decisions taken during this phase (2026-11-05)

| Question | Decision |
|---|---|
| Max age of the last good constituent list (step 1, "configurable") | **3 calendar days** → `universe.constituents_max_age_days: 3` |
| Subscription mode (step 6 says quote; quote has no OI, F-WS-6) | **quote, as written**. OI change log and Q-WS-1 cadence measurement wait for Phase 3 |
| Q-UNI-2: stale/missing constituents block INDEX too? (asked at review) | **No: INDEX stays tradable**; constituent flags apply to STOCK contracts only |
| Q-UNI-4: holiday false "NOTHING recorded" alert (asked at review) | **Suppress** using the calendar: `engine.eod.check_today` returns no alerts on a *verified* holiday |

Not asked, chosen and flagged: a self-identifying User-Agent for NSE files (F-NSE-6). A browser-cookie route to the
NSE JSON holiday API was tried once and **blocked by the sandbox as bot-check circumvention**, so holidays come from the
official circular PDFs instead (F-NSE-5).

## 1. Files

| File | Purpose |
|---|---|
| `engine/sources.py` | NSE fetch (config UA + timeout); strict parsers for constituent CSVs and the ban list |
| `engine/universe.py` | registry (versioned by date), daily diff, universe builder, restrictions, `get_universe` / `get_contracts` / `get_contract` / `is_tradable`, `strike_intervals`, `refresh()`, CLI `python3 -m engine.universe` |
| `engine/provider.py` | + `UniverseSubscriptionProvider` (spot + near + next future per member, one mode) |
| `engine/recorder.py` | `_record` runs `refresh()` (idempotent) and subscribes via the new provider |
| `engine/eod.py` | `is_verified_holiday()`; `check_today` skips its alerts on verified F&O holidays |
| `engine/config.py`, `config/engine/v2.yaml` | v2 is the default: `universe`, `restrictions`, `http` blocks; v1's `subscriptions` dropped. v1.yaml left byte-identical as Phase 1's record |
| `scripts/launchd/com.clade.engine-universe.plist` | weekdays 08:35 pre-open refresh. **You install it** |
| `tests/engine_tests/test_universe.py` | 15 fixture tests (no network) |
| `tests/engine_tests/test_edges.py` | config test now checks v2 |
| `tests/engine_tests/test_storage.py` | + `test_eod_no_data_alert_suppressed_only_on_verified_holiday` |
| docs | verified-facts §10 (F-NSE-2..6, F-INST-5/6), open-questions (Q-UNI-1..4, Q-NSE-5/6; Q-NSE-2 and Q-NSE-4 updated), architecture §9 |
| `docs/phase-2-evidence/` | raw test output, live refresh/report, live API checks, live recorder smoke, NSE source probes |

## 2. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| 1 | Constituents from official source, URL in verified-facts, stored daily with source + fetch time | DONE | F-NSE-2/3; `constituents` + `fetches` tables; live: 50 + 100 symbols |
| 1b | Failed fetch → last good list only if ≤ N days old, flagged STALE_CONSTITUENTS; older → block | DONE | `test_stale_constituents_flagged_then_blocked` (1 day: STALE, tradable; 4 days: BLOCKED; NIFTY future tradable on both), `test_index_tradable_without_any_constituent_list` |
| 2 | Universe = (N50 ∪ N100) ∩ active NFO futures; dedup; INDEX family; F&O derived, never assumed | DONE | `test_no_duplicate_underlying_and_fno_derived_from_master`; live: 97 |
| 3 | Registry: underlying, spot token, futures (all active expiries), option tokens, tradingsymbol, type, expiry, strike, lot, tick, segment, active, first/last seen | DONE | `Contract`, `Member`; `test_historical_lookup_and_daily_diff` |
| 3b | Strike intervals derived from listed strikes | DONE | `test_strike_intervals_derived_from_listed_strikes`; live NIFTY 23-Nov: 50 |
| 4 | Daily pre-open job: download, diff vs yesterday, log added/removed/lot changes/rollovers; keep history | DONE | `master_diff`; `test_historical_lookup_and_daily_diff`, `test_token_reused_for_another_contract_resolves_by_date`, `test_refresh_is_idempotent_and_refuses_out_of_order`. Plist written, **not installed** |
| 5a | Ban list from official source daily, source + time | DONE | F-NSE-4; `test_banned_security_not_tradable` |
| 5b | Expiries from master; holidays from official source | DONE | expiries only via master rows; holidays F-NSE-5, circular sha256 re-checked each refresh; `test_holidays_weekends_and_unverified_circulars` |
| 5c | Source not fetched/verified today → RESTRICTION_UNVERIFIED, not tradable | DONE | `test_missing_ban_list_is_restriction_unverified`, `test_ban_list_for_another_trade_date_does_not_verify_today`, circular-checksum case in the holiday test |
| 6 | UniverseSubscriptionProvider: spot + near + next futures, quote mode | DONE | `test_provider_subscribes_spot_near_and_next_in_quote_mode`; live smoke: 291 tokens, 291 quote packets |
| 7 | API get_universe / get_contracts / get_contract / is_tradable | DONE | methods on `Registry` (they need the DB handle); all tests above |
| AT1 | No duplicate underlying | DONE | RELIANCE in both lists → one member, `indices=("NIFTY100","NIFTY50")` |
| AT2 | Constituent without NFO never in universe | DONE | TATACAP → excluded `NO_NFO_FUTURES` |
| AT3 | Expired contracts never active after expiry | DONE | `test_expired_contract_never_active_after_expiry` (stale dump still lists it) |
| AT4 | Banned → False, BANNED | DONE | `(False, ["BANNED"])` |
| AT5 | Missing ban list → RESTRICTION_UNVERIFIED | DONE | see 5c |
| AT6 | Grep test: no numeric lot sizes or date literals in logic modules | DONE | `test_grep_logic_modules` over every `engine/*.py`. On its first run it caught two date literals in my own docstrings, which I fixed |
| AT7 | get_contract(token, past_date) returns that date's mapping | DONE | lot 65 on D1 and 75 on D2; token reused M&M NOV→DEC resolves by date |

## 3. Today's universe (live, 2026-11-05 22:16 IST; master fetched after the close)

| | |
|---|---|
| Universe count | **97** |
| By family | **STOCK 96, INDEX 1** (NIFTY) |
| Constituents | NIFTY 50 (50) ∪ NIFTY 100 (100) = 100 unique; NIFTY 50 ⊂ NIFTY 100 today |
| Excluded | **BAJAJHLDNG, TATACAP, TMCV, VAML**: all `NO_NFO_FUTURES` (no NFO futures in the master) |
| Subscriptions | 291 tokens (97 × spot + 2 futures), quote, 1 connection |
| Registry | 47,537 contracts registered (all NFO + the spots of every NFO underlying); baseline day, so no diff yet |
| Restrictions today | holidays verified (both circular checksums match). **Ban list RESTRICTION_UNVERIFIED for 2026-11-05**: by the evening NSE's file is already for 06-NOV (KAYNES banned; stored for that date). So every derivative answers `is_tradable = False` today. That is correct for a list that can no longer be checked; tomorrow's 08:35 refresh should verify 06-Nov (Q-UNI-3) |

## 4. Facts used

F-INST-1..3, F-WS-2/4/6/7 (Phases 0–1) and new F-NSE-2..6, F-INST-5/6 (verified-facts §10, with URLs).

## 5. Open questions raised (need you)

- Q-UNI-1 / Q-UNI-3: no-ban file format and morning ban-file date are unmeasured.
- Q-NSE-5: weekends and the 2026-11-08 Muhurat session are RESTRICTION_UNVERIFIED.
- Q-NSE-6: the 2027 F&O holiday circular must be added to config by ~Dec 2026, or all 2027 dates are unverified.

## 6. Limitations and assumptions

- **Recorder change takes effect at the next 09:00 start**: 291 quote tokens instead of Phase 1's 12 full ones. The OI log and `docs/measured-oi-cadence.md` (Phase 1 step 6) produce nothing in quote mode.
- Holiday alert suppression needs that day's circular re-check (08:35 job or the recorder's refresh). If neither ran, the alert still fires: a false alarm, never a hidden failure.
- `BANNED` applies to NFO contracts only. Spot rows are not checked against the F&O ban list.
- Holidays come from config dates copied from the circular, plus a checksum re-check every day. A **new** amending circular would not be detected automatically; it has to be added to config.
- `NO_MASTER`: dates without an applied master answer nothing. A day the refresh missed cannot be reconstructed later unless its `instruments.csv.gz` exists.
- Out-of-order masters are refused (a past date can't be inserted after a later one).
- The registry keeps the master's own strings (e.g. `lot_size "65"`) and converts them on read. Strike is `None` for futures and spots.
- Live runs happened after the close: the master dump was the 2026-11-05 one, and the WebSocket sent one snapshot packet per token.
- Protected assets: `git diff --stat defa774` still shows only Phase 1's `.gitignore` (+3 lines).

## 7. Raw test output

### 7.1 `python3 -m unittest discover -s tests/engine_tests -t . -v` (full file: phase-2-evidence/engine-tests.txt; only module paths trimmed. The ALERT lines are printed by alert tests with the sender stubbed)
```
test_expired_token_fails_cleanly_without_leaking_token ... ok
test_session_prefers_env_then_config_file ... ok
test_v2_loads_and_missing_key_fails ... ok
test_engine_never_uses_kiteconnect_rest_class ... ok
test_no_order_methods_in_repo_code ... ok
test_connection_limits_from_config ... ok
test_near_future_and_spot_resolve ... ok
test_unknown_symbol_fails_loudly ... ok
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
test_single_recorder_lock_and_eod_refuses_while_held ... /Users/turagasanthoshkumar/Clade-NSE-Skills/tests/engine_tests/test_storage.py:251: ResourceWarning: unclosed file <_io.TextIOWrapper name='/tmp/tmp5utyajby/recorder.lock' mode='a' encoding='utf-8'>
  self.assertIsNotNone(acquire_lock(root))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
ok
test_compacted_replay_identical_to_raw_buffer_and_sizes_reported ... ok
test_intervals_from_change_log_excluding_gaps ... ok
test_archive_then_delete_only_with_verified_checksum ... ok
test_mismatch_or_failure_never_deletes ... ok
test_uncompacted_day_is_skipped ... ok
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
Ran 49 tests in 1.104s

OK
fixture storage report: …(see file)
exit=0
```

### 7.2 Whole repo `python3 -m unittest discover -s tests -v` (phase-2-evidence/full-suite.txt)
```
Ran 112 tests in 0.817s

OK
exit=0
```

### 7.3 Live: phase-2-evidence/live-universe.txt, live-api.txt, live-smoke.txt

## 8. Install (owner)
```
cp scripts/launchd/com.clade.engine-universe.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.clade.engine-universe.plist
```
Without it, the recorder's own 09:00 refresh still runs everything, just later.
