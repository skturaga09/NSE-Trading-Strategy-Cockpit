# Phase 12 report: event-driven backtesting, timing studies, walk-forward validation

Date: built 2026-11-07 (Saturday, IST; market closed). Branch `stack/4-setup-radar`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, decisions.md, questions-ledger.md, phase-0…11 reports.
Advisory and paper-trading only: nothing places, modifies or cancels an order. `test_no_order_methods_in_repo_code` and
`test_engine_never_uses_kiteconnect_rest_class` still pass, and they now scan the new files too. **Every result below is SIMULATED / HYPOTHETICAL.**

## 0. Headline

- **Recorded sessions: 0 GOOD, so the stage is BELOW_SYSTEM_CHECK. No strategy conclusion is allowed.**
  - The only recorded session is 2026-11-06. Its coverage is 65.8%. There is also a 30-minute uncovered stretch at the open: a restart gap from 09:03:08 to 11:26:38 after the Mac slept.
  - SYSTEM_CHECK needs 20 GOOD sessions. TENTATIVE needs 60. FINAL needs 125, which is about May 2027 at the earliest.
  - **Every Phase 8 family (A–F) is INSUFFICIENT_SAMPLE.**
- **HISTORICAL_CANDLES ran now, as the phase allows.** It uses the NIFTY 50 index at 5m and 15m: 1,375 usable days from 2021-01-01 to 2026-07-31.
  - It is a price-path study only. There are no fills and no costs (owner decision D-55).
  - On that basis:
    - **Index sweeps have no edge.** SWEEP_HIGH: −0.19 R, 95% CI [−0.30, −0.08]. SWEEP_LOW: −0.00 R [−0.12, +0.13].
    - **ZONE_DEFENDED** is +0.21 R, but the CI [−0.25, +0.76] spans zero, on only 133 entries.
    - **Breakouts almost never form on index 5m/15m** under the live thresholds (33 + 23 setups in 5.5 years).
  - Costs would push every one of these lower.
  - This matches the earlier lab finding that the sweep failed out of sample (memory note, 2026-10-22).
- **Edge half-life: no value is measured.**
  - Recorded data: no entries.
  - Historical data: every setup type is either NO_POSITIVE_EDGE (age-0 expectancy ≤ 0) or INSUFFICIENT_SAMPLE.
  - So the Phase 6 AGE_VS_HALF_LIFE rule (D-56) is built but stays disabled. Live outputs are unchanged.
- **The look-ahead guard passes.** A sentinel bar placed in the future leaves every decision known before it unchanged. The same sentinel placed in the past does change them, which proves the test can catch leakage.

## 1. Questions and decisions

**Reminder (rule Q5): 14 earlier BLOCKING rows are still OPEN.** They are Q-0-2, Q-0-3, Q-0-6, Q-0-7, Q-0-8, Q-1-4, Q-3-1, Q-6-2, Q-7-4, Q-7-5, Q-7-6, Q-7-8, Q-7-9 and Q-7-10. In addition, 127 earlier rows are ASSUMED. Three of the open rows hit this phase:
- **Q-7-4: futures margin is counted at full contract value**, so live risk rejects nearly every future. Recorded backtests will show close to zero trades until this is answered.
- **Q-7-5: every risk value is still only PROPOSED.**
- **Q-3-1: session hours change on 2026-12-07.** The GOOD-session window uses the single configured `sessions.fno` close, 15:40.

Asked once at the start of this phase and answered by you on 2026-11-07:
- **Q-12-1 (BLOCKING): proceed** with the 14 rows still open (D-54).
- **Q-12-2 (BLOCKING): option (a).** HISTORICAL_CANDLES is a price-path event study on index candles only: no fills, no rupees, VWAP and OI families NOT_REPRESENTABLE, and stocks excluded because of survivorship (D-55).
- **Q-12-3 (BLOCKING): option (a).** The additive Phase 6 half-life change (D-56).
- **Q-12-4 … Q-12-13: accepted as assumed** (D-57). They cover:
  - no KEEP without go-live criteria;
  - minimum trades 100;
  - the GOOD definition;
  - the holdout rule;
  - walk-forward windows and grids;
  - day-clustered bootstrap;
  - precision vs win rate;
  - VIX UNAVAILABLE;
  - file layout;
  - the OI-delay diagnostic.

Interpretations found while building (ASSUMED, each a ledger row; rule 16, conservative reading):
- **Q-12-14:** no score ranking exists in the live paper path. Simultaneous signals are resolved by `run_day`'s (as_of, recommendation_id) order plus the Phase 7 risk rules, and the backtest inherits exactly that.
- **Q-12-15:** historical data rules:
  - the index session is 09:15–15:30;
  - holidays come only from config, so the day after a 2021–2025 holiday gets no PDH/PDL/PDC;
  - a day missing any bar is excluded (8 days);
  - 1m/3m-dependent items are UNAVAILABLE;
  - levels are relabelled `LAB_CSV`.
- **Q-12-16:** the outcome model:
  - the stop triggers on touch;
  - a gap-through exits at the open;
  - a bar touching both stop and target counts as the stop;
  - the position squares off at 15:10;
  - MULTI_SESSION means the target was hit on a later session only.
- **Q-12-17:** half-life method, file versioning, and which entries Phase 6 may use.
- **Q-12-18:** segment definitions.
- **Q-12-19:** Parquet rebuild for compacted days, a separate backtest ledger, and the live Phase 8 config (v14).
- **Q-12-20:** the recorded walk-forward score floor is a post-filter on trades.
- **Q-12-21:** verdict rules. HISTORICAL never gives a verdict.
- **Q-12-22:** precision is counted once per event, at confirmation.

## 2. What was built (files)

New:
| File | Content |
|---|---|
| `engine/backtest.py` | Pure, 537 lines. Contents:<ul><li>session quality, stages, split, holdout gate</li><li>price path (`walk`, gap-through), `r_multiple`, `excursions`, `segment`, `outcome`</li><li>`age_entries` (half-life input), `class_entries` (study 3)</li><li>`metrics` / `bootstrap` (day-clustered), `verdict`, `half_life`</li><li>segments (`tod_bucket`, `regime`, `expiry_label`, `group`)</li><li>walk-forward (`windows`, `month_windows`, `walk_forward`)</li><li>`oi_views` (OI known at decision vs OI eventually reported)</li><li>`historical_day`: Phase 5 `Detector` + Phase 6 `setups_from_structure` / `track`, unchanged, on lab index bars</li></ul> |
| `engine/backtest_report.py` | Edge CLI `python3 -m engine.backtest_report [all\|historical\|recorded] [--no-walk-forward] [--pipeline-check DATE]`. Contents:<ul><li>lab loader with sha256 check</li><li>historical runner</li><li>recorded runner: session quality from the recorder's own events/gaps; the unchanged Phase 9 `ledger.run_day` into a per-run backtest ledger; Parquet → buffer rebuild with the Phase 1 replay readers; holdout read log</li><li>`trade_rows`: Phase 7 costs in force on the trade date, slippage, net R</li><li>recorded event study, OI-delay diagnostic, versioned half-life writer, markdown renderer</li></ul> |
| `config/engine/v16.yaml` | v15 + `opportunity.half_life_file` / `half_life_multiple` + `backtest.*`. The holdout rule was fixed here before any recorded data was read |
| `config/engine/half_life/v1.json` | The half-life file Phase 6 reads. It has no MEASURED entry, so the rule is disabled |
| `tests/engine_tests/test_backtest.py` | 38 tests: acceptance criteria, the 15 required scenarios, the look-ahead guard |
| `tests/engine_tests/golden/nifty_index_2021-01_{5m,15m}.csv` | Fixture: 2021-01-01 … 01-15 rows copied from the read-only lab files |
| `docs/phase-12-evidence/` | `backtest-report.md` (every table), `results.json`, `run-log.txt`, `full-test-run.txt`, `phase12-tests-verbose.txt`, `preexisting-eod-failure-check.txt` |

