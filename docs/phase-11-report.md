# Phase 11 report: option-chain intelligence, IV/Greeks, event gates, selector V2

Date: built 2026-11-07 (Saturday, IST; market closed). Branch `stack/4-setup-radar`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, decisions.md, questions-ledger.md, phase-0…10 reports.
Advisory and paper-trading only: no order placement, modification or cancellation exists. `test_no_order_methods_in_repo_code`
and `test_engine_never_uses_kiteconnect_rest_class` pass.

## 0. Headline

- **No option has ever been recorded.** So every real-data number below comes from one of two sources: a read-only after-hours REST snapshot (labelled AFTER_HOURS), or the recorded 2026-11-06 session, which has no options in it. Live recording of options starts on the first session after you reinstall the recorder plist (§9). That is 2026-11-09 at the earliest.
- **The IV model** is Black-76 on the same-expiry future (F-OPT-1/2: NSE options are European). It uses the RBI 91-day T-bill rate (F-RATE-RBI-1) and time in trading-calendar years. IV is computed only from the mid of a fresh, narrow, two-sided book. It is **never computed from LTP** (test).
- **The IV percentile gate rejects every long option for at least 20 recorded sessions** (Q-11-7: no history means UNAVAILABLE, which means rejection). So **no option candidate can pass before ~20 recorded option sessions exist**. This is by design (rule 16) and is your call to change.
- **Event gate on real data:** the NSE event calendar (F-EVT-1) was fetched and stored. For long options on 2026-11-09, **9 of 96 stock underlyings are EVENT_IV_RISK** and 87 have no known event. NIFTY is an index, so it is not gated on constituents' results. On 2026-11-06 no calendar had been stored, so **every option candidate there is EVENT_UNVERIFIED** (§4.3).
- **Interface:** every change is additive and owner-approved (D-52). Earlier tests changed only where V2 intends a new behaviour: the OTM alternative, the v14 defaults, and the EOD chain order (§3).

## 1. Questions and decisions

Reminder (rule Q5): 14 earlier BLOCKING rows are still OPEN: Q-0-2, Q-0-3, Q-0-6, Q-0-7, Q-0-8, Q-1-4, Q-3-1, Q-6-2, Q-7-4, Q-7-5, Q-7-6, Q-7-8, Q-7-9, Q-7-10. Phase 11 touches four of them:
- **Q-7-8** (which strikes tier C records): the planner answers it, with your cap of 400.
- **Q-7-9** (option quantity units): still unmeasured. It gets measured on the first recorded option session.
- **Q-7-6** (event days): `risk.event_days` is still empty. The new event gate does that job for long options.
- **Q-3-1** (session hours from 2026-12-07): affects the intraday fraction of T.

Asked once this phase, answered by you on 2026-11-07:
- **Q-11-1 (BLOCKING):** proceed, with the 14 rows still open (D-50).
- **Q-11-2 (BLOCKING):** live tier C, (a) in `full` mode with a cap of **400** option tokens (D-51).
- **Q-11-3 (BLOCKING):** additive interface changes approved (D-52).

ASSUMED, each with a ledger row: Q-11-4 … Q-11-21. Highlights:
- **Q-11-7:** the IV-percentile gate blocks options until 20 sessions of history exist.
- **Q-11-12:** `dashboard/black76.py` is not imported.
- **Q-11-14:** the planner's priority order uses the previous session's setups.
- **Q-11-15:** you must reinstall the recorder plist.
- **Q-11-16:** the hypothesis rules.
- **Q-11-18:** change-only books look stale, which keeps IV coverage low.

**Interpretations (rule 16: the conservative reading)**
- **"Never use LTP from a stale trade for IV".** IV never uses LTP at all.
- **Positioning hypotheses** need **all four** inputs, each beyond its minimum: OI change, premium change, IV change and underlying move. Anything else is UNCERTAIN. OI plus premium alone never produces a label (test).

| label | option | OI | premium | IV | underlying |
|---|---|---|---|---|---|
| CALL_BUYING / PUT_BUYING | CE / PE | ▲ | ▲ | ▲ | moves toward the money (CE ▲, PE ▼) |
| CALL_WRITING / PUT_WRITING | CE / PE | ▲ | ▼ | ▼ | not toward the money (flat or away) |
| SHORT_COVERING | CE / PE | ▼ | ▲ | ▲ or flat | toward the money |
| LONG_LIQUIDATION | CE / PE | ▼ | ▼ | ▼ or flat | away from the money |
| SPREAD_OR_HEDGE_SUSPECTED | CE and PE at one strike | both ▲, ratio within [0.67, 1.5] | — | — | — |
| UNCERTAIN | anything else, or any input UNAVAILABLE | | | | |

