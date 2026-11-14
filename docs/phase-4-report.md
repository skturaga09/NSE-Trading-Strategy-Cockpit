# Phase 4 report: futures positioning intelligence (positioning hypotheses)

Date: built 2026-11-06 (IST). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, phase-0/1/2/3 reports.

> Positioning hypotheses are inferred from public price, volume and open-interest data only. They do not identify
> who traded and are not evidence of institutional buying or selling. (`engine.positioning.DISCLAIMER`)

## 0. Owner decisions taken during this phase (2026-11-06)

| Question | Decision |
|---|---|
| Build plan: Phase 4 needs ≥5 recorded sessions; 1 exists (2026-11-06, outage 09:03–11:26) | **Build now**, report on 2026-11-06 after EOD, labelled 1 partial session; re-run the same command at ≥5 sessions |
| "Phase 3 snapshots only" vs significance needing each contract's history | **Phase 3 history store** (history.sqlite, Kite minute candles, `HISTORICAL_API`) for distributions, beta, RVOL baseline; snapshots for today |
| Thresholds (no verified source) | **As proposed**, all in `config/engine/v5.yaml` → `positioning` |
| Phase 0 labels (PRICE_UP_OI_UP…) vs phase text (LONG_BUILDUP…) | **Phase 4 text wins**; deviation recorded in architecture §11 |
| Combined-OI windows were gated by the slowest component (Dec/Jan p90 15–100 min ⇒ almost every window disabled) | **Measure the combined series**: `engine.oi_cadence` writes `COMBINED:<underlying>` rows |
| Combined OI DEGRADED whenever a far month's OI is unchanged ≥ 300 s | **Keep strict** (revisit with Q-QUAL-1) |

Chosen and flagged, not asked: an OI step during a recorder gap is unchecked, not "invalid"; liquidity that cannot be
measured (gap) suppresses with INSUFFICIENT_DATA, not ILLIQUID_FUTURE; a STALE EMPTY minute counts as 0 trades;
ROLLOVER_WINDOW suppresses the near-month view and only flags the combined views (Q-POS-4); `cadence` per series =
max over recorded dates; distributions are fixed for the day (history only, no same-day lookahead); events only are stored
(Q-POS-5); the global config default stays v4 (Q-CFG-2).

## 1. Files

| File | Purpose |
|---|---|
| `engine/positioning.py` | features, history profile, classification (3 views), noise filters, events, append-only store, report, CLI |
| `engine/oi_cadence.py` | + `COMBINED:<underlying>` rows (`_stats` shared; `cadence(day_dir, cfg, underlying_of)`) |
| `config/engine/v5.yaml` | v4 unchanged + `positioning` (25 required keys, loader fails on a missing one) |
| `tests/engine_tests/test_positioning.py` | 17 tests, synthetic 20-session history + scripted days |
| `tests/engine_tests/test_storage.py` | + combined-cadence assertion |
| docs | architecture §11, open-questions (Q-CFG-2, Q-POS-1..6), this report, `phase-4-evidence/` |