Changed:
| File | Change |
|---|---|
| `engine/opportunity.py` | Additive (D-56):<ul><li>`Evaluation.age_vs_half_life` is now `float \| Unavailable`</li><li>`opportunity_age(..., *, half_life=None)` and `track(..., *, half_life=None)`</li><li>new `half_lives(cfg)`</li><li>`run_setups` passes each setup type's half-life</li><li>new rule `AGE_VS_HALF_LIFE`</li></ul>Configs before v16 have no file key, so their outputs are unchanged (all 14 Phase 6 tests pass unchanged) |
| docs | decisions D-54…57, ledger Q-12-1…22, architecture §19 |

## 3. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| Data-1 | Intraday OI, depth and option logic are tested only on recorded sessions | DONE: only the RECORDED path can reach them; HISTORICAL lists them NOT_REPRESENTABLE | `test_event_rows_three_anchors_and_not_representable_families`; report "Not representable" line |
| Data-2 | State the historical granularity; every table names its dataset | DONE: §4.1; every table header | `test_every_table_is_titled_with_its_dataset_stage_and_good_sessions` |
| Data-3 | Universe per date from stored snapshots; survivorship warning | PARTIAL:<ul><li>RECORDED uses each day's own stored master and stores</li><li>HISTORICAL is restricted to the NIFTY index because no historical constituent lists exist (survivorship: stocks excluded, D-55)</li></ul> | §4.1 |
| Eng-1 | Phase 1 replay engine; the same pure strategy, selector, risk and paper-broker code as live | DONE:<ul><li>`ledger.run_day` is unchanged</li><li>compacted days are rebuilt with the Phase 1 replay readers</li><li>historical uses the Phase 5/6 code unchanged</li></ul>On real data the path ran (PIPELINE_CHECK 2026-11-06), but there were 0 ENTRY_ELIGIBLE recommendations, so no real trade went through it | `test_buffer_rebuilt_from_parquet_equals_the_original`, scenario tests, run log |
| Eng-2 | Fills: executable side, slippage, partial fills; gap-through-stop at the first price beyond the stop | DONE:<ul><li>Phase 9 `paper_fill` walks the book; partial fills are flagged</li><li>the price path exits at a gap bar's open</li></ul> | `test_stop_gap_paper_exit_fills_beyond_the_stop_and_costs_are_date_effective` (paper exit at the bid 98495 vs the 99000 stop), `test_gap_through_stop_exits_at_the_first_price_beyond_not_at_the_stop`; Phase 9 `test_partial_fill_when_visible_depth_is_short` |
| Eng-3 | Full Phase 7 costs at the rates in force on each date | DONE. A date with no verified rate is flagged `cost_unverified` | same stop-gap test (the 2026-11-05 trade is unverified) |
| Eng-4 | Simultaneous signals resolved by live ranking and risk | DONE as built live (Q-12-14) | `test_simultaneous_signals_resolved_by_the_live_risk_rules` |
| St-1 | Event study: MFE/MAE at 1/3/5/10/15/30/60 min from detection, confirmation and first executable; pre-signal move share; time to target / invalidation; segments from the data | DONE:<ul><li>HISTORICAL: real tables H2/H3, where 1 and 3 min are below the 5m resolution</li><li>RECORDED: built, run only in the PIPELINE_CHECK</li></ul> | `test_excursions_below_resolution_are_unavailable`, `test_segments_come_from_each_events_measured_exit`, tables H2/H3 |
| St-2 | Edge half-life per family → a versioned file Phase 6 reads to enable age_vs_half_life | DONE:<ul><li>`config/engine/half_life/v1.json` exists</li><li>Phase 6 reads it</li><li>no MEASURED value yet, so the rule is disabled</li></ul> | `test_half_life_measured_and_conservative_statuses`, `test_rule_disabled_without_value_and_fails_timely_when_older_than_half_life`, `test_phase6_reads_only_recorded_measured_tentative_entries`, `test_half_life_file_is_versioned_and_partial_runs_carry_other_datasets` |
| St-3 | TIMELY vs VALID_BUT_LATE vs RETEST expectancy | DONE (HISTORICAL table H5); RECORDED is waiting for sessions | table H5 |
| St-4 | OI publication delay: OI at decision time vs OI as eventually reported (diagnostic) | PARTIAL:<ul><li>The decision-level diagnostic is built and was run in the PIPELINE_CHECK: 20 positioning decisions, OI differs in 1, median difference 0.16%.</li><li>A full Phase 4–8 re-run on eventually reported OI was **not built**.</li></ul> | `test_oi_publication_delay_decision_uses_only_received_oi`; PIPELINE_CHECK |
| St-5 | Segments: regime (NIFTY structure), VIX bucket, time of day, expiry proximity, instrument, score band | PARTIAL:<ul><li>HISTORICAL: regime, time of day, timeframe</li><li>RECORDED: tables for underlying, time of day, score band, instrument and expiry are built but empty (0 GOOD sessions)</li><li>VIX is UNAVAILABLE everywhere (Q-12-11)</li></ul> | tables H6, R7 |
| Val-1 | GOOD sessions (coverage ≥ 95%, no long gap in the first/last 30 min); good vs excluded with reasons; stage chosen automatically; every table header shows the stage and good-session count | DONE | `Sessions.*`, `test_stages_from_good_session_count`, table R1, header test |
| Val-2 | Development / validation / final holdout. The holdout (last 30 of the first 125 good sessions) is written to config before analysis, never read before FINAL, read exactly once and logged | DONE | `test_holdout_is_the_last_30_of_the_first_125_good_sessions`, `test_holdout_read_only_at_final_once_and_logged`, `test_holdout_rule_is_in_versioned_config` |
| Val-3 | 5-year historical candle backtest runs now, in its own section labelled HISTORICAL_CANDLES | DONE | §4, run log |
| Val-4 | Walk-forward: tune on rolling train windows, evaluate on the following window only | DONE:<ul><li>HISTORICAL: 18 windows (table H7)</li><li>RECORDED: wired, NOT_RUN (0 development sessions)</li></ul> | `test_walk_forward_chooses_on_train_and_scores_on_test_only` |
| Val-5 | Per family: trades, precision, win rate, average win/loss, expectancy in R and rupees after costs, profit factor, max drawdown, slippage share, bootstrap CIs; INSUFFICIENT_SAMPLE flag | DONE for RECORDED trades (INR and net R tables, slippage share). HISTORICAL has R only; rupees and slippage are NOT_REPRESENTABLE (no fills) | `test_figures_and_day_clustered_bootstrap_are_deterministic`, `test_costs_and_slippage_share` |
| Val-6 | Every table titled SIMULATED / HYPOTHETICAL | DONE: 21 headers in the evidence report | header test |
| Sc | Required scenario tests (15) | DONE (§5) | `Scenarios.*`, `Sessions.*`, `PricePath.*` |
| LA | Look-ahead guard: a future sentinel observation must change nothing | DONE, and shown to be sensitive | `test_look_ahead_guard_sentinel_future_bar_changes_nothing_known_before_it` |
| Rep | This report: tables, the half-life file, a plain-language verdict per family | DONE | §4, §6, Appendix |