- **OI concentration** is shown as the strike plus its share of the range's OI, and the change in that share. It is never called resistance.
- **Options factor (Q-11-10):**
  - SUPPORTIVE (full 20 points) needs at least 2 labels in the trade direction at ATM ± 2 and none against.
  - CONTRADICTING needs at least 2 against and none with; it scores 0.
  - Anything else is NEUTRAL and scores 0.
  - No chain at all means UNAVAILABLE, and the 20 points are left out of the available maximum (as in Phase 8).
- **Event gate (Q-11-8):**
  - Every board meeting counts, not only results.
  - The window is 5 trading days from the decision day, with the meeting day included.
  - A calendar more than 1 day old, or none, means EVENT_UNVERIFIED, and every option is rejected, index options included.
  - A stock missing from the calendar is labelled NO_KNOWN_EVENT. The required notice period is unverified (Q-EVT-1).
- **"REJECTED with EVENT_IV_RISK".** The selector marks the option EXCLUDED with that reason. Phase 7 `risk_check` then REJECTS it (`CANDIDATE_ELIGIBLE: EXCLUDED: EVENT_IV_RISK …`). A future gets the same finding as a warning label only.

## 2. What was built (files)

New:
| File | Content |
|---|---|
| `engine/options.py` | Pure. Contents:<ul><li>Black-76 price, no-arbitrage bounds, bisection IV solver with reasons</li><li>Greeks: delta, gamma, theta per trading day, vega per IV point</li><li>`trading_years`, `risk_free`</li><li>`analyze` (per-contract analytics with provenance and age)</li><li>`hypothesis`, `chain_snapshot` (OI, OI change and its age, volume, premium change, spread, depth, IV, IV change, PCR by OI and by volume, concentration and its change, hedge rule)</li><li>`atm_iv`, `iv_percentile`, `options_factor`, `OptionContext`</li><li>`premium_at` (delta-gamma-theta), `changes`, `quote_from_rest`</li><li>`plan_tier_c` (tier C planner)</li></ul> |
| `engine/events.py` | Pure `parse`, `window_end`, `gate`. Edge `fetch` (NSE event calendar, self-identifying User-Agent, raw bytes and sha256 stored in `<root>/events/<date>.json`) and `status_at` (no look-ahead). CLI: `python3 -m engine.events` |
| `engine/chain_report.py` | Edge. CLI `python3 -m engine.chain_report DATE` writes `<date>/options.sqlite`: `chain_snapshots`, `iv_history`, `runs`. Also `context_at`, the OptionContext builder that Phase 8 uses |
| `config/engine/v14.yaml` | v13 + `tiers.C {mode: full, max_tokens: 400}` + `options.*` + `events.*` + `dashboard.stale_after_s.chain` |
| `tests/engine_tests/test_options.py` | 23 tests: acceptance criteria, IV references, Greeks, chain, planner, recorder planner, recorded-chain integration |
| `docs/phase-11-evidence/` | `sources-2026-11-07.txt`, `after-hours-chain-2026-11-07.json`, `signal-dry-run-2026-11-06.json`, `preexisting-eod-failure-check.txt` |

