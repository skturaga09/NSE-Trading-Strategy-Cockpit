# Phase 8 report: signal engine, eligibility gates, evidence scoring, lifecycle

Date: built 2026-11-06 (IST, evening). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, phase-0…7 reports. `docs/decisions.md` does not exist. `docs/questions-ledger.md`
did not exist; it was created in this phase (rows from Phase 8 on; earlier questions stay in open-questions.md).
Advisory and paper-trading only: no order placement, modification or cancellation exists. `test_no_order_methods_in_repo_code` and
`test_engine_never_uses_kiteconnect_rest_class` pass.

## 0. Headline

On the one recorded session (2026-11-06): 961 Phase 6 setups ⇒ 865 lifecycles ⇒ **86 recommendations, all REJECTED, 0 ENTRY_ELIGIBLE**.
- Families A–D cannot fire. No OI cadence doc exists (Q-EOD-1), so every OI window is disabled and the primary positioning view is never evaluated (OI_WINDOW_DISABLED). The same cause leaves SUSPECTED_ACCUMULATION / _DISTRIBUTION at 0.
- E (58) and F (28) fire. **Every one failed RISK_CHECK_APPROVED** (futures capital at full notional, Q-RISK-1; options have no data, Q-CON-1). **Every one also failed TIMELINESS.**
  E/F need a BOS/CHOCH after the sweep, and by the time that confirmation arrived, Phase 6 classed the setup VALID_BUT_LATE (45), EXHAUSTED (36) or UNKNOWN (5).
- Available score maximum is 43.33 / 100. These inputs were UNAVAILABLE: options (always), volume profile (not built), futures positioning (OI windows disabled), index positioning, and index trend (NIFTY had no 15m BOS/CHOCH that day).
  So every score is in the RESEARCH_PRIORITY_LOW band.
- Replaying the 86 stored inputs regenerates 86 byte-identical recommendations.

This is the correct output for these inputs, not a tuning result. It says nothing about an edge.

## 1. Owner answers and interpretations

Questions were asked once, at the start (guardrail Q2). The rows are in [questions-ledger.md](questions-ledger.md).
- **Q-8-1 (BLOCKING), answered: proceed.** Q-EOD-1, Q-RISK-1 and Q-CON-1 stay OPEN. Their effect is §0.
- **Q-8-2..9: the owner accepted the assumptions.**
  - Q-8-2: 12 labels. Recommendation fields = the phase text's list.
  - Q-8-3: the driver stops at ENTRY_ELIGIBLE / WAIT_FOR_RETEST / REJECTED. REJECTED is terminal.
  - Q-8-4: Tier B promotion is built and tested, not wired live.
  - Q-8-5: raw points.
  - Q-8-6: families sit on Phase 6 setups.
  - Q-8-7: thresholds are PROPOSED.
  - Q-8-8: entry trigger / T1 / T2.
  - Q-8-9: critical inputs.