## 4. Results

### 4.1 Datasets and granularity

| dataset | what it is | granularity | can test | cannot test |
|---|---|---|---|---|
| **HISTORICAL_CANDLES** | Lab CSVs `nifty50_5m_2021_2026.csv` / `nifty50_15m_2021_2026.csv`, sha256 checked against config (`926a901a…` / `dfc7cf74…`). 1,383 days; 1,375 usable; 8 excluded for an incomplete bar count (Muhurat / special sessions) | **5-minute and 15-minute** NIFTY 50 **index** OHLC. No volume, no OI | Phase 5 structure and sweeps, Phase 6 setups and Opportunity Age (at 5m closes), price paths | <ul><li>VWAP (no volume)</li><li>futures OI: Kite has intraday futures history only from a contract's listing (F-HIST-7), and its continuous series is daily only (F-HIST-4)</li><li>options, depth, fills, costs, rupees</li><li>Phase 8 families (A–D need OI; E/F need rejection RVOL)</li><li>stocks (survivorship)</li></ul> |
| **RECORDED** | Recorder sessions under `data/engine/<date>/` | Ticks and 5-level depth; 1m candles | Everything, through the live code | Nothing yet: 0 GOOD sessions |

Kite historical candles (F-HIST-1…8) are **not** the source here. Their intraday history for futures does not go back 5 years.

### 4.2 Recorded sessions

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

| session | GOOD | coverage | max edge gap s | reasons |
|---|---|---|---|---|
| 2026-11-06 | False | 65.8% | 1800.0 | COVERAGE 65.8% < 95%; EDGE_GAP 1800 s > 30 s in the first/last 30 min |

- Split: development 0, holdout 0. The holdout read was refused with `HOLDOUT_EMPTY`.
- Trades: none. Walk-forward: NOT_RUN.
- The half-life entries for RECORDED are empty.

**PIPELINE_CHECK 2026-11-06.** This run used the EXCLUDED session through the recorded code path. It is not part of any result.
- `run_day`: 0 eligible, 0 opened. All 86 Phase 8 recommendations are REJECTED, as in Phase 8.
- Event study: 2,964 event rows across 988 setups × 3 anchors, including Phase 4 positioning setups (LONG_BUILDUP 13, SHORT_BUILDUP 4, SHORT_COVERING 3).
- 783 age entries and 861 class entries.
- OI-delay diagnostic: of 20 positioning decisions, 1 had a different OI as eventually reported (median absolute difference 0.16%).
- The table is in the Appendix.

### 4.3 HISTORICAL_CANDLES: families (entry at FIRST_EXECUTABLE = the first TIMELY evaluation)

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED | 1 | 0.348 | 0.000 | — | -1.000 | -1.000 | 0.000 | 1.000 | **INSUFFICIENT_SAMPLE** |
| BREAKOUT_ACCEPTED | 0 | 0.303 | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| SWEEP_HIGH | 2361 | 0.464 | 0.200 | 3.316 | -1.072 | -0.193 [-0.302, -0.078] | 0.775 [0.661, 0.906] | 509.765 | yes |
| SWEEP_LOW | 2029 | 0.507 | 0.237 | 3.229 | -1.005 | -0.003 [-0.122, 0.126] | 0.996 [0.844, 1.167] | 119.266 | yes |
| ZONE_DEFENDED | 133 | 0.626 | 0.241 | 4.097 | -1.026 | 0.206 [-0.248, 0.755] | 1.265 [0.708, 2.065] | 22.433 | yes |

How to read this table:
- **Precision** counts each event once, at confirmation: did the price path reach the target before the stop, by 15:10 (Q-12-22)?
- **Win rate** is over the FIRST_EXECUTABLE entries. These come later than confirmation, so the two numbers differ.
- **Sweep stops sit at the wick extreme**, which makes them tight. So the average loss is about −1 R (gap-throughs make it slightly worse) and the average win is about +3.3 R.
- **Max drawdown** is the sum of R over 5.5 years, with no position sizing.
- **Setups by type** (5m + 15m): SWEEP_HIGH 6,115; SWEEP_LOW 6,316; ZONE_DEFENDED 982; BREAKOUT_ACCEPTED 33; BREAKDOWN_ACCEPTED 23.

### 4.4 Event study, half-life, Opportunity Age, segments, walk-forward (HISTORICAL_CANDLES)

The full tables are in the Appendix (H2–H7). The main readings:

- **Price moves before the signal (H2).** The "moved before signal" share is the share of events where price moved in the trade direction before first detection.
  - Breakouts and breakdowns: 96–100%. They are late by construction: the median pre-signal move is +1.5 ATR.
  - Sweeps: 8–9%. They are counter-moves: the median pre-signal move is −0.9 ATR.
  - Zones: 34%.
- **Segments (H2), SWEEP_HIGH at confirmation (n = 6,115):**
  - IMMEDIATE_1_5: 2,055
  - CONTINUATION_5_30: 682
  - MID_30_90: 89
  - MULTI_SESSION: 34
  - FAILED: 2,759
  - INCONCLUSIVE: 496

  At FIRST_EXECUTABLE, FAILED dominates: 1,835 of 2,515. The edge that exists at confirmation is mostly gone by the time an entry passes the Phase 6 timeliness rules.
- **Half-life (H4).** No setup type has a positive fresh-entry expectancy at age 0:
  - SWEEP_HIGH −0.112 R (n = 5,627)
  - SWEEP_LOW −0.066 R (n = 5,658)
  - ZONE_DEFENDED −0.040 R (n = 860)

  So each is **NO_POSITIVE_EDGE**: there is no edge to decay. Breakouts and breakdowns are INSUFFICIENT_SAMPLE (19 and 21 fresh entries).
