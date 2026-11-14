# Phase 1 report: raw market recorder and deterministic replay engine

Date: 2026-11-05 (IST). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, phase-0-report.md.

## 0. Owner decisions taken at the start of this phase (2026-11-05)

| Question | Decision |
|---|---|
| Q-WS-5 WebSocket client | install `kiteconnect` 5.2.2 and use **only** `KiteTicker` (never the REST `KiteConnect` class, which carries order methods) |
| Dependencies | install `pyarrow` 26.0.1 (Parquet/zstd) and `boto3` 1.43.124 (S3 archive). Twisted 26.10.0 and autobahn 19.11.2 came with kiteconnect |
| Q-OPS-1 Phase 1 universe | NIFTY, RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS: near-month future + spot, all `full` mode |
| Q-OPS-2 retention / disk | raw data kept for 5 sessions, archived to `~/EngineArchive`; disk guard alerts below 5 GB free, stops depth below 3 GB, stops ticks below 2 GB |

## 1. Files

| File | Purpose |
|---|---|
| `engine/config.py`, `config/engine/v1.yaml` | versioned config with SHA-256; every key required, no defaults in code |
| `engine/broker.py` | read-only session (env → `kite_config.json`), `check()`, `instruments_csv()`, `refresh()` (reuses `refresh_kite_token.refresh`), `ticker()`. `TokenExpired` on 403/TokenException. **No order methods** |
| `engine/provider.py` | `SubscriptionProvider` protocol + `ConfigSubscriptionProvider` (near-month future / exact tradingsymbol → token via the day's master) |
| `engine/packets.py` | pure frame split + decode into raw exchange integers (F-WS-4/5/7, F-WS-9) |
| `engine/store.py` | per-date `DayStore` (SQLite WAL buffer, INSERT only) + raw frames log; `Event`, ordering key |
| `engine/recorder.py` | `Recorder` (non-blocking callback → bounded queue → writer thread; change-only writes; OI change log; gaps; disk guard; status) + live CLI |
| `engine/replay.py` | `day_events`/`load_events` (buffer, parquet or frames), `replay()`, `ReplayClock`, `AsOfStore`, `encode()` |
| `engine/health.py` | health CLI |
| `engine/oi_cadence.py` | OI-change cadence → `docs/measured-oi-cadence.md` |
| `engine/compact.py` | EOD: per-table size report, Parquet (A), zstd frames (B), verification, timed replay of both |
| `engine/retention.py` | archive → sha256 verify → delete; local path or S3 |
| `tests/engine_tests/*` | 27 fixture tests (no network) |
| `.github/workflows/engine-tests.yml` | CI: runs the engine tests, including the no-order grep test |
| `.gitignore` | `data/engine/` |
| docs | verified-facts §9 (F-NSE-1, F-WS-8..12, F-INST-4); open-questions updated + Q-STORE-1..3, Q-OPS-6; architecture §8 (as built, deviations) |
| `docs/phase-1-evidence/` | raw test output, live smoke output, installed versions |

## 2. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| 1 | Broker adapter: session from env, token refresh flow, clean failure on expired token, no order methods | DONE | `test_expired_token_fails_cleanly_without_leaking_token`, `test_session_prefers_env_then_config_file`; live: session check OK (live-smoke.txt). `refresh()` calls the existing flow; **not exercised** (it would log in to your account) |
| 2 | SubscriptionProvider, config-listed symbols resolved via the master at startup | DONE | `test_near_future_and_spot_resolve`, `test_unknown_symbol_fails_loudly`; live: 12 tokens resolved |
| 3a | KiteTicker, limits read from config (F-WS-2) | DONE | `test_connection_limits_from_config`; `ws.*` in v1.yaml |
| 3b | Every tick as received + receive_ts, exchange_ts, last_trade_ts, token, mode, connection_id, per-connection seq | DONE | frames log is byte-exact for every frame (`test_out_of_order_and_duplicates…`). The `ticks` table holds every decoded field; seq is per connection, per packet |
| 3c | OI change log, a row only when OI changes, with the exchange ts of the change | DONE | `test_oi_change_log_only_on_change` (first row of the day = baseline, `prev_oi` NULL) |
| 3d | Depth snapshots for full-mode instruments | DONE | `test_change_only_ticks_and_rate_limited_depth` |
| 3e | Connection events; gaps detectable from data alone | DONE | `test_disconnect_produces_gap_and_no_synthetic_ticks`, `test_disconnect_open_at_session_end_is_closed_as_gap`, `test_own_shutdown_close_is_not_a_gap` |
| 3f | Daily full instrument master snapshot with the date | DONE | `<date>/instruments.csv.gz`; live: 1,658,982 bytes |
| 3g | Append-only, partitioned by date; buffered writes; bounded queue; queue metric; drops logged as a gap | DONE | `test_queue_overflow_logs_gap_not_crash`; `status.json` has `queue_depth`, `dropped_total` |
| 4 | Replay in (exchange_ts, receive_ts, seq) order through the live interface; ReplayClock; AsOfStore; max speed or real-time multiple | DONE | `test_live_consumers_get_same_events_as_replay`, `test_get_latest_never_returns_future_data_property`, `test_real_time_speed_sleeps_by_clock_delta` |
| 5 | Health CLI: ticks/s, instruments live, last tick age, queue depth, gaps today | DONE | `python3 -m engine.health`; output in live-smoke.txt |
| 6 | OI cadence measurement → docs/measured-oi-cadence.md | PARTIAL | script done and tested (`test_intervals_from_change_log_excluding_gaps`). **The file needs a market-hours session** (your live check). I did not create a placeholder |
| 7 | Bytes/day per table on one recorded session | PARTIAL | `engine.compact` reports it (`before_bytes`). Only fixture and an after-hours 12-packet snapshot exist, which are not representative |
| 8 | Parquet zstd typed + raw-frames alternative, prototyped on the same session, size + replay speed, pick one, record in architecture.md | PARTIAL | both formats are written and verified on every compaction. **Decision pending real data** (Q-STORE-1). architecture.md §8 says so |
| 9 | Change-only depth (≤1/s/instrument, config) and ticks; determinism tests still pass | DONE | `test_change_only_ticks_and_rate_limited_depth` + all replay tests. Conflict with "duplicates stored as received" flagged as Q-STORE-2 |
| 10 | Retention: derived data forever, raw for N sessions then archive (local/S3), checksum-verified before delete | DONE | `test_archive_then_delete_only_with_verified_checksum`, `test_mismatch_or_failure_never_deletes` (corrupting, failing and fake-S3 targets), `test_uncompacted_day_is_skipped`. S3 was tested only against a fake client |
| 11 | Disk guard: alert, then stop depth, then ticks; each logged as a gap | DONE | `test_disk_guard_degrades_depth_then_ticks_with_gap_records` |
| AT1 | Out-of-order/duplicates stored as received, deterministic order, byte-identical replays | DONE | `test_out_of_order_and_duplicates_stored_as_received_and_replay_deterministic` |
| AT2 | AsOfStore never returns receive_ts > as_of (property test) | DONE | 200 random trials × every step × 5 queries (stdlib `random`, seed 20261105; hypothesis isn't installed) |
| AT3 | Disconnect → gap record, no synthetic ticks | DONE | see 3e |
| AT4 | OI log only on change | DONE | see 3c |
| AT5 | Queue overflow → logged gap, no crash | DONE | see 3g |
| AT6 | No order code (grep test in CI) | DONE | `test_no_order_methods_in_repo_code` (all tracked + new .py/.ts/.tsx/.js/.sh) and `test_engine_never_uses_kiteconnect_rest_class`; workflow added |
| AT7 | Size per day before and after optimization | PARTIAL | reported by `engine.compact` (`frames.bin` = unoptimized, all packets; `A_parquet_bytes`/`B_frames_zst_bytes` = after). Needs a real session |
| AT8 | Replay of the compacted day identical to the raw buffer | DONE | `test_compacted_replay_identical_to_raw_buffer_and_sizes_reported`; also on live smoke data (`parquet_replay_identical: true`) |
| AT9 | Archive-then-delete never removes a file without a verified checksum | DONE | see 10 |
| AT10 | Disk-guard degradation → gap records | DONE | see 11 |

## 3. Facts used

F-WS-1..7 (Phase 0) plus new: **F-NSE-1** market hours 09:15–15:40 (NSE/FAOP/74467, effective 2026-08-03; the old 15:30 close would have been wrong), **F-WS-8/9** library source (reconnect, resubscribe, divisors), **F-WS-10..12, F-INST-4** measured in the smoke run. URLs are in verified-facts.md §9.

## 4. Open questions raised (need you)

- **Q-STORE-1**: pick format A or B after the first full session's `storage_report.json`.
- **Q-STORE-2**: "duplicates stored as received" (step 1) vs "skip unchanged ticks" (step 9). Currently resolved by keeping both stores.
- **Q-STORE-3**: the instrument master is kept forever at ~1.66 MB/day (~0.6 GB/yr).
- **Q-OPS-6**: compaction and retention are CLIs. No launchd job was installed.
- **Interface deviations** from the Phase 0 plan (`Recorder` signature, per-date storage instead of a single `engine.db`/`observation` table, `replay()` signature) are listed in architecture.md §8 for your sign-off.

## 5. Limitations and assumptions

- No market-hours data yet. Every number in the fixture storage report is from synthetic fixtures (and is noted as such); the parquet overhead dominates at that size.
- `engine.health` reads `status.json`, which the recorder rewrites every second. The live smoke output shows `connections {'0': 'connected'}` after shutdown. That label bug was fixed afterwards (state becomes `shutdown`).
- Parquet replay is ~10–100× slower than frames replay at fixture size (per-row Python conversion). It must be re-measured on a real day before deciding Q-STORE-1.
- "GB" in the disk guard = 10^9 bytes.
- Instrument family for Parquet partitioning = master `segment` (`NFO-FUT`, `NSE`, `INDICES`). The phase text didn't define "family".
- The token refresh flow (`--refresh`) wasn't executed: it performs a real login.
- The REST adapter has no rate limiter. Phase 1 makes 2 REST calls per run (check + master).
- Existing suite: 63 tests unaffected; full discovery is 90 tests, all OK. Protected assets: `git diff --stat defa774` shows only `.gitignore` (+3 lines).

## 6. Raw test output

### 6.1 `python3 -m unittest discover -s tests/engine_tests -t . -v` (full file: phase-1-evidence/engine-tests.txt; module paths trimmed here)
```
test_expired_token_fails_cleanly_without_leaking_token ... ok
test_session_prefers_env_then_config_file ... ok
test_v1_loads_and_missing_key_fails ... ok
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
test_compacted_replay_identical_to_raw_buffer_and_sizes_reported ... ok
test_intervals_from_change_log_excluding_gaps ... ok
test_archive_then_delete_only_with_verified_checksum ... ok
test_mismatch_or_failure_never_deletes ... ok
test_uncompacted_day_is_skipped ... ok

----------------------------------------------------------------------
Ran 27 tests in 0.708s

OK

fixture storage report: {"before_bytes": {"ticks": 20480, "depth": 8192, "oi_changes": 8192, "events": 8192, "gaps": 8192, "meta": 8192, "frames.bin": 21659, "buffer.sqlite(file)": 40960, "instrument_master(csv.gz)": 235}, "A_parquet_bytes": {"ticks": 19537, "depth": 19721, "oi_changes": 4732, "events": 1298, "gaps": 1113, "meta": 481}, "B_frames_zst_bytes": 1300, "replay": {"events_buffer": 202, "events_parquet": 202, "events_frames": 252, "seconds_buffer": 0.0028, "seconds_parquet_A": 0.0301, "seconds_frames_B": 0.0012}}
exit=0
```

### 6.2 Whole repo suite `python3 -m unittest discover -s tests -v` (full file: phase-1-evidence/full-suite.txt)
```
Ran 90 tests in 0.498s

OK
exit=0
```

### 6.3 Live smoke (after hours, read-only): see phase-1-evidence/live-smoke.txt

## 7. Live check (automated after the review request "can you automate these steps?")

Added after the first review: `engine/eod.py`, `scripts/launchd/com.clade.engine-recorder.plist`,
`scripts/launchd/com.clade.engine-eod.plist`. The recorder now takes a lock (`data/engine/recorder.lock`),
exits at once when `--until` has passed, and on a same-day restart writes a `restart` gap and uses
new connection ids. Tests: `test_restart_records_gap_and_uses_new_connection_id`,
`test_single_recorder_lock_and_eod_refuses_while_held`, `test_eod_compacts_writes_cadence_and_runs_retention`
(engine tests 30, full suite 93, all OK: phase-1-evidence/*.txt).

| When (IST, weekdays) | Job | Does |
|---|---|---|
| 08:00 | existing `com.clade.kite-refresh` | token |
| 08:45 | existing pmset repeat `wakepoweron` | wakes the Mac |
| 09:00 (+ every 15 min retry until 15:45) | `com.clade.engine-recorder` | `caffeinate -i python3 -m engine.recorder --until 15:45` |
| 15:50 | `com.clade.engine-eod` | health → `<date>/health.txt`; compact (verified); `docs/measured-oi-cadence.md`; retention; `data/engine/eod_last.json` |

Install (owner):
```
cp scripts/launchd/com.clade.engine-*.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.clade.engine-recorder.plist
launchctl load -w ~/Library/LaunchAgents/com.clade.engine-eod.plist
```
After the first session, paste `data/engine/<date>/health.txt`, `docs/measured-oi-cadence.md` and
`data/engine/<date>/storage_report.json` here. Q-STORE-1 is decided from them.

### 7.1 Phone alerts (owner request: "add the ntfy alert if the recorder dies")

`engine/alerts.py` → existing `dashboard.exit_monitor.notify` (channel from `dashboard/exit_config.json`), priority 5,
at most once per (IST date, cause), in `data/engine/alerts_sent.json`. A failed send never raises and is retried on the next trigger.

| Cause | Detected by | When |
|---|---|---|
| Kite token rejected at start | recorder | at the 09:00 start / each 15-min retry (alerted once) |
| Python exception | recorder | immediately |
| All WebSocket connections out of reconnect attempts | recorder | immediately |
| Killed / crashed hard / Mac slept | next recorder start (no `shutdown` event after the last `connect`) | ≤15 min after wake/retry, with the down window |
| Died and never restarted, or nothing recorded, or 0 ticks | `engine.eod` at 15:50 (weekdays) | after close |
| Disk guard alert / stop depth / stop ticks | recorder | immediately |

Tests: `test_alert_once_per_day_and_failed_send_is_retried`, `test_unclean_stop_detected_only_without_shutdown`,
`test_eod_day_checks`; engine tests 33, full suite 96, all OK. `tests/engine_tests/__init__.py` disables the real
sender for all tests. **Incident:** one test run before that guard existed called the real `notify`, which pushed a false
"Engine recorder DIED and did not restart" alert on 2026-11-05 ~22:00 IST. The owner confirmed receiving it, so
end-to-end delivery (engine → notify → ntfy → phone) is verified.
Known gap: an NSE holiday triggers a false "NOTHING recorded today" (holiday calendar unverified, Q-NSE-2).