Changed (all additive):
| File | Change |
|---|---|
| `engine/tiers.py` | `allocate(..., *, caps=None)`, a per-tier cap; `TierBook.plan` passes `tiers.<T>.max_tokens` when the config has it |
| `engine/broker.py` | `KiteSession.quote(keys, batch, rate_per_s)`: read-only GET `/quote`, batched at 500 (F-QUOTE-1) and paced at 1 req/s (F-RATE-1) |
| `engine/recorder.py` | `previous_session`, `TierCPlanner` (REST chain scan → `plan_tier_c` → `TierBook.promote(tier C)`, plan written to `<day>/tier_c_plan.json`). On config v14+ and a trading day, `_record` fetches the event calendar once and runs the planner in a daemon thread every 15 min. A planner failure is logged and futures recording carries on |
| `engine/contracts.py` | Selector V2 (see the module docstring); new optional `Candidate` fields |
| `engine/signals.py` | Default config is now v14. `SignalInputs.options/events`. The options factor comes from the chain. Opportunity Age option fields are filled |
| `engine/opportunity.py` | Field types `option_premium_change`, `option_iv_change` widened to `float \| Unavailable` |
| `engine/signal_report.py` | Builds the OptionContext and EventStatus at each decision time from recorded data (v14+) |
| `engine/eod.py` | EOD chain: `chain` step first (it needs the buffer) |
| `engine/api.py`, `engine/dashboard.py` | `GET /api/engine/chain` plus the pure `chain_view` (selected-contract comparison). The API reads v14 |
| `engine/snapshots.py` | `jsonable` recurses into dicts (Q-11-21) |
| `dashboard/web/fo-engine/panels/OptionChain.tsx`, `FoEngineTab.tsx` | Panel D (was a placeholder) |
| `scripts/launchd/com.clade.engine-recorder.plist` | `--config config/engine/v14.yaml` (repo copy only, Q-11-15) |
| tests | `test_contracts_risk.py`: V1 helper passes a V1-equivalent V2 context, and OTM expectations were added. `test_signals.py`: v14 default, new options-factor test. `test_dashboard_api.py`: EOD chain order, v14, `/chain` test. `fo-engine/tests/components.test.tsx`: panel D test |
| docs | verified-facts §14 (F-OPT-1/2, F-RATE-RBI-1, F-EVT-1), open-questions (Q-EVT-1, Q-OPT-1/2), decisions D-50…52, ledger Q-11-1…21, architecture §18 |

## 3. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| B1 | Option subscription planner, which covers:<ul><li>ATM ± N strikes</li><li>strikes near LevelMap levels</li><li>top-OI and unusual-OI-change strikes</li><li>the nearest liquid expiry + next</li><li>allocator limits</li><li>priority</li></ul> | DONE. Live from the first session after the plist reinstall (owner action) | `test_planner_respects_cap_priority_and_reasons`, `test_tier_c_planner_promotes_within_the_cap_and_writes_its_plan`, `test_allocator_never_exceeds_limits_with_option_tier` |
| B2 | Chain metrics, which cover:<ul><li>CE/PE OI, OI change with OI ages</li><li>volume, premium change, spread, depth</li><li>PCR over the strike range</li><li>concentration and its change</li></ul> | DONE | `test_chain_snapshot_metrics_hedge_and_missing_oi`, `test_snapshots_context_and_iv_history_from_recorded_rows` |
| B3a | IV from mid via Black-76; trading-calendar T; rate from config with its source; dividends documented | DONE | `test_trading_years_and_rate`, `test_iv_recovered_from_a_fresh_narrow_book_mid`. Module docstring explains why Black-76: the future already carries dividends and carry |
| B3b | Compute only with bid and ask, spread below the threshold, mid inside the bounds, and a converging solver; otherwise UNAVAILABLE; never from LTP | DONE | `test_wide_spread_option_iv_unavailable_not_computed_from_ltp`, `test_iv_unavailable_reasons` |
| B3c | Unit tests against textbook values (cited) | DONE | `test_iv_solver_matches_reference_values_within_tolerance` (Hull 1.12; Haug 1.7011), `test_greeks_match_finite_differences` |
| B3d | IV percentile vs the underlying's own recorded history; UNAVAILABLE until enough history | DONE (history store starts empty) | `test_iv_percentile_needs_history_and_ignores_the_same_day`, recorded-chain test |
| B4 | Positioning hypotheses from all four inputs; never from OI and premium alone; concentration shown as a hypothesis | DONE | `test_rising_call_oi_without_corroboration_is_uncertain_not_call_writing`, `test_each_label_needs_all_four_inputs` |
| B5 | Options factor (supportive / neutral / contradicting) replaces the UNAVAILABLE slot | DONE | `test_options_factor_states`, `test_options_factor_scored_from_the_chain_and_opportunity_age_option_fields_filled` |
| B6a | Results / board-meeting calendar from an official NSE source (URL verified); option buying within N days ⇒ REJECTED EVENT_IV_RISK; futures get a warning | DONE | F-EVT-1; `test_option_within_results_window_rejected_event_iv_risk_futures_warned`, `test_event_window_and_calendar_store` |
| B6b | Gate on IV percentile above a maximum for long options | DONE | `test_iv_percentile_gate_for_long_options` |
| B6c | Calendar unavailable ⇒ EVENT_UNVERIFIED, option candidates rejected | DONE | `test_missing_or_stale_calendar_rejects_every_option_event_unverified` |
| B7 | Selector V2: nearby OTM alternative; delta from computed Greeks; premium at stop/target by delta-gamma (method labelled); theta cost over the holding time; expiry-day sensitivity; Opportunity Age premium/IV-change fields filled | DONE | `test_otm_alternative_greeks_premium_theta_and_expiry_sensitivity`, `test_strikes_expiries_and_rollover_come_from_the_registry`, options-factor test (Opportunity Age fields) |
| B8 | Dashboard panel D: OI distribution, OI change, premium change, IV, concentrations, liquidity, hypotheses, selected-contract comparison | DONE (built and unit-tested; not deployed, owner rebuilds `dist`, Q-10-20) | `components.test.tsx` "panel D option chain", `test_chain_panel_reads_options_store_with_no_look_ahead`; `tsc --noEmit` exit 0 |
| AT1 | Wide-spread option ⇒ IV UNAVAILABLE, not computed from LTP | DONE | `test_wide_spread_option_iv_unavailable_not_computed_from_ltp` |
| AT2 | IV solver matches reference values within tolerance | DONE | `test_iv_solver_matches_reference_values_within_tolerance` |
| AT3 | Rising call OI with no premium / IV / underlying corroboration ⇒ UNCERTAIN, not call writing | DONE | `test_rising_call_oi_without_corroboration_is_uncertain_not_call_writing` |
| AT4 | Option within the results window ⇒ REJECTED EVENT_IV_RISK | DONE | `test_option_within_results_window_rejected_event_iv_risk_futures_warned` (risk_check REJECTED) |
| AT5 | Missing calendar ⇒ option candidates rejected EVENT_UNVERIFIED | DONE | `test_missing_or_stale_calendar_rejects_every_option_event_unverified` |
| AT6 | Allocator never exceeds limits with the option tier added | DONE | `test_allocator_never_exceeds_limits_with_option_tier` |
| R | Report: chain snapshots for 3 underlyings with hypotheses, IV coverage %, rejected-for-event counts | PARTIAL: real data exists only as an after-hours snapshot (empty books, no reference snapshot); see §4 | evidence files |