- **Opportunity Age validation (H5).** VALID_BUT_LATE entries are negative for every type with n ≥ 100, and their CIs exclude 0:
  - SWEEP_HIGH −0.121 R
  - SWEEP_LOW −0.097 R
  - ZONE_DEFENDED −0.055 R

  RETEST is worse than TIMELY for sweeps (−0.275 / −0.216 R). TIMELY is best for each type, but positive only for ZONE_DEFENDED (+0.198 R, CI spans 0).
- **Segments (H6).**
  - **Timeframe:** 15m entries are worse (−0.284 R, CI excludes 0) than 5m entries (−0.076 R).
  - **Time of day:** 13:30–14:30 is the worst bucket (−0.368 R, CI excludes 0). 09:15–10:15 is the only positive bucket (+0.050 R, CI spans 0).
  - **Regime:** UNAVAILABLE for 3,623 of 4,524 entries, because the 15m TREND detector restarts each day.
  - **VIX and expiry:** UNAVAILABLE.
- **Walk-forward (H7)**, 18 windows of 12 months train / 3 months test:
  - SWEEP_HIGH out-of-sample: −0.202 R [−0.327, −0.066]
  - SWEEP_LOW out-of-sample: +0.001 R [−0.134, +0.154]
  - The grid (acceptance closes × consolidation width) does not affect sweeps: all four values give identical sweep rows, so the first grid value wins ties.
  - Breakout and zone families never have 100 trades in a train window, so they get no choice.

## 5. Required scenario tests

| scenario | test (all in `tests/engine_tests/test_backtest.py`) |
|---|---|
| long buildup, short buildup, covering, unwinding | `test_long_short_buildup_covering_unwinding_become_backtest_events`: the Phase 4 fixture day → Phase 6 positioning setups → backtest event rows, with family and direction per quadrant |
| OI/price contradiction | `test_oi_price_contradiction_produces_no_event` (OI up, price flat ⇒ no setup, no event) |
| OI publication delay | `test_oi_publication_delay_decision_uses_only_received_oi` |
| sweeps, false breakouts | `test_sweeps_and_false_breakouts`:<ul><li>lab-fixture sweeps take their stop from the wick extreme</li><li>BREAKOUT_FAILED never becomes a setup</li><li>a reversing breakout's segment is FAILED</li></ul> |
| expiry and rollover | `test_expiry_and_rollover_labels_and_expiry_day_block` (EXPIRY_DAY / ROLLOVER_WINDOW / NORMAL; risk EXPIRY_DAY rejects) |
| illiquid options | `test_illiquid_option_is_never_traded` |
| data interruptions | `test_data_interruption_excludes_the_session_and_breaks_the_path`, `test_target_end_and_data_interruption` |
| stop gaps | `test_stop_gap_paper_exit_fills_beyond_the_stop_and_costs_are_date_effective`, `test_gap_through_stop_exits_at_the_first_price_beyond_not_at_the_stop` |
| costs | the same stop-gap test (date-effective; unverified before 2026-11-06), `test_costs_and_slippage_share` |
| simultaneous signals | `test_simultaneous_signals_resolved_by_the_live_risk_rules` |
| position sizing | `test_position_sizing_whole_lots_within_the_risk_budget` |
| daily loss limit | `test_daily_loss_limit_blocks_the_next_signal_in_the_backtest_ledger` |

## 6. Plain-language verdicts per family

The only verdict-bearing data is RECORDED, and it has 0 GOOD sessions (stage BELOW_SYSTEM_CHECK). So **every family is INSUFFICIENT_SAMPLE**. The historical index study is context only: it uses an index proxy and has no fills and no costs (Q-12-21).

| family | verdict | why, in plain words |
|---|---|---|
| A LONG_BUILDUP_BREAKOUT | **INSUFFICIENT_SAMPLE** | No recorded trades. It needs futures OI, which the 5-year data does not have. Index breakouts are also rare under the live thresholds (33 in 5.5 years) |
| B SHORT_BUILDUP_BREAKDOWN | **INSUFFICIENT_SAMPLE** | Same as A (23 index breakdowns) |
| C SHORT_COVERING_MOMENTUM | **INSUFFICIENT_SAMPLE** | Same as A |
| D LONG_UNWINDING_CONTINUATION | **INSUFFICIENT_SAMPLE** | Same as B |
| E BULLISH_SWEEP_REVERSAL | **INSUFFICIENT_SAMPLE** | No recorded trades. For context, the underlying index SWEEP_LOW setup shows no gross edge over 5.5 years (−0.003 R, CI [−0.12, +0.13]; out-of-sample +0.001 R) before any costs. Expect REVISE or DROP unless the RVOL and structure filters change that on recorded data |
| F BEARISH_SWEEP_REVERSAL | **INSUFFICIENT_SAMPLE** | No recorded trades. For context, index SWEEP_HIGH loses before costs (−0.193 R, CI [−0.30, −0.08]; out-of-sample −0.202 R). This is the strongest warning in this report |

KEEP is impossible until go-live criteria exist in docs/decisions.md (Q-12-4).

## 7. Verified facts used