- **Assumed during the build (Q-8-10..17, ASSUMED, not yet answered):**
  - Q-8-10: CONFLICTING_EVIDENCE is a label, not a gate.
  - Q-8-11: precedence is NO_TRADE > UNCERTAIN > CONFLICTING_EVIDENCE > family. EXHAUSTED or UNKNOWN ⇒ REJECTED. WAIT_FOR_RETEST only when TIMELINESS is the only failure.
  - Q-8-12: equal part split inside a factor; the reversal volume part uses the sweep's rejection RVOL.
  - Q-8-13: ENTRY_ELIGIBLE expires when no longer TIMELY. Everything expires at the 15:00 cutoff and at the close.
  - Q-8-14: breadth and index inputs.
  - Q-8-15: pickled inputs.
  - Q-8-16: observation emission.
  - Q-8-17: no event gate (not in this phase's gate list; Q-RISK-3 stays open).
- **Tests first (guardrail 14):** `tests/engine_tests/test_signals.py` was written before `engine/signals.py`. Its fixture arithmetic was then corrected twice before the first green run:
  - VWAP comes from the Phase 5 detection.
  - The fixture ATR was raised to 1000 paise, so that the base case is TIMELY under `max_stop_atr` 1.5.

## 2. Files

| File | Purpose |
|---|---|
| `engine/signals.py` (pure, 710 lines) | `Evidence`, `MarketContext`, `FamilySetup`, `Observation`; `match` (A–F), `exhaustion_observation` (G), `accumulation`, `market_context`; `Part` / `Factor` / `Score` / `ScoreSet`, `score`; `Gate`, `gates`; `SignalInputs`, `SignalRecommendation`, `recommend`, `payload`; `Transition`, `Lifecycle`, `ALLOWED`, `start`, `advance`, `IllegalTransition`, `drive`; `promotions`, `promote` |
| `engine/signal_report.py` (edge) | `QuoteBook` (recorded quotes as of t, read-only, one scan per underlying), `run_date`, `write` / `read` / `replay_check` (`<date>/signals.sqlite`), `summarize`, `report`, CLI |
| `config/engine/v10.yaml` | v9 unchanged + `signals` (sha256 `664f38c6`); weights must sum to 100 (loader check) |
| `tests/engine_tests/test_signals.py` | 23 tests, synthetic fixtures (reuses the Phase 6/7 fixtures and constructors) |
| `engine/contract_report.py` | refactor only: the rows→Quote mapping became `quote_from_rows` and is shared. The re-run Phase 7 report is **byte-identical** to `phase-7-evidence/candidates-2026-11-06.md` (`phase-8-evidence/contract-report-refactor-check.txt`) |
| docs | `questions-ledger.md` (new), architecture §15, this report, `phase-8-evidence/` |

No earlier interface changed. `git diff --stat defa774` (tracked files) shows only Phase 1's `.gitignore`.

## 3. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| F-A | Fresh long buildup breakout (resistance, LONG_BUILDUP residual, RVOL elevated, above VWAP, acceptance) | DONE | `test_A_fresh_long_buildup_breakout` (positive + 6 negatives) |
| F-B | Short buildup breakdown (symmetric) | DONE | `test_B_fresh_short_buildup_breakdown` |
| F-C | Short-covering momentum; exhaustion check always run; "covering, not confirmed new buying" | DONE | `test_C_short_covering_momentum_is_labelled_and_exhaustion_checked` |
| F-D | Long-unwinding continuation, persistent volume | DONE | `test_D_long_unwinding_continuation_needs_persistent_volume` |
| F-E/F | Liquidity-sweep reversals: sweep + reclaim + rejection RVOL + structure confirmation | DONE | `test_E_F_liquidity_sweep_reversals` |
| F-G | Exhaustion = warning on other setups + standalone observation, never an entry | DONE | `test_G_exhaustion_is_an_observation_and_a_warning_never_an_entry` |
| OPT | Option-chain evidence slot UNAVAILABLE | DONE | `test_missing_option_data_scores_zero_…` |
| LBL | 12 state labels incl. SUSPECTED_ACCUMULATION / _DISTRIBUTION, NO_TRADE, UNCERTAIN | DONE (list assumed, Q-8-2) | `test_all_twelve_state_labels_exist_and_are_reachable`, `test_suspected_accumulation_and_distribution` |
| GATE | 10 mandatory gates before scoring; failure ⇒ REJECTED with reasons, setup + score still stored | DONE | `test_high_score_with_a_failed_gate_…`, `test_stale_critical_data_…`, `test_late_waits_for_retest_unknown_is_rejected`; real data: 86 stored REJECTED with scores |
| GATE-T | TIMELY required; VALID_BUT_LATE ⇒ WAIT_FOR_RETEST; UNKNOWN ⇒ REJECTED | DONE | `test_late_waits_for_retest_unknown_is_rejected`, `test_driver_retest_then_eligible_then_expired` |
| SC1 | Config weights, versioned; default 25/20/20/15/10/10 | DONE | v10 `signals.weights`; `test_v10_loads_missing_key_and_bad_weights_fail` |
| SC2 | Each factor: points + explanation + inputs; UNAVAILABLE ⇒ 0 and listed; max achievable reported | DONE | `test_missing_option_data_scores_zero_listed_missing_and_max_available_reported` |
| SC3 | Separate bullish, bearish, reversal, continuation scores | DONE | `test_scores_are_separate_and_counter_direction_scores_lower` |
| SC4 | Broad market: NIFTY trend/structure, breadth (share above VWAP), index futures positioning | DONE (on real data, trend and index positioning were UNAVAILABLE all day, §0) | `market_context`; real data §4 |
| SC5 | Bands 80+/60–79/<60 labelled RESEARCH_PRIORITY, "not a probability" | DONE | `test_scores_are_separate_…` |
| REC | Recommendation object with the spec's fields | DONE | `test_recommendation_has_every_field_and_prices_from_quotes` |
| REC-P | Prices only from actual quotes; no defensible stop or R:R ⇒ NO_TRADE | DONE | same test (entry range = executable ask .. walked fill); `test_no_defensible_stop_is_no_trade` |
| LC1 | State machine with the 13 states; only allowed transitions; each an appended row (ts + cause) | DONE | `test_illegal_transitions_raise_and_rows_are_appended`; real data: 2,681 rows |
| LC2 | Illegal transitions raise | DONE | same test (skips, back-in-time, out of terminal states) |
| TIER | ENTRY_ELIGIBLE ⇒ promote the underlying + candidate contracts to Tier B via the Phase 3 API | DONE (not wired into the live recorder, Q-8-4) | `test_entry_eligible_promotes_underlying_and_candidates_to_tier_b` (real `TierBook.plan()` shows tier B) |
| AT1 | High score with a failed gate ⇒ REJECTED, never ENTRY_ELIGIBLE | DONE | `test_high_score_with_a_failed_gate_is_rejected_never_entry_eligible` (score ≥ 60, two gates, plus the driver) |
| AT2 | Stale critical data ⇒ cannot reach ENTRY_ELIGIBLE | DONE | `test_stale_critical_data_cannot_reach_entry_eligible` (stale price, stale quote, driver) |
| AT3 | Illegal lifecycle transitions raise | DONE | `test_illegal_transitions_raise_and_rows_are_appended` |
| AT4 | Each family: positive and negative fixtures; negatives produce no setup | DONE | the 7 family tests + accumulation |
| AT5 | Missing option data ⇒ options factor 0, listed missing, max-available reported | DONE | `test_missing_option_data_…` |
| AT6 | Replaying stored inputs regenerates an identical object | DONE | `test_replaying_stored_inputs_regenerates_an_identical_object` (in memory + through the SQLite store); real data: 86/86 identical |
| RPT | Per-day counts by family and status; top 10 rejected-for-reason examples | DONE (1 recorded day) | §4 |

Mutation checks (`phase-8-evidence/mutation-checks.txt`): each guard was broken in turn, and the suite must fail.
```
MUTATION single-position gate ignored: exit=1 -> 1 failing
    FAIL: test_high_score_with_a_failed_gate_is_rejected_never_entry_eligible
MUTATION price age not checked in DATA_QUALITY: exit=1 -> 2 failing
    FAIL: test_all_twelve_state_labels_exist_and_are_reachable
    FAIL: test_stale_critical_data_cannot_reach_entry_eligible
MUTATION lifecycle transition table not enforced: exit=1 -> 1 failing
    FAIL: test_illegal_transitions_raise_and_rows_are_appended
MUTATION missing option factor counted as available: exit=1 -> 1 failing
    FAIL: test_missing_option_data_scores_zero_listed_missing_and_max_available_reported
MUTATION family A without the RVOL check: exit=1 -> 2 failing
    FAIL: test_A_fresh_long_buildup_breakout
    FAIL: test_B_fresh_short_buildup_breakdown
MUTATION family E without structure confirmation: exit=1 -> 1 failing
    ERROR: test_E_F_liquidity_sweep_reversals
MUTATION risk_check approval not required: exit=1 -> 1 failing
    ERROR: test_high_score_with_a_failed_gate_is_rejected_never_entry_eligible
MUTATION stored inputs differ from the ones used: exit=1 -> 1 failing
    FAIL: test_replaying_stored_inputs_regenerates_an_identical_object
restored: OK
```
("missing option factor counted as available" is a misnomer: that mutation drops the factor's missing-input listing.)

## 4. Real data: 2026-11-06 (1 partial session; outage 09:03–11:26)

Command: `python3 -m engine.signal_report 2026-11-06 --report …` (config v10 sha256 `664f38c6`). It ran in 4 min 30 s, recomputing Phases 4–6, and wrote 3,069 rows.
Full output: [phase-8-evidence/signal-report-2026-11-06.md](phase-8-evidence/signal-report-2026-11-06.md); run log: `run-2026-11-06.txt`.
Inputs:
- Portfolio flat.
- No margin quotes.
- No option bars or quotes (none recorded).
- Quotes = the latest recorded depth + tick row at or before each decision.

**Counts by family and status (recommendations)**

| family | ENTRY_ELIGIBLE | WAIT_FOR_RETEST | REJECTED |
|---|---|---|---|
| A, B, C, D | 0 | 0 | 0 (cannot fire: OI_WINDOW_DISABLED, Q-EOD-1; Phase 4 produced 0 events) |
| E bullish sweep reversal | 0 | 0 | 58 |
| F bearish sweep reversal | 0 | 0 | 28 |

- **Classification:** BULLISH_SWEEP_REVERSAL 36, BEARISH_SWEEP_REVERSAL 22, CONFLICTING_EVIDENCE 18, NO_TRADE 9, UNCERTAIN 1.
- **Phase 6 class at the decision:** VALID_BUT_LATE 45, EXHAUSTED 36, UNKNOWN 5.
- **Lifecycles (865, one per breakout/breakdown/sweep setup; 96 ZONE setups map to no family):**
  - Final states: INVALIDATED 396, EXPIRED 383, REJECTED 86.
  - Transitions: None→DETECTED 865, DETECTED→WATCHING 865, WATCHING→CONFIRMED 86, CONFIRMED→REJECTED 86, WATCHING→EXPIRED 383, WATCHING→INVALIDATED 396.
- **Observations:** POSSIBLE_EXHAUSTION 301; SUSPECTED_ACCUMULATION / _DISTRIBUTION 0 (no evaluated positioning view).
- **Bands:** RESEARCH_PRIORITY_LOW 86.

Failed gates across the 86 REJECTED (a recommendation can fail several):

| gate | count | main reason |
|---|---|---|
| RISK_CHECK_APPROVED | 86 | CAPITAL_ABOVE_LIMIT (MARGIN_ESTIMATED full notional, Q-RISK-1), plus spread / net R:R / risk per lot |
| TIMELINESS | 86 | Phase 6 not TIMELY at the confirmation (above) |
| SPREAD_ACCEPTABLE | 70 | mostly SPREAD_VS_MOVE_TOO_WIDE: the spread is > 20 % of the move to T1 |
| LIQUIDITY_MINIMUM | 10 | 5 with no priced candidate (no plan), 5 not sized (BAD_GEOMETRY) |
| COST_MODEL_VERIFIED | 10 | no risk decision (5) / no cost estimate on an excluded candidate (5) |
| VALID_ENTRY_STOP | 9 | 5 no obstacle in the trade direction (no T1 ⇒ no R:R), 4 BAD_GEOMETRY |
| DATA_QUALITY | 7 | 5 obstacle missing, 1 price 60 s old, 1 STALE_QUOTE (11.7 s > 5 s) |
| INSTRUMENT_TRADABLE | 5 | no priced candidate |
| DAILY_LIMITS | 5 | no risk decision (no plan); a flat portfolio never breaches |

**Top 10 rejected (highest score first), with the reasons:**

| # | underlying, time | family / classification | dir | score / available | contract | failed gates |
|---|---|---|---|---|---|---|
| 1 | NIFTY 13:12 | E BULLISH_SWEEP_REVERSAL | LONG | 42.85/43.33 | NIFTY26NOVFUT | SPREAD_ACCEPTABLE: SPREAD_VS_MOVE_TOO_WIDE (28.6 % of the move to T1 > 20 %)<br>RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 2 | RELIANCE 12:27 | E BULLISH_SWEEP_REVERSAL | LONG | 42.57/43.33 | RELIANCE26NOVFUT | SPREAD_ACCEPTABLE: SPREAD_VS_MOVE_TOO_WIDE (33.3 % of the move to T1 > 20 %)<br>RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 VALID_BUT_LATE (RULES_FAILED) |
| 3 | ABB 14:21 | E BULLISH_SWEEP_REVERSAL | LONG | 41.85/43.33 | ABB26NOVFUT | RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 4 | ABB 14:21 | E BULLISH_SWEEP_REVERSAL | LONG | 41.85/43.33 | ABB26NOVFUT | RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 5 | ABB 14:21 | E BULLISH_SWEEP_REVERSAL | LONG | 41.85/43.33 | ABB26NOVFUT | RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 6 | HINDUNILVR 14:54 | E BULLISH_SWEEP_REVERSAL | LONG | 41.82/43.33 | HINDUNILVR26NOVFUT | SPREAD_ACCEPTABLE: SPREAD_VS_MOVE_TOO_WIDE (37.5 % of the move to T1 > 20 %)<br>RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 7 | SIEMENS 14:21 | E CONFLICTING_EVIDENCE | LONG | 41.64/43.33 | SIEMENS26NOVFUT | RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 8 | SIEMENS 14:21 | E CONFLICTING_EVIDENCE | LONG | 41.64/43.33 | SIEMENS26NOVFUT | RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 9 | TCS 14:09 | F CONFLICTING_EVIDENCE | SHORT | 39.2/43.33 | TCS26NOVFUT | SPREAD_ACCEPTABLE: SPREAD_VS_MOVE_TOO_WIDE (66.7 % of the move to T1 > 20 %)<br>RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |
| 10 | CIPLA 14:21 | E CONFLICTING_EVIDENCE | LONG | 39.09/43.33 | CIPLA26NOVFUT | SPREAD_ACCEPTABLE: SPREAD_VS_MOVE_TOO_WIDE (150.0 % of the move to T1 > 20 %)<br>RISK_CHECK_APPROVED: REJECTED<br>TIMELINESS: Phase 6 EXHAUSTED (POSSIBLE_EXHAUSTION) |

The repeated ABB and SIEMENS rows at 14:21 are separate Phase 6 sweep setups (different swept levels) confirmed in the same minute. Each has its own lifecycle.

Replay check on real data: `{"checked": 86, "identical": 86, "different": []}`. Each stored `SignalInputs` was regenerated through `recommend`, and its JSON compared byte for byte with the stored object.

## 5. Facts used

**No new external facts. No kiteconnect method is called in Phase 8.** The pure module makes no I/O (`test_signal_core_is_pure`). The edge reads only local
SQLite files, read-only (`buffer.sqlite`, `universe.sqlite`, history.sqlite via Phase 4), and writes only `<date>/signals.sqlite`.

Internal interfaces used as they are:

| Phase | Interface | Where |
|---|---|---|
| 3 | `TierBook.promote` | `engine/tiers.py:118` |
| 5 | `levels_at` | `engine/structure.py:532` |
| 6 | `opportunity_age` / `Setup` / `Evaluation` | `engine/opportunity.py:271` |
| 7 | `select_contracts` | `engine/contracts.py:319` |
| 7 | `risk_check` | `engine/risk.py:88` |
| 7 | `Recommendation` (token-backed) | `engine/risk.py:76` |

Existing facts relied on:
- F-QUOTE-5/7 and F-WS-5: pending quantity is not executed volume, and 5-level depth is not a full book (in labels and in the liquidity note).
- F-QUOTE-6: VWAP = average traded price (breadth).
- F-WS-9: prices in paise.

## 6. Open questions

**Still OPEN and blocking capabilities:**
- Q-EOD-1: no cadence doc ⇒ families A–D, accumulation, futures-positioning and index-positioning factors are all dead.
- Q-RISK-1: futures capital.
- Q-CON-1: options.

**Phase 8 rows ASSUMED:** Q-8-10..17 (ledger).

**Still OPEN from earlier phases and relevant here:**
- Q-RISK-2: every risk value is PROPOSED.
- Q-RISK-3: event days (Q-8-17).
- Q-RISK-4: portfolio state source.
- Q-CFG-2: global default config.
- Q-POS-5 / Q-STR-6: nothing runs live, and Phase 8 is batch too.
- Q-QUAL-1.

New observations for your review (not ledger questions; no decision is needed to finish Phase 8):
- **E/F confirmation vs timeliness.** Requiring a BOS/CHOCH after the sweep meant that every E/F setup on this day was already LATE / EXHAUSTED when confirmed.
  Because REJECTED is terminal (Q-8-3), a setup rejected while LATE for another reason (e.g. capital) never gets a retest chance. Only "TIMELINESS alone failed" waits for a retest.
  Today that is masked by Q-RISK-1, but it will matter once futures can pass risk.
- **SPREAD_VS_MOVE_TOO_WIDE** (Phase 7 limit, 20 %) failed on 70 of 86. Sweep targets are close, so a one-tick spread is a large share of the move.

## 7. Limitations

- One recorded session, with a 2 h 23 min outage. Families A–D, C's exhaustion warning on real setups, and SUSPECTED_* are proven on fixtures only.
- No ENTRY_ELIGIBLE was produced on real data, so the Tier B promotion and the WAIT_FOR_RETEST → CONFIRMED path are proven on fixtures only.
- Batch only. Phase 8 recomputes Phases 4–6 for the date (~4.5 min) and does not run inside the recorder. Promotions are not applied live (Q-8-4).
- Portfolio is flat at every decision (no paper ledger), so NO_CONFLICTING_POSITION and DAILY_LIMITS never bind on real data except when no plan exists.
- Stored inputs are pickled engine objects. Replay needs the same code version, and any change to these classes or functions makes old stored inputs non-replayable or different. Bump the config version when logic changes.
  `signals.sqlite` is INSERT OR IGNORE per config version: re-running changed code under the same version keeps the old rows. That happened once in this phase: the store of the first run was deleted (derived, created minutes earlier) and regenerated after a wording fix to two gate details.
- No volume profile, so profile_depth is at most 5 / 10. No option chain, so options are 0 / 20.

## 8. Raw test output

### 8.1 `python3 -m unittest discover -s tests/engine_tests -t . -v`
Full file: phase-8-evidence/engine-tests.txt. Phase 8 lines are shown with module paths trimmed, then the tail.
```
test_labels_never_claim_institutional_activity ... ok
test_signal_core_is_pure ... ok
test_v10_loads_missing_key_and_bad_weights_fail ... ok
test_A_fresh_long_buildup_breakout ... ok
test_B_fresh_short_buildup_breakdown ... ok
test_C_short_covering_momentum_is_labelled_and_exhaustion_checked ... ok
test_D_long_unwinding_continuation_needs_persistent_volume ... ok
test_E_F_liquidity_sweep_reversals ... ok
test_G_exhaustion_is_an_observation_and_a_warning_never_an_entry ... ok
test_all_twelve_state_labels_exist_and_are_reachable ... ok
test_suspected_accumulation_and_distribution ... ok
test_high_score_with_a_failed_gate_is_rejected_never_entry_eligible ... ok
test_late_waits_for_retest_unknown_is_rejected ... ok
test_missing_option_data_scores_zero_listed_missing_and_max_available_reported ... ok
test_no_defensible_stop_is_no_trade ... ok
test_passing_fixture_is_entry_eligible ... ok
test_recommendation_has_every_field_and_prices_from_quotes ... ok
test_scores_are_separate_and_counter_direction_scores_lower ... ok
test_stale_critical_data_cannot_reach_entry_eligible ... ok
test_driver_retest_then_eligible_then_expired ... ok
test_entry_eligible_promotes_underlying_and_candidates_to_tier_b ... ok
test_illegal_transitions_raise_and_rows_are_appended ... ok
test_replaying_stored_inputs_regenerates_an_identical_object ... ok
Ran 159 tests in 36.591s
OK
exit=0
```

### 8.2 Whole repo `python3 -m unittest discover -s tests -v`
Full file: phase-8-evidence/full-suite.txt.
```
test_engine_never_uses_kiteconnect_rest_class (engine_tests.test_edges.TestNoOrderCode.test_engine_never_uses_kiteconnect_rest_class) ... ok
test_no_order_methods_in_repo_code (engine_tests.test_edges.TestNoOrderCode.test_no_order_methods_in_repo_code) ... ok
test_grep_logic_modules (engine_tests.test_universe.TestNoHardcodedContractFacts.test_grep_logic_modules) ... ok
Ran 222 tests in 36.697s
OK
exit=0
```

An earlier run of 8.2 failed once (`test_no_order_methods_in_repo_code`). My own purity test contained the literal order-method names, and the repo-wide guard flagged them.
That line was removed (the repo-wide guard already covers `engine/signals.py`), and both suites were re-run with the output above.
