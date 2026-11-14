# Phase 13 report: volume profile and order-book behaviour (2026-11-07)

Advisory and paper-trading only. Nothing in this phase places, modifies or cancels an order; no order function exists.

## 0. Owner answers (this phase)

| Row | Answer | Decision |
|---|---|---|
| Q-13-1 (BLOCKING): proceed while 14 earlier BLOCKING rows are OPEN | proceed | D-58 |
| Q-13-2 (BLOCKING): profile levels in the LevelMap | (a): Phase 5 detections under v17, latest snapshot only, they act as obstacles | D-59 |
| Q-13-3 (BLOCKING): TICK_BASED honesty and coverage | proposal OK | D-60 |
| Q-13-4 … Q-13-8 (NON-BLOCKING) | stand as ASSUMED | D-60 |

Still OPEN (BLOCKING, earlier phases): Q-0-2, Q-0-3, Q-0-6, Q-0-7, Q-0-8, Q-1-4, Q-3-1, Q-6-2, Q-7-4, Q-7-5, Q-7-6, Q-7-8, Q-7-9, Q-7-10.

## 1. Files

New
- `engine/profile.py`: pure profile / levels / rejection / depth behaviour / score parts; edge `load_ticks`, `add_profile`.
- `config/engine/v17.yaml`: v16 + `profile.*`, `depth.*`, `signals.part_shares` (v16 not edited).
- `tests/engine_tests/test_profile.py`: 25 tests, fixtures only.
- `docs/phase-13-report.md` (this file).

Changed
- `engine/structure.py`: `PROFILE_LEVELS`; `levels_at` adds the latest profile snapshot's levels.
- `engine/opportunity.py`: `exhaustion` HIGH_VOLUME_ZONE_REJECTION (configs with `profile`); `run_date` calls `add_profile`.
- `engine/signals.py`: `_factor(..., shares=None)`; v17 profile_depth parts.
- `engine/signal_report.py`: `run_date` calls `add_profile`.
- `engine/backtest.py`: `factor_study`.
- `engine/backtest_report.py`: per-anchor part values, `profile_study`, R8 / PIPELINE_CHECK tables, HISTORICAL not-representable entry.
- `docs/architecture.md` §20, `docs/decisions.md` D-58..D-60, `docs/questions-ledger.md` Q-13-1..Q-13-12.

Not changed: frontend (see §5, requirement 1c), `engine/eod.py` and every live default (Q-13-9).

## 2. Requirements