- F-HIST-4 (continuous data is day candles only): https://kite.trade/docs/connect/v3/historical/ (2026-11-05)
- F-HIST-7 (intraday history starts at a contract's listing): measured, measured-kite.txt (2026-11-05)
- F-HIST-1/2 (intervals, record format): https://kite.trade/docs/connect/v3/historical/ (2026-11-05). Used only to state why Kite candles are not the 5-year source.
- F-COST-1…6 (charges, through the Phase 7 cost model): https://zerodha.com/charges/ ; https://zerodha.com/marketintel/bulletin/445377/revision-in-stt-securities-transaction-tax-from-1st-april-2026 (2026-11-06)
- F-NSE-1 (F&O close 15:40) through config `sessions.fno`. The cash session 09:15–15:30 is config `sessions.cash` (Phase 3).
- No new external fact was needed. Nothing new went into open-questions.md.

**API usage (guardrail 5).** No kiteconnect method or field is used in Phase 12. The new code reads only local files:
- SQLite and Parquet through the existing `engine.store` / `engine.replay` readers;
- `pyarrow.parquet.ParquetFile(...).metadata` row-group statistics, which pyarrow 26.0.1 already uses in compaction;
- the lab CSVs.

## 8. Test output (raw)

Engine (`python3 -m unittest discover -s tests/engine_tests -t .`, 2026-11-07, a Saturday). The full raw output is in `phase-12-evidence/full-test-run.txt`. Below is the failure block and the summary, verbatim:
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
Ran 275 tests in 43.285s

FAILED (failures=1)
```
**274 of 275 pass.** The one failure is the pre-existing Q-9-24 weekend-clock test: `engine/eod.py` reads the wall clock. With the clock pinned to 2026-11-06 16:00 IST (the fixture's day) it passes. `phase-12-evidence/preexisting-eod-failure-check.txt` ends with:
```
Ran 1 test in 0.353s

OK
weekday-pinned result (clock 2026-11-06 16:00 IST): PASS
```
Phase 12 alone (`python3 -m unittest tests.engine_tests.test_backtest`): `Ran 38 tests … OK`. The per-test list is in `phase12-tests-verbose.txt`.

Frontend (untouched this phase): `npx tsc --noEmit -p fo-engine/tsconfig.json` exit 0; `npx vitest run -c fo-engine/vitest.config.ts`: `Test Files 2 passed (2)`, `Tests 27 passed (27)`.

Real-data run (`python3 -m engine.backtest_report all --pipeline-check 2026-11-06`, `phase-12-evidence/run-log.txt`):
```
{"run_dir": "/Users/turagasanthoshkumar/Clade-NSE-Skills/data/engine/backtest/20261107T173514", "runtime_s": 167.3, "half_life_file": "config/engine/half_life/v1.json", "recorded_stage": "BELOW_SYSTEM_CHECK"}
python3 -m engine.backtest_report all --pipeline-check 2026-11-06  164.17s user 1.93s system 98% cpu 2:47.94 total
```

## 9. Known limitations

- **No GOOD recorded session yet.** Every recorded study, walk-forward and verdict is built and fixture-tested but has produced no real result. The earliest SYSTEM_CHECK is 20 good sessions away. Mac sleep (Q-0-3) directly delays this.
- **The recorded path has never opened a real trade.** On 2026-11-06 there were 0 ENTRY_ELIGIBLE recommendations, because full-notional futures margin rejects nearly every future (Q-7-4) and options are blocked by the IV gate (Q-11-7). Until those change, recorded backtests will show about 0 trades.
- **The historical study is gross price-path R on the index.** That means no basis, no spread, no slippage, no costs and no partial fills. Real futures results would be lower.
- **Historical coverage gaps:**
  - opening range, the 3m timeframe and 1/3-minute horizons are unavailable;
  - the day after a 2021–2025 holiday has no previous-day levels;
  - regime is UNAVAILABLE early in each session.
- **The OI-delay study is decision-level only.** A full re-run of Phase 4–8 on eventually reported OI was not built.
- **The half-life is gross.** It is keyed by Phase 6 setup type, not by Phase 8 family, because Phase 6 does not know the family.
- **The recorded walk-forward score floor is a post-filter**, so filtered-out trades still occupied position slots (Q-12-20).
- **No live score ranking exists**, so simultaneous signals are taken in recommendation order, then risk rules apply (Q-12-14).
- **Reading back from an `s3://` retention target is not supported.** The current target is the Drive mount path, which works.
- **Earlier run directories stay in `data/engine/backtest/`.** Four of them, 20261107T171600 … 172036, were produced before the precision and MULTI_SESSION fixes, so their numbers are superseded. The half-life file's `generated_by` names the first run; its entries are identical to the final run's, so no new version was written.

## 10. Assumptions

Every assumption is a ledger row: Q-12-4 … Q-12-13 (accepted, D-57) and Q-12-14 … Q-12-22 (ASSUMED). They stand unless you answer, and they will be reported again in Phase 15.

## 11. Owner actions

None are required for this phase. Optional:
1. Keep the Mac awake through market hours. Each GOOD session moves the recorded studies toward SYSTEM_CHECK (20), TENTATIVE (60) and FINAL (125).
2. Write go-live criteria into docs/decisions.md before FINAL (Q-12-4).
3. Answering Q-7-4 (margin) is what lets futures trades appear in recorded backtests at all.

To re-run:
```bash
python3 -m engine.backtest_report all
```

## Appendix: every table of the final run

Verbatim from `docs/phase-12-evidence/backtest-report.md`.

### Phase 12 backtest run 2026-11-07T17:35:14.448276+05:30 (config v16)

#### HISTORICAL_CANDLES

HISTORICAL_CANDLES: NIFTY 50 index 5m/15m (lab CSV, sha256 verified), 1375 usable days 2021-01-01..2026-07-31, 8 excluded; price path only: no fills, no costs, gross R

Not representable: VWAP families (no volume); Phase 8 families A-D (no futures OI); Phase 8 families E/F (rejection RVOL needs volume); stocks (survivorship: no historical constituent lists); rupee expectancy, slippage share (no fills)

Setups by type: {'SWEEP_HIGH': 6115, 'SWEEP_LOW': 6316, 'ZONE_DEFENDED': 982, 'BREAKDOWN_ACCEPTED': 23, 'BREAKOUT_ACCEPTED': 33}. Excluded days: 8.

#### H1. Families, entry at FIRST_EXECUTABLE (first TIMELY evaluation), unit R

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED | 1 | 0.348 | 0.000 | — | -1.000 | -1.000 | 0.000 | 1.000 | **INSUFFICIENT_SAMPLE** |
| BREAKOUT_ACCEPTED | 0 | 0.303 | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| SWEEP_HIGH | 2361 | 0.464 | 0.200 | 3.316 | -1.072 | -0.193 [-0.302, -0.078] | 0.775 [0.661, 0.906] | 509.765 | yes |
| SWEEP_LOW | 2029 | 0.507 | 0.237 | 3.229 | -1.005 | -0.003 [-0.122, 0.126] | 0.996 [0.844, 1.167] | 119.266 | yes |
| ZONE_DEFENDED | 133 | 0.626 | 0.241 | 4.097 | -1.026 | 0.206 [-0.248, 0.755] | 1.265 [0.708, 2.065] | 22.433 | yes |

#### H2. Event study: segments, pre-signal move, time to exit

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family @ anchor | n | n anchor unavailable | IMMEDIATE_1_5 | CONTINUATION_5_30 | MID_30_90 | MULTI_SESSION | FAILED | INCONCLUSIVE | moved before signal | median pre-signal ATR | median min to target | median min to stop |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED @ FIRST_DETECTION | 23 | 0 | 5 | 2 | 1 | 4 | 7 | 4 | 0.957 | 1.459 | 7.5 | 25.0 |
| BREAKDOWN_ACCEPTED @ CONFIRMATION | 23 | 0 | 3 | 1 | 3 | 5 | 8 | 3 | 0.957 | 1.459 | 27.5 | 20.0 |
| BREAKDOWN_ACCEPTED @ FIRST_EXECUTABLE | 1 | 22 | 0 | 0 | 0 | 0 | 1 | 0 | 1.000 | 2.095 | — | 10.0 |
| BREAKOUT_ACCEPTED @ FIRST_DETECTION | 33 | 0 | 6 | 2 | 1 | 3 | 18 | 3 | 1.000 | 1.558 | 5.0 | 110.0 |
| BREAKOUT_ACCEPTED @ CONFIRMATION | 33 | 0 | 8 | 0 | 1 | 3 | 18 | 3 | 1.000 | 1.558 | 5.0 | 105.0 |
| BREAKOUT_ACCEPTED @ FIRST_EXECUTABLE | 0 | 33 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | — | — |
| SWEEP_HIGH @ FIRST_DETECTION | 6115 | 0 | 1619 | 730 | 76 | 7 | 3204 | 479 | 0.084 | -0.883 | 5.0 | 5.0 |
| SWEEP_HIGH @ CONFIRMATION | 6115 | 0 | 2055 | 682 | 89 | 7 | 2759 | 523 | 0.084 | -0.883 | 5.0 | 5.0 |
| SWEEP_HIGH @ FIRST_EXECUTABLE | 2515 | 3600 | 219 | 245 | 45 | 1 | 1835 | 170 | 0.061 | -0.872 | 10.0 | 5.0 |
| SWEEP_LOW @ FIRST_DETECTION | 6316 | 0 | 1757 | 826 | 102 | 14 | 3067 | 550 | 0.088 | -0.965 | 5.0 | 5.0 |
| SWEEP_LOW @ CONFIRMATION | 6316 | 0 | 2272 | 811 | 110 | 13 | 2507 | 603 | 0.088 | -0.965 | 5.0 | 5.0 |
| SWEEP_LOW @ FIRST_EXECUTABLE | 2179 | 4137 | 184 | 262 | 56 | 4 | 1515 | 158 | 0.065 | -0.919 | 10.0 | 5.0 |
| ZONE_DEFENDED @ FIRST_DETECTION | 982 | 0 | 392 | 286 | 54 | 11 | 171 | 68 | 0.335 | -0.635 | 5.0 | 10.0 |
| ZONE_DEFENDED @ CONFIRMATION | 982 | 0 | 429 | 141 | 39 | 7 | 241 | 125 | 0.335 | -0.635 | 5.0 | 10.0 |
| ZONE_DEFENDED @ FIRST_EXECUTABLE | 156 | 826 | 11 | 18 | 2 | 3 | 99 | 23 | 0.320 | -0.743 | 10.0 | 5.0 |

#### H3. Event study: median MFE / MAE in R (and ATR) per horizon after the anchor

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family @ anchor | 1 min | 3 min | 5 min | 10 min | 15 min | 30 min | 60 min |
|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.15 / 0.09 R (0.36 / 0.25 ATR) | 0.17 / 0.11 R (0.52 / 0.34 ATR) | 0.22 / 0.13 R (0.60 / 0.39 ATR) | 0.28 / 0.17 R (0.76 / 0.52 ATR) | 0.41 / 0.32 R (1.24 / 0.94 ATR) |
| BREAKDOWN_ACCEPTED @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.09 / 0.14 R (0.32 / 0.56 ATR) | 0.11 / 0.16 R (0.33 / 0.61 ATR) | 0.14 / 0.23 R (0.42 / 0.79 ATR) | 0.18 / 0.27 R (0.55 / 0.94 ATR) | 0.31 / 0.29 R (0.87 / 1.01 ATR) |
| BREAKDOWN_ACCEPTED @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.05 / 0.77 R (0.04 / 0.60 ATR) | 0.05 / 1.10 R (0.04 / 0.85 ATR) | 0.05 / 1.42 R (0.04 / 1.10 ATR) | 1.40 / 1.42 R (1.09 / 1.10 ATR) | 1.62 / 1.42 R (1.26 / 1.10 ATR) |
| BREAKOUT_ACCEPTED @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.12 / 0.08 R (0.44 / 0.22 ATR) | 0.15 / 0.11 R (0.61 / 0.36 ATR) | 0.22 / 0.13 R (0.86 / 0.37 ATR) | 0.31 / 0.19 R (1.10 / 0.71 ATR) | 0.42 / 0.28 R (1.28 / 1.05 ATR) |
| BREAKOUT_ACCEPTED @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.07 / 0.10 R (0.35 / 0.34 ATR) | 0.12 / 0.13 R (0.46 / 0.53 ATR) | 0.15 / 0.13 R (0.66 / 0.66 ATR) | 0.22 / 0.20 R (0.84 / 0.84 ATR) | 0.25 / 0.36 R (0.97 / 1.23 ATR) |
| SWEEP_HIGH @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.99 / 0.75 R (0.43 / 0.28 ATR) | 1.44 / 1.00 R (0.62 / 0.40 ATR) | 1.78 / 1.00 R (0.75 / 0.48 ATR) | 2.53 / 1.62 R (1.07 / 0.73 ATR) | 3.61 / 2.52 R (1.45 / 1.07 ATR) |
| SWEEP_HIGH @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.62 / 0.59 R (0.35 / 0.34 ATR) | 0.87 / 0.83 R (0.50 / 0.50 ATR) | 1.08 / 1.01 R (0.62 / 0.60 ATR) | 1.57 / 1.57 R (0.90 / 0.86 ATR) | 2.29 / 2.24 R (1.30 / 1.25 ATR) |
| SWEEP_HIGH @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 1.21 / 1.24 R (0.35 / 0.36 ATR) | 1.78 / 1.83 R (0.49 / 0.51 ATR) | 2.14 / 2.24 R (0.61 / 0.62 ATR) | 3.16 / 3.17 R (0.88 / 0.90 ATR) | 4.36 / 4.56 R (1.21 / 1.29 ATR) |
| SWEEP_LOW @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.90 / 0.68 R (0.48 / 0.31 ATR) | 1.26 / 0.93 R (0.69 / 0.43 ATR) | 1.54 / 1.00 R (0.83 / 0.52 ATR) | 2.21 / 1.35 R (1.13 / 0.79 ATR) | 2.99 / 2.24 R (1.49 / 1.19 ATR) |
| SWEEP_LOW @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.52 / 0.50 R (0.37 / 0.36 ATR) | 0.74 / 0.71 R (0.53 / 0.52 ATR) | 0.91 / 0.85 R (0.66 / 0.64 ATR) | 1.34 / 1.34 R (0.93 / 0.93 ATR) | 1.86 / 2.06 R (1.28 / 1.35 ATR) |
| SWEEP_LOW @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 1.17 / 1.17 R (0.38 / 0.38 ATR) | 1.74 / 1.78 R (0.56 / 0.53 ATR) | 2.15 / 2.20 R (0.70 / 0.67 ATR) | 2.96 / 3.15 R (0.98 / 0.98 ATR) | 3.92 / 4.31 R (1.30 / 1.41 ATR) |
| ZONE_DEFENDED @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.38 / 0.26 R (0.45 / 0.30 ATR) | 0.58 / 0.33 R (0.68 / 0.38 ATR) | 0.73 / 0.39 R (0.82 / 0.44 ATR) | 1.07 / 0.60 R (1.21 / 0.69 ATR) | 1.45 / 0.88 R (1.67 / 0.98 ATR) |
| ZONE_DEFENDED @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.24 / 0.23 R (0.35 / 0.35 ATR) | 0.35 / 0.33 R (0.53 / 0.50 ATR) | 0.44 / 0.40 R (0.68 / 0.61 ATR) | 0.68 / 0.61 R (1.04 / 0.91 ATR) | 0.93 / 0.88 R (1.36 / 1.27 ATR) |
| ZONE_DEFENDED @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 2.18 / 1.57 R (0.39 / 0.28 ATR) | 3.05 / 2.33 R (0.53 / 0.40 ATR) | 4.12 / 3.00 R (0.66 / 0.51 ATR) | 6.86 / 3.99 R (1.12 / 0.75 ATR) | 8.13 / 5.50 R (1.42 / 1.09 ATR) |

#### H4. Edge half-life (fresh entry expectancy by age since confirmation)

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| setup type | status | half-life | age 0 min: n / E[R] | age 5 min: n / E[R] | age 15 min: n / E[R] | age 30 min: n / E[R] | age 60 min: n / E[R] | age 120 min: n / E[R] |
|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED | INSUFFICIENT_SAMPLE | — | 21 / -0.014 | 17 / 0.110 | 15 / 0.092 | 13 / 0.188 | 11 / 0.074 | 8 / -0.245 |
| BREAKOUT_ACCEPTED | INSUFFICIENT_SAMPLE | — | 19 / -0.017 | 12 / -0.031 | 12 / 0.035 | 12 / -0.011 | 11 / 0.000 | 8 / -0.130 |
| SWEEP_HIGH | NO_POSITIVE_EDGE | — | 5627 / -0.112 | 1794 / -0.070 | 643 / -0.083 | 235 / 0.032 | 56 / 0.035 | 18 / -0.003 |
| SWEEP_LOW | NO_POSITIVE_EDGE | — | 5658 / -0.066 | 1874 / 0.008 | 639 / 0.048 | 243 / -0.012 | 69 / 0.023 | 11 / 0.480 |
| ZONE_DEFENDED | NO_POSITIVE_EDGE | — | 860 / -0.040 | 325 / 0.015 | 177 / 0.031 | 97 / -0.011 | 35 / 0.001 | 11 / 0.285 |

#### H5. Opportunity Age validation: TIMELY vs VALID_BUT_LATE vs RETEST entries

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED / TIMELY | 1 | — | 0.000 | — | -1.000 | -1.000 | 0.000 | 1.000 | **INSUFFICIENT_SAMPLE** |
| BREAKDOWN_ACCEPTED / VALID_BUT_LATE | 22 | — | 0.591 | 0.429 | -0.702 | -0.034 [-0.330, 0.261] | 0.883 [0.252, 2.847] | 1.766 | **INSUFFICIENT_SAMPLE** |
| BREAKOUT_ACCEPTED / VALID_BUT_LATE | 33 | — | 0.606 | 0.382 | -0.780 | -0.076 [-0.331, 0.175] | 0.753 [0.262, 1.981] | 4.203 | **INSUFFICIENT_SAMPLE** |
| SWEEP_HIGH / RETEST | 423 | — | 0.189 | 2.742 | -0.979 | -0.275 [-0.441, -0.103] | 0.653 [0.468, 0.864] | 130.566 | yes |
| SWEEP_HIGH / TIMELY | 2164 | — | 0.197 | 3.486 | -1.081 | -0.179 [-0.300, -0.056] | 0.793 [0.669, 0.932] | 440.587 | yes |
| SWEEP_HIGH / VALID_BUT_LATE | 4917 | — | 0.571 | 0.492 | -0.937 | -0.121 [-0.149, -0.094] | 0.698 [0.641, 0.760] | 601.363 | yes |
| SWEEP_LOW / RETEST | 382 | — | 0.199 | 2.905 | -0.991 | -0.216 [-0.409, -0.002] | 0.728 [0.509, 0.997] | 94.781 | yes |
| SWEEP_LOW / TIMELY | 1846 | — | 0.238 | 3.233 | -1.014 | -0.002 [-0.127, 0.140] | 0.998 [0.840, 1.185] | 119.605 | yes |
| SWEEP_LOW / VALID_BUT_LATE | 5235 | — | 0.595 | 0.459 | -0.913 | -0.097 [-0.122, -0.071] | 0.738 [0.681, 0.801] | 507.855 | yes |
| ZONE_DEFENDED / RETEST | 5 | — | 0.400 | 2.563 | -1.000 | 0.425 [-1.000, 1.960] | 1.708 [0.000, 10.251] | 3.000 | **INSUFFICIENT_SAMPLE** |
| ZONE_DEFENDED / TIMELY | 128 | — | 0.234 | 4.200 | -1.027 | 0.198 [-0.277, 0.753] | 1.251 [0.674, 2.044] | 21.433 | yes |
| ZONE_DEFENDED / VALID_BUT_LATE | 851 | — | 0.716 | 0.265 | -0.859 | -0.055 [-0.098, -0.011] | 0.776 [0.639, 0.948] | 46.723 | yes |

#### H6. Segment: timeframe (min), entry at FIRST_EXECUTABLE, all setup types

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| timeframe (min) | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| 15 | 433 | 0.040 | 0.196 | 2.858 | -1.052 | -0.284 [-0.465, -0.100] | 0.664 [0.492, 0.872] | 142.875 | yes |
| 5 | 4091 | 0.086 | 0.220 | 3.341 | -1.040 | -0.076 [-0.159, 0.011] | 0.906 [0.808, 1.013] | 371.282 | yes |

#### H6. Segment: NIFTY 15m TREND regime, entry at FIRST_EXECUTABLE, all setup types

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| NIFTY 15m TREND regime | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| DOWN | 276 | 0.034 | 0.207 | 3.150 | -1.003 | -0.146 [-0.431, 0.173] | 0.817 [0.486, 1.228] | 56.279 | yes |
| RANGE | 337 | 0.032 | 0.187 | 3.607 | -1.306 | -0.388 [-0.817, 0.020] | 0.635 [0.376, 1.023] | 132.953 | yes |
| UNAVAILABLE | 3623 | 0.105 | 0.224 | 3.263 | -1.022 | -0.062 [-0.147, 0.028] | 0.922 [0.819, 1.036] | 314.638 | yes |
| UP | 288 | 0.032 | 0.184 | 3.644 | -1.000 | -0.145 [-0.436, 0.207] | 0.822 [0.487, 1.265] | 69.079 | yes |

#### H6. Segment: time of day (confirmation), entry at FIRST_EXECUTABLE, all setup types

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| time of day (confirmation) | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| 09:15-10:15 | 242 | 0.164 | 0.215 | 3.893 | -1.002 | 0.050 [-0.245, 0.367] | 1.064 [0.706, 1.499] | 39.362 | yes |
| 10:15-11:30 | 1077 | 0.149 | 0.227 | 3.174 | -0.992 | -0.049 [-0.183, 0.095] | 0.937 [0.769, 1.128] | 126.220 | yes |
| 11:30-13:30 | 1891 | 0.099 | 0.225 | 3.437 | -1.029 | -0.023 [-0.155, 0.124] | 0.971 [0.810, 1.159] | 169.320 | yes |
| 13:30-14:30 | 852 | 0.056 | 0.189 | 3.038 | -1.162 | -0.368 [-0.564, -0.189] | 0.609 [0.466, 0.781] | 324.612 | yes |
| 14:30-15:40 | 462 | 0.022 | 0.221 | 3.132 | -0.995 | -0.084 [-0.327, 0.196] | 0.892 [0.595, 1.261] | 91.488 | yes |

#### H7. Walk-forward (train 12 m / test 3 m / step 3 m), out-of-sample test windows only

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family | windows | windows with a choice | choices | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED | 18 | 0 | {} | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| BREAKOUT_ACCEPTED | 18 | 0 | {} | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| SWEEP_HIGH | 18 | 18 | {'{"structure.acceptance.closes": 2, "structure.consolidation.max_width_atr": 1.0}': 14, '{"structure.acceptance.closes": 2, "structure.consolidation.max_width_atr": 1.5}': 4} | 1908 | 0.204 | 0.200 | 3.336 | -1.084 | -0.202 [-0.327, -0.066] | 0.767 [0.639, 0.919] | 410.242 | yes |
| SWEEP_LOW | 18 | 18 | {'{"structure.acceptance.closes": 2, "structure.consolidation.max_width_atr": 1.0}': 18} | 1632 | 0.232 | 0.232 | 3.308 | -0.999 | 0.001 [-0.134, 0.154] | 1.002 [0.828, 1.206] | 119.266 | yes |
| ZONE_DEFENDED | 18 | 0 | {} | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |

#### RECORDED

Split: {'development': 0, 'holdout': 0, 'post_window': 0, 'development_days': []}. Holdout: HOLDOUT_EMPTY: fewer good sessions.

#### R1. Session quality

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

| session | GOOD | coverage | max edge gap s | reasons |
|---|---|---|---|---|
| 2026-11-06 | False | 65.8% | 1800.0 | COVERAGE 65.8% < 95%; EDGE_GAP 1800 s > 30 s in the first/last 30 min |

#### R2. Families (paper-broker trades, net of Phase 7 costs), unit INR

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No trades.

#### R3. Families, unit net R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No trades.

#### R4. Slippage share of gross P&L, OI publication delay

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

Slippage: {'slippage_inr': 0, 'gross_inr': 0, 'share_of_gross': None}

OI delay: {'label': 'LOOK_AHEAD_DIAGNOSTIC (never a decision input)', 'positioning_decisions': 0, 'oi_unavailable_at_decision': 0, 'differs': 0, 'median_abs_diff_pct': None}

#### R7. Segment: underlying, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

#### R7. Segment: tod, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

#### R7. Segment: score_band, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

#### R7. Segment: instrument, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

#### R7. Segment: expiry (events @ FIRST_EXECUTABLE, gross R), unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

#### R6. Walk-forward (train 40 / test 10 / step 10 good sessions), out-of-sample only

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

NOT_RUN: 0 development sessions < train 40 + test 10

#### R5. Event study, half-life, Opportunity Age (recorded)

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

0 family x anchor rows; half-life no entries

#### Verdicts

**SIMULATED / HYPOTHETICAL · stage BELOW_SYSTEM_CHECK · 0 good sessions**

| Phase 8 family | verdict | reason |
|---|---|---|
| A | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| B | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| C | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| D | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| E | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| F | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |

#### PIPELINE_CHECK 2026-11-06 (EXCLUDED session; not part of any result)

run_day: {'day': '2026-11-06', 'eligible': 0, 'opened': 0, 'not_opened': 0, 'actual': 0}; trades: 0; event rows: 2964; age entries: 783; class entries: 861; OI delay: {'label': 'LOOK_AHEAD_DIAGNOSTIC (never a decision input)', 'positioning_decisions': 20, 'oi_unavailable_at_decision': 0, 'differs': 1, 'median_abs_diff_pct': 0.1582}

| family @ anchor | n | n anchor unavailable | IMMEDIATE_1_5 | CONTINUATION_5_30 | MID_30_90 | MULTI_SESSION | FAILED | INCONCLUSIVE |
|---|---|---|---|---|---|---|---|---|
| BREAKOUT_ACCEPTED @ FIRST_DETECTION | 2 | 0 | 1 | 1 | 0 | 0 | 0 | 0 |
| BREAKOUT_ACCEPTED @ CONFIRMATION | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| BREAKOUT_ACCEPTED @ FIRST_EXECUTABLE | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| LONG_BUILDUP @ FIRST_DETECTION | 13 | 4 | 2 | 1 | 0 | 0 | 3 | 7 |
| LONG_BUILDUP @ CONFIRMATION | 13 | 4 | 2 | 2 | 0 | 0 | 2 | 7 |
| LONG_BUILDUP @ FIRST_EXECUTABLE | 3 | 14 | 0 | 1 | 0 | 0 | 1 | 1 |
| SHORT_BUILDUP @ FIRST_DETECTION | 4 | 3 | 2 | 0 | 0 | 0 | 1 | 1 |
| SHORT_BUILDUP @ CONFIRMATION | 4 | 3 | 2 | 0 | 0 | 0 | 1 | 1 |
| SHORT_BUILDUP @ FIRST_EXECUTABLE | 2 | 5 | 0 | 0 | 0 | 0 | 1 | 1 |
| SHORT_COVERING @ FIRST_DETECTION | 3 | 0 | 0 | 1 | 0 | 0 | 1 | 1 |
| SHORT_COVERING @ CONFIRMATION | 3 | 0 | 0 | 1 | 0 | 0 | 1 | 1 |
| SHORT_COVERING @ FIRST_EXECUTABLE | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| SWEEP_HIGH @ FIRST_DETECTION | 570 | 0 | 103 | 26 | 0 | 0 | 262 | 179 |
| SWEEP_HIGH @ CONFIRMATION | 570 | 0 | 128 | 22 | 0 | 0 | 226 | 194 |
| SWEEP_HIGH @ FIRST_EXECUTABLE | 333 | 237 | 26 | 7 | 0 | 0 | 179 | 121 |
| SWEEP_LOW @ FIRST_DETECTION | 293 | 0 | 101 | 24 | 0 | 0 | 87 | 81 |
| SWEEP_LOW @ CONFIRMATION | 293 | 0 | 114 | 25 | 0 | 0 | 72 | 82 |
| SWEEP_LOW @ FIRST_EXECUTABLE | 85 | 208 | 16 | 5 | 0 | 0 | 37 | 27 |
| ZONE_DEFENDED @ FIRST_DETECTION | 96 | 0 | 33 | 15 | 3 | 0 | 10 | 35 |
| ZONE_DEFENDED @ CONFIRMATION | 96 | 0 | 32 | 8 | 3 | 0 | 16 | 37 |
| ZONE_DEFENDED @ FIRST_EXECUTABLE | 14 | 82 | 2 | 1 | 0 | 0 | 9 | 2 |

Half-life file: `config/engine/half_life/v1.json`. Runtime 167.3 s.