## 4. Real-data results

### 4.1 Chain snapshots, 3 underlyings (AFTER_HOURS REST snapshot, 2026-11-07 ~16:35 IST)

Source: `docs/phase-11-evidence/after-hours-chain-2026-11-07.json`. These are Friday 2026-11-06 closing values, read with read-only `/quote` (4 requests per underlying, paced). Expiry 2026-11-23 is the nearest one with a same-expiry future. Strikes are ATM ± 5, CE and PE. In trading-calendar years no time passes over the weekend, so Saturday's T equals T at Friday's close.

| underlying | expiry | spot LTP | ATM | rows | PCR (OI, ATM ± 5) | PCR (volume) | CE OI concentration | PE OI concentration | hypotheses |
|---|---|---|---|---|---|---|---|---|---|
| NIFTY | 2026-11-23 | ₹25,030.35 | 25050 | 22 | 0.550 | UNAVAILABLE (CE volume total 0 after hours) | 25000 (53.1 % of range) | 25000 (60.6 %) | 22 UNCERTAIN |
| RELIANCE | 2026-11-23 | ₹1,320.00 | 1320 | 22 | 0.332 | UNAVAILABLE (same) | 1300 (21.6 %) | 1300 (40.8 %) | 22 UNCERTAIN |
| HDFCBANK | 2026-11-23 | ₹788.25 | 790 | 22 | 0.582 | UNAVAILABLE (same) | 800 (24.9 %) | 750 (22.1 %) | 22 UNCERTAIN |

- **Every book was empty** (`bids=0 asks=0` on all 69 instruments). The underlying reference therefore fell back to spot LTP.
- **Every hypothesis is UNCERTAIN, as it must be:** there is no snapshot 15 minutes earlier, so OI / premium / IV / underlying changes are all UNAVAILABLE.
- **OI concentration** is shown with its strike and share. It is a hypothesis input, never "resistance".
- **These OI values count as fresh** because they were received now (Q-11-19). They are Friday's closing OI; the exchange timestamps are 2026-11-06 16:52–16:57 IST.
- The full strike tables are in the evidence file.