| # | Requirement | Status | Proof |
|---|---|---|---|
| 1 | Session profile per underlying: POC, VAH, VAL (value-area % in config), HVNs, LVNs | DONE | `test_poc_and_value_area_match_the_hand_computation`, `test_hvn_and_lvn`, `test_poc_tie_goes_to_the_bin_nearest_the_middle_then_the_lower`, `test_bin_is_bps_of_the_first_price_rounded_up_to_the_tick` |
| 1a | Tick-based where recorded ticks exist, labelled TICK_BASED | DONE | `test_tick_profile_matches_the_hand_computed_poc_and_value_area`, `test_minute_tick_volume_equals_its_candle_volume_or_the_minute_is_not_used`, `test_no_look_ahead`, `test_partial_or_missing_minutes_make_the_profile_unavailable`; real data §4.1 |
| 1b | Candle-based fallback labelled APPROXIMATE, never presented as trade-at-price | DONE (data, detections, score details) | `test_candle_based_profile_is_labelled_approximate_in_data`, `test_candle_volume_is_spread_evenly_over_the_range`, `test_no_ticks_for_the_token_falls_back_to_approximate`, `test_profile_part_value_and_label` |
| 1c | APPROXIMATE label in the UI | PARTIAL | The label is in the score-part detail string, which `SignalDetail.tsx` renders verbatim (`p.detail`). It is not visible today: v17 signals are not exported (Q-13-9), and profile detections are not stored in structure.sqlite, so the chart draws no profile lines (Q-13-10). No frontend test |
| 2 | Profile levels in the LevelMap | DONE | `test_level_map_uses_only_the_latest_profile_snapshot` |
| 2a | Exhaustion flag "rejection at high-volume zone" | DONE | `test_hvz_rejection_detection_and_exhaustion_flag`, `test_configs_before_v17_keep_the_old_note` |
| 3 | Depth behaviour (Tier B only): spread, imbalance, replenishment, withdrawals, possible absorption, labelled "observed in 5-level depth" | DONE (fixtures) / no real data | `test_replenishment_and_possible_absorption_at_the_offer`, `test_withdrawal_needs_no_trade_at_the_price_and_less_volume_than_the_drop`, `test_imbalance_from_visible_pending_quantity`, `test_no_tier_b_snapshots_is_unavailable`. 2026-11-06 has 0 Tier B depth snapshots (§4.1) |
| 3a | Spoofing / iceberg / aggressor never labelled confirmed | DONE | `test_no_depth_field_claims_confirmed_spoofing_iceberg_or_aggressor` (no "confirm" anywhere in depth output; no spoof / iceberg / aggressor field) |
| 4 | Fill the profile+depth score factor | DONE (weight 0) | `test_v17_profile_depth_parts_carry_weight_zero_and_scores_do_not_change`, `test_profile_part_value_and_label`; real data §4.3 |
| 5 | Re-run the Phase 12 study; weights stay 0 without out-of-sample value | DONE | `test_below_final_or_small_samples_are_insufficient_and_weights_stay_zero`, `test_final_with_separated_cis_adds_value_else_no_evidence`, `test_historical_dataset_lists_the_profile_as_not_representable`; run §4.2: INSUFFICIENT_SAMPLE, weights 0 |
| — | Acceptance: fixture profile matches hand-computed POC/VA | DONE | `test_poc_and_value_area_match_the_hand_computation`, `test_tick_profile_matches_the_hand_computed_poc_and_value_area` |
| — | Acceptance: candle-based output carries APPROXIMATE | DONE | `test_candle_based_profile_is_labelled_approximate_in_data` |
| — | Acceptance: no depth field labelled confirmed spoofing/iceberg (string test) | DONE | `test_no_depth_field_claims_confirmed_spoofing_iceberg_or_aggressor` |
| — | Pure core, time as input | DONE | `test_profile_core_reads_no_clock` |

## 3. Verified facts used (docs/verified-facts.md)

| Fact | Used for | Source |
|---|---|---|
| F-INST-2 | master `tick_size` column: the bin is a whole multiple of it | https://kite.trade/docs/connect/v3/market-quotes/ (+ MEASURED) |
| F-WS-5 | `full` packets carry volume and 5 + 5 depth levels | https://kite.trade/docs/connect/v3/websocket/ |
| F-QUOTE-7 | depth quantity = pending orders, not executed volume | https://kite.trade/docs/connect/v3/market-quotes/ |
| F-QUOTE-8 | 5 buy + 5 sell levels (not a full book) | MEASURED measured-kite.txt |
| F-WS-7 | index packets have no volume or depth: HISTORICAL_CANDLES cannot test the profile | https://kite.trade/docs/connect/v3/websocket/ |
| F-HIST-11 | tick-delta 1m volume = exchange minute volume (basis for TICK_BASED) | MEASURED (Phase 3) |

No new external fact was needed. The 70 % value area is a market convention, not a verified fact: config, PROPOSED (Q-13-5).

## 4. Runs on recorded data

### 4.1 Profile on 2026-11-06 (read-only; nothing written)

Script `docs/phase-13-evidence/p13_real.py` (v17 `add_profile` on Phase 5 detections), raw output:

```
underlyings 97 depth snapshot rows 0
detections {'PROFILE_UNAVAILABLE': 7469}
labels {('PROFILE_UNAVAILABLE', 'TICK_BASED'): 7469}
unavailable reasons {'INSUFFICIENT_DATA': 2528, 'INSUFFICIENT_COVERAGE': 4941}
runtime_s 21.2
```

Reconciliation diagnostic (`docs/phase-13-evidence/p13_diag.py`), raw output:

```
NIFTY tick rows 15565 1m candles 384 COMPLETE/EMPTY+OK 251 tick==candle 251 first candle 09:15 tick 0.1 coverage at close 0.652
RELIANCE tick rows 12087 1m candles 384 COMPLETE/EMPTY+OK 245 tick==candle 245 first candle 09:15 tick 0.1 coverage at close 0.636
HDFCBANK tick rows 18669 1m candles 384 COMPLETE/EMPTY+OK 251 tick==candle 251 first candle 09:15 tick 0.05 coverage at close 0.652
INFY tick rows 16100 1m candles 384 COMPLETE/EMPTY+OK 251 tick==candle 251 first candle 09:15 tick 0.1 coverage at close 0.652
all near futures: usable candles 22328 reconciled tick==candle 22328
```

Every usable minute reconciles, but the session's best coverage is 0.652 < 0.95, so every profile is UNAVAILABLE (correct under D-60).
**No profile level has been produced on real data yet.** No Tier B depth snapshot exists, so depth behaviour is UNAVAILABLE NOT_TIER_B.

DIAGNOSTIC ONLY (min_coverage forced to 0, not engine output; `docs/phase-13-evidence/p13_diag2.py`), NIFTY near future at the close:

```
TICK_BASED NIFTY26NOVFUT bin 12.4 POC 24967.4 VAL 24824.8 VAH 25060.4 HVN [24955.0, 25029.4] LVN [24992.2] coverage 0.6519 volume 4944680
APPROXIMATE NIFTY26NOVFUT bin 12.4 POC 25017.0 VAL 24837.2 VAH 25060.4 HVN [25029.4] LVN [] coverage 0.6519 volume 4944680
engine output at min_coverage 0.95: Unavailable(reason='INSUFFICIENT_COVERAGE: coverage 0.65 < profile.min_coverage 0.95 (251/385 usable minutes, TICK_BASED)')
```

The candle approximation moves the POC by 49.60 points on the same minutes: why it is labelled APPROXIMATE.

### 4.2 Phase 12 re-run (`python3 -m engine.backtest_report recorded --config config/engine/v17.yaml --pipeline-check 2026-11-06`)

```
{"run_dir": "/Users/turagasanthoshkumar/Clade-NSE-Skills/data/engine/backtest/20261107T194407", "runtime_s": 17.9, "half_life_file": "config/engine/half_life/v1.json", "recorded_stage": "BELOW_SYSTEM_CHECK"}
```

report.md R8 (RECORDED): stage BELOW_SYSTEM_CHECK, 0 good sessions; volume_profile and depth_behaviour verdict INSUFFICIENT_SAMPLE
("no conclusion before FINAL"), no rows. PIPELINE_CHECK 2026-11-06 (excluded from every result): 289 FIRST_EXECUTABLE events, all
`UNAVAILABLE INSUFFICIENT_COVERAGE` (volume_profile) and `UNAVAILABLE NOT_TIER_B` (depth_behaviour); verdict INSUFFICIENT_SAMPLE.
HISTORICAL_CANDLES: NOT_REPRESENTABLE (index, F-WS-7). **Out-of-sample value: none shown; weights stay 0** (v17 `part_shares`).
The half-life file is unchanged (v1).

### 4.3 Phase 8 under v17 vs v16, 2026-11-06 (in memory, nothing written)

Script `docs/phase-13-evidence/p13_signals.py` (`signal_report.run_date` under each config), raw output:

```
v16 recommendations 86 profile_depth parts {('volume_profile', 5.0, 'NO_VOLUME_PROFILE'): 86, ('visible_depth', 5.0, 'value'): 76, ('visible_depth', 5.0, 'NO_CANDIDATE'): 10}
v17 recommendations 86 profile_depth parts {('volume_profile', 0.0, 'INSUFFICIENT_COVERAGE'): 86, ('depth_behaviour', 0.0, 'NOT_TIER_B'): 86, ('visible_depth', 5.0, 'value'): 76, ('visible_depth', 5.0, 'NO_CANDIDATE'): 10}
same recommendation ids: True | score/status/classification differences: 0
```