## 2. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| In | Pure functions over snapshot objects + config | DONE (+ history store, owner) | `evaluate_day` takes data, master, `history(token)`, cadence, cfg, day; no clock/disk/network |
| F1 | Price change 1/3/5/15/30 min, futures and spot | DONE | features `fut_/spot_/index_price_chg_{w}m_pct`; `test_each_quadrant` |
| F2 | OI change 5/15/30 min + vs previous session close, combined default, near-month secondary; windows shorter than the measured cadence disabled | DONE | `combined_/near_oi_chg_{w}m_pct`, `*_prev_close_pct`; `test_window_shorter_than_measured_cadence_is_disabled` |
| F3 | RVOL vs same-time baseline | DONE (Q-HIST-6) | `rvol_15m` (near future, last 15 min vs same-minute median of 20 sessions) |
| F4 | Volume vs OI-change ratio | DONE | `volume_oi_ratio_15m` = all futures' volume / abs(combined OI change) |
| F5 | VWAP deviation in ATR, ATR-normalized move, momentum | DONE | `vwap_dev_atr`, `atr_move_15m`, `momentum_15m_roc_pct`, `atr` (14 × 5-min, history-seeded) |
| F6 | Basis, its change, abnormal flag | DONE | `basis`, `basis_chg_15m`, `basis_z`; flag `ABNORMAL_BASIS` at abs(z) > 3 |
| F7 | OI-change percentile vs own rolling distribution | DONE | `*_oi_pctile_{w}m`, min sample 100 ⇒ else LOW_SAMPLE (`test_low_sample_history`) |
| F8 | Rolling beta vs NIFTY futures, residual per window; optional sector residual | DONE / sector **skipped** (Q-POS-3) | `beta`, `residual_chg_{w}m_pct`; `test_move_with_beta_times_index_is_index_driven` |
| DQ | Each feature has its own DataQuality; UNAVAILABLE if any input not OK | DONE | `Feature.quality` (source, missing inputs, OI age, status); `test_stale_oi_suppressed` checks it |
| C1 | 4 quadrants on residual price × combined OI, significant | DONE | `test_each_quadrant` |
| C2 | NEUTRAL_OR_MIXED: not significant, conflicting windows, insufficient data | DONE | `test_mixed_windows_are_neutral`, `test_oi_up_with_flat_price_is_not_a_buildup` |
| C3 | Percentiles vs own history, fixed % floor, min sample ⇒ LOW_SAMPLE | DONE | `_sig`, `_pctile`; `test_low_sample_history` |
| C4 | Raw classification too, residual primary | DONE | `PositioningState.raw` / `.primary`; NIFTY itself: raw is primary (`test_index_itself_uses_raw_price`) |
| N | Filters OI_STALE, OI_JUMP_INVALID, ROLLOVER_WINDOW, EXPIRY_DAY, ILLIQUID_FUTURE, INDEX_DRIVEN, LOW_SAMPLE, each named | DONE | `test_stale_oi_suppressed`, `test_implausible_oi_jump`, `test_rollover_…`, `test_expiry_day_suppresses_every_view`, `test_illiquid_future`, `test_move_with_beta_…`, `test_low_sample_history` |
| E | Events after N confirmations with every listed field; append-only, state changes = new rows | DONE | `test_confirmation_evidence_and_invalidation`, `test_replay_gives_the_same_events_every_run` (second write adds 0 rows) |
| L | "positioning hypothesis" wording; no "institution" except the disclaimer | DONE | `test_no_output_text_says_institution_except_the_disclaimer` (source, states, events, report) |
| AT1–7 | Acceptance tests | DONE | §6 |
| R | Report on all recorded sessions | see §5 | 1 recorded session (2026-11-05 has a master only, no recording) |

## 3. Facts used

No new external facts. F-NSE-1/5 (F&O session, holidays → previous session), F-HIST-2/3 (history rows, OI),
F-WS-5/6 (OI only in full mode). Measured: OI cadence by expiry (§5).

## 4. Open questions

Q-CFG-2 (global default v5?), **Q-POS-1** (primary mostly OI_STALE, with Q-QUAL-1), **Q-POS-2** (history store not refreshed
daily), Q-POS-3 (sector), Q-POS-4 (rollover reading), Q-POS-5 (states not persisted / not live), Q-POS-6 = Q-HIST-6.

## 5. Real data: 2026-11-06

PENDING EOD.

## 6. Raw test output

PENDING EOD.

## 7. Limitations

- One recorded session, with a 2 h 23 min outage. Nothing here says anything about an edge, and nothing should be read that way.
- History covers 2026-09-29 → 2026-11-05. Jan-2027 futures start 2026-10-28, so combined-OI distributions use only minutes where every current component exists (about 7 sessions).
- The previous-session close comes from the history store's last minute, not from the exchange's closing OI.
- ATR mixes history 5-minute bars (built from Kite minutes) with today's tick-built 5-minute candles until 14 of today's are available.
- An OI step that cannot be measured (input not OK) is not checked for a jump.
- ~90 s per day on this Mac (97 underlyings); batch only, not wired into the recorder.