### 4.2 IV coverage

- **After-hours snapshot: 0 / 66 contracts (0 %) have an IV.** All 66 are NO_VALID_BOOK, because after the close the REST book is empty. This is the honest result. The IV pipeline itself is proven on synthetic recorded rows (`test_snapshots_context_and_iv_history_from_recorded_rows`: 10 / 10).
- **Recorded 2026-11-06: 0 option tokens recorded,** so there is no coverage to report. `python3 -m engine.chain_report 2026-11-06 --dry-run` printed `{"date": "2026-11-06", "config_version": "v14", "iv_history_rows": 0}` in 1.8 s.

### 4.3 Rejected for event

**Next session (calendar stored 2026-11-07 16:35 IST, VERIFIED, 610 board meetings, sha256 `3dde5225…6333`).** Long options on 2026-11-09, window through 2026-11-16 (2026-11-10 is an F&O holiday):

| outcome | underlyings |
|---|---|
| EVENT_IV_RISK (option candidates rejected; futures get a warning) | **9**: ABB (11-13 results), BAJFINANCE (11-10 other business), EICHERMOT (11-13), GRASIM (11-13), HAL (11-12), IDEA (11-12), POWERINDIA (11-12), TATAPOWER (11-11 results/other), TMPV (11-13) |
| NO_KNOWN_EVENT | 87 |
| INDEX, not gated on constituents | 1 (NIFTY) |

**Recorded 2026-11-06 under v14 (dry run, nothing written; `signal-dry-run-2026-11-06.json`, 256 s).**
- **Setups and recommendations:** 988 setups and 39 Phase 4 events, giving 86 recommendations, **all REJECTED** (as in Phase 8).
- **Options factor:** UNAVAILABLE on all 86 (NO_OPTION_CHAIN).
- **Option candidates:** 486, all NO_TRADE. **All 486 are EVENT_UNVERIFIED,** because no calendar existed before 2026-11-07. All 486 are also IV_PERCENTILE_UNAVAILABLE, NO_PREMIUM_MODEL and DATA_NOT_OK (no option quote).
- **Futures:** 81 candidates, all EXCLUDED, none for an event reason. Top reasons: CAPITAL_ABOVE_LIMIT 76 (Q-7-4), RISK_PER_LOT_ABOVE_MAX 72, SPREAD_VS_MOVE_TOO_WIDE 54.

## 5. Verified facts used

- F-OPT-1 (index options European): https://www.nseindia.com/static/products-services/equity-derivatives-bank-nifty-option-contract-specification-monthly (2026-11-07)
- F-OPT-2 (stock options European, physically settled): https://www.nseindia.com/static/products-services/equity-derivatives-individual-securities (2026-11-07)
- F-RATE-RBI-1 (91-day T-bill YTM 5.8970 %, 2026-11-04): https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63918 (2026-11-07)
- F-EVT-1 (NSE event calendar endpoint): https://www.nseindia.com/api/event-calendar (2026-11-07)
- Already verified: F-QUOTE-1/3/5/7 (`/quote` batch size, fields, pending quantities), F-RATE-1 (1 req/s), F-WS-4/5/6 (quote mode has no depth or OI, which is why tier C is full), F-WS-2 (connection limits), F-NSE-5 (2026 holidays, used for T and the event window), F-NSE-6 (User-Agent), F-INST-2 (master columns: strike, expiry, lot size).

**API usage (guardrail 5).** No kiteconnect method is newly used. `KiteTicker` is unchanged. The new REST call is a plain `requests` GET to `/quote` with repeated `i` keys. The fields read are those of F-QUOTE-3: `last_price, volume, oi, timestamp, depth.buy[]/depth.sell[] {price, quantity, orders}`. The live run in §4.1 returned exactly these.

## 6. Test output (raw)

Engine (`python3 -m unittest discover -s tests/engine_tests -t .`, 2026-11-07, a Saturday). The full raw output, including the ResourceWarnings and the progress dots, is in `phase-11-evidence/full-test-run.txt`. Below is the failure block and the summary, verbatim:
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
Ran 237 tests in 37.437s