Same 86 recommendations, 0 differences in score, status or classification: the v17 parts are filled (with their UNAVAILABLE reasons) at weight 0. Note: Phase 5 profile levels and Phase 6 HIGH_VOLUME_ZONE_REJECTION could not change anything on this day, because no profile was available (§4.1).

## 5. Limitations

- No real profile levels yet (coverage 0.652 on the only recorded session); no Tier B data ever (Q-8-4, Q-13-4).
- TICK_BASED is still not trade-at-price: volume between packets is attributed at the packet's last price (D-60).
- v17 is not live: the EOD job and live defaults still use v14 / v15. The API and the paper ledger read the numerically latest stored
  version, so writing v17 rows would switch them (Q-13-9). Real-data runs here were dry-run / in-memory.
- UI: no profile lines on the chart and no visible APPROXIMATE label until v17 signals are exported and profile detections are stored
  (requirement 1c PARTIAL; Q-13-10). No frontend file changed, so tsc / vitest were not re-run.
- A minute counts from its candle close, as in Phase 5 (Q-13-11).
- Session note: while checking the recording, a `sqlite3` CLI call created an empty 0-byte `data/engine/2026-11-06/snapshots.sqlite`
  (the CLI creates missing files). `read_snapshots` prefers that file, so engine reads of the day failed until it was removed (verified 0
  bytes, no tables, created 19:26 by that call). No recorded data was changed. The first full test run happened while it existed
  (fixtures only; same result as the final run).

## 6. Assumptions and open questions (ledger rows)

ASSUMED: Q-13-4 (strict Tier B), Q-13-5 (thresholds), Q-13-6 (weights 0), Q-13-7 (near future, today only), Q-13-8 (OOS rule),
Q-13-9 (v17 not live), Q-13-10 (everything as Detections; not stored), Q-13-11 (timing), Q-13-12 (part values).
New OPEN rows: none. Earlier ASSUMED rows stand and are re-reported in Phase 15.

## 7. Test suite

`python3 -m unittest discover -s tests/engine_tests -t .`, raw output:

Full raw output: `docs/phase-13-evidence/full-test-run.txt`. Raw failure block and summary below. 300 tests, 1 failure: the known Q-9-24 weekend-clock failure (`test_eod_compacts_writes_cadence_and_runs_retention`, also failing in Phase 12; today is Saturday). All 25 Phase 13 tests pass.

```
======================================================================
FAIL: test_eod_compacts_writes_cadence_and_runs_retention (tests.engine_tests.test_storage.TestAutomation.test_eod_compacts_writes_cadence_and_runs_retention)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/turagasanthoshkumar/Clade-NSE-Skills/tests/engine_tests/test_storage.py", line 270, in test_eod_compacts_writes_cadence_and_runs_retention
    self.assertEqual(sent, ["Engine recorder DIED and did not restart"])  # fixture day has no shutdown event
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: Lists differ: [] != ['Engine recorder DIED and did not restart']

Second list contains 1 additional elements.
First extra element 0:
'Engine recorder DIED and did not restart'

- []
+ ['Engine recorder DIED and did not restart']

----------------------------------------------------------------------
Ran 300 tests in 47.612s

FAILED (failures=1)

fixture storage report: {"before_bytes": {"ticks": 20480, "depth": 8192, "oi_changes": 8192, "events": 8192, "gaps": 8192, "meta": 8192, "frames.bin": 21659, "buffer.sqlite(file)": 40960, "instrument_master(csv.gz)": 235}, "A_parquet_bytes": {"ticks": 19537, "depth": 19721, "oi_changes": 4732, "events": 1298, "gaps": 716, "meta": 346}, "B_frames_zst_bytes": 1300, "replay": {"events_buffer": 202, "events_parquet": 202, "events_frames": 252, "seconds_buffer": 0.001, "seconds_parquet_A": 0.0156, "seconds_frames_B": 0.0009, "method": "streamed passes (Q-6-5); no event list is built"}}
exit 1
```