FAILED (failures=1)

fixture storage report: {"before_bytes": {"ticks": 20480, "depth": 8192, "oi_changes": 8192, "events": 8192, "gaps": 8192, "meta": 8192, "frames.bin": 21659, "buffer.sqlite(file)": 40960, "instrument_master(csv.gz)": 235}, "A_parquet_bytes": {"ticks": 19537, "depth": 19721, "oi_changes": 4732, "events": 1298, "gaps": 716, "meta": 346}, "B_frames_zst_bytes": 1300, "replay": {"events_buffer": 202, "events_parquet": 202, "events_frames": 252, "seconds_buffer": 0.0007, "seconds_parquet_A": 0.0032, "seconds_frames_B": 0.0009, "method": "streamed passes (Q-6-5); no event list is built"}}
```
**236 of 237 pass.** The one failure is the pre-existing Q-9-24 weekend-clock test (`engine/eod.py` reads the wall clock). With the clock pinned to a weekday it passes (`phase-11-evidence/preexisting-eod-failure-check.txt`: `weekday-pinned result: PASS`).

Frontend (`cd dashboard/web && npx tsc --noEmit -p fo-engine/tsconfig.json; npx vitest run -c fo-engine/vitest.config.ts`):
```
tsc exit 0
 ✓ fo-engine/tests/isolation.test.ts (20 tests)
 ✓ fo-engine/tests/components.test.tsx (7 tests)

 Test Files  2 passed (2)
      Tests  27 passed (27)
```


## 7. Known limitations

- **No recorded option data yet.** Coverage, cadence and option feed units (Q-7-9 / Q-OPT-2) are measurable only after the first live session.
- **Weekly index options get no IV.** They have no same-expiry future, so IV is UNAVAILABLE (NO_SAME_EXPIRY_FUTURE). A put-call-parity forward was not built (Q-11-4).
- **IV coverage will be low on illiquid strikes:**
  - change-only books look stale after 5 s (Q-11-18);
  - spreads above 10 % give no IV.
- **IV percentile is UNAVAILABLE for about 20 sessions,** so long options are rejected (Q-11-7). The history ranks intraday IV against each day's last snapshot (Q-11-13).
- **Physically settled stock options** may trade away from Black-76 values near expiry (Q-OPT-1).
- **The planner's "active setups" are the previous session's** (Q-11-14). Level strikes ignore the basis.
- **The rate expires on 2026-11-25** (21 days after the auction). After that every IV is RATE_STALE until a newer auction is entered in a new config version. Nothing fetches it automatically.
- **Session hours change on 2026-12-07** (Q-3-1). The intraday fraction of T, and expiry at the close, use the single configured close (15:40).
- **The EOD weekend-clock failure is pre-existing** (Q-9-24). It fails on Saturdays and passes with the clock pinned to a weekday (`phase-11-evidence/preexisting-eod-failure-check.txt`).

## 8. Assumptions

Every assumption above is a ledger row: Q-11-4 … Q-11-21 (ASSUMED). They stand unless you answer, and they will be reported again in Phase 15.

## 9. Owner actions

1. **DONE 2026-11-07 ~17:00 IST (reinstalled at the owner's request).** Turn on live tier C (D-51): reinstall the recorder job so it runs config v14. Do this before 09:00 on a weekday, while the recorder is not running.
   ```bash
   cp scripts/launchd/com.clade.engine-recorder.plist ~/Library/LaunchAgents/ && launchctl unload ~/Library/LaunchAgents/com.clade.engine-recorder.plist; launchctl load ~/Library/LaunchAgents/com.clade.engine-recorder.plist
   ```
2. **DONE 2026-11-07 (owner request): `npm run build` + `launchctl kickstart -k` of the dashboard server; it serves the new bundle and `/api/engine/chain`.** Panel D in the running dashboard: rebuild `dashboard/web/dist` and restart `com.clade.dashboard-server`, as in Q-10-20.
3. **Before 2026-11-25:** enter the latest RBI 91-day T-bill auction in a new config version, or IV becomes RATE_STALE.
4. **DONE 2026-11-07 (owner request, D-53):** the retention archive now targets Google Drive `My Drive/EngineArchive` (config v15, EOD plist reinstalled); the last 5 sessions stay local. Check that Drive is set to *Stream files*.
