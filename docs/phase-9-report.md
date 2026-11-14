# Phase 9 report: paper trading, actual-trade tracking, live monitoring and exits

Date: built 2026-11-07 (IST, Saturday). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, decisions.md, questions-ledger.md, phase-0 … 8 reports.
Advisory and paper-trading only: no function places, modifies or cancels an order. A SIMULATED fill is arithmetic on a recorded quote.
`test_no_order_methods_in_repo_code` and `test_engine_never_uses_kiteconnect_rest_class` pass.

## 0. Headline

- **Real data: 0 paper trades.** Paper trading over every recorded session gave this result (`phase-9-evidence/run-all-sessions.json`):
  - 2026-11-05 has no Phase 8 output.
  - 2026-11-06 has 86 recommendations and **0 ENTRY_ELIGIBLE** (Phase 8 §0). The open blockers cause this: Q-6-5 (OI windows disabled), Q-7-4 (futures capital at full notional) and Q-7-8 (no options recorded).
  - No gate was loosened to manufacture trades.
- **The 5-trade list is synthetic** (Q-9-14): five fixture trades run through the real code and a temporary ledger (`phase-9-evidence/synthetic-5-trades.txt`, §5).
- **The real-data plumbing check is not a trade list.** Five of the REJECTED 2026-11-06 recommendations were replayed in memory through `paper_fill` and the monitor over the recorded ticks (`phase-9-evidence/real-data-plumbing-smoke.txt`, §6). It found one crash, now fixed and tested, and three behaviours worth your attention (Q-9-16, Q-9-17, Q-9-18).
- **Tests:** 30 new tests pass. 13 of 13 mutations of the guards are caught. The suite has 1 failure, and it is pre-existing: a Phase 1 test that reads the wall clock and fails on weekends (§8, Q-9-24).

## 1. Owner answers and interpretations

Questions were asked once, at the start (rule Q2). Rows are in [questions-ledger.md](questions-ledger.md); decisions are D-41 … D-44.
- **Q-9-1 (BLOCKING), answered: proceed.** The 16 earlier BLOCKING rows stay OPEN.
- **Q-9-2 (= Q-7-7), answered: both ledgers, checked separately.** `risk_both` runs `risk_check` on the SIMULATED state and on the ACTUAL state, never summed. A breach in either rejects. Q-7-7 is now ANSWERED.
- **Q-9-3, answered:** square-off cutoff **15:10 IST** (`monitor.squareoff_cutoff`).
- **Q-9-4, answered:** EXIT_REQUIRED when the estimated net unrealized loss is ≥ `risk.max_risk_per_trade_inr` (₹2,000, still PROPOSED Q-7-5), plus the ledger's day P&L ≤ −`risk.max_daily_loss_inr`.
- **Assumed at the start (Q-9-5 … Q-9-14):** lifecycle vs decisions, storage, fill model, tick hard stop, predefined thesis rules, staleness, in-app alerts, journal entry by API/CLI, replay running mode, and synthetic 5 trades.
- **Assumed or found during the build (Q-9-15 … Q-9-25):**
  - **Q-9-15 is BLOCKING and OPEN.** For options, the phase text conflicts with treating the contract stop as a hard stop (§7).
  - The rest are NON-BLOCKING ASSUMED.
- **Tests first (guardrail 14):** `tests/engine_tests/test_paper.py` was written before `engine/paper.py` and `engine/ledger.py`. Changes to the tests during the build:
  - The SQL scanner was tightened, because it was reading the module docstring as SQL.
  - Two tests were added after mutation checks exposed gaps (§4): `test_disconnect_with_a_fresh_book_still_shows_no_pnl` and `test_daily_loss_is_per_ledger_never_summed`.
  - One assertion was added after the real-data smoke crashed (no sized quantity ⇒ NO_FILL).

## 2. Files

| File | Purpose |
|---|---|
| `engine/paper.py` (pure, 552 lines) | `paper_fill` (buy at the ask / sell at the bid side, 5-level walk, whole lots, partial fills, no quote ⇒ `Unavailable("NO_FILL: …")`, quote snapshot stored, label SIMULATED); `Monitor` (tick rules, timers, staleness, review); `run_trades` (driver: exact-time timers, per-ledger daily loss, SIMULATED exit fills with retry, lifecycle rows checked against Phase 8 `ALLOWED`); `risk_both`; `Trade`, `Obs`, `Decision`, `Alert`, `ReviewInputs`, `Feedback`, `LifecycleRow`, `NoFill`, `Result`; `AlertSink` + `deliver` |
| `engine/ledger.py` (edge, 494 lines) | `ledger.sqlite` schema (separate `sim_*` / `actual_*` tables; shared tables keyed by ledger; INSERT only); `add_sim_trade`, `record_taken` / `record_skipped` / `record_exit` (ACTUAL journal), `record_feedback`, `InAppSink`, `store_result`; per-ledger reads `trades` / `decisions` / `alerts` / `feedback` / `lifecycle` / `summary` / `portfolio_state` (each validates the ledger name); `trade_from_payload`; replay `run_day`, `day_events` (token-filtered buffer read), `_Inputs` (Phase 6 evaluations, Phase 5 swings + VWAP, Phase 8 opposite signals); CLI |
| `config/engine/v11.yaml` | v10 unchanged + `monitor` (cutoff 15:10, review 300 s, breakeven 1.0 R, trail timeframes 3m/5m/15m) + `paper.ledger_file` (sha256 `937f4776`) |
| `tests/engine_tests/test_paper.py` | 30 tests, synthetic fixtures (no live calls) |
| `data/engine/ledger.sqlite` | created by the real-data run (empty of trades; one `runs` row per day). Gitignored data dir |
| docs | this report, `phase-9-evidence/`, questions-ledger rows Q-9-1 … Q-9-25 (+ Q-7-7 answered), decisions D-41 … D-44, architecture §16 |

No earlier interface changed, and no earlier module was edited. `git diff --stat defa774` on tracked files shows only Phase 1's `.gitignore`.
Reused as they are:
- Phase 7: `quote_problem`, `costs.fill`, `costs.round_trip`, `risk_check`
- Phase 8: `recommend`, `ALLOWED`, `IllegalTransition`, `_dir`
- `signal_report.QuoteBook` / `read`
- `contract_report.quote_from_rows`
- the `store` event builders

## 3. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| B1 | Paper fills from executable quotes at decision time: buy at ask, sell at bid, + slippage model | DONE | `test_buy_at_ask_sell_at_bid_with_quote_snapshot_and_label`, `test_touch_only_quote_fills_touch_qty_with_estimated_slippage` |
| B1 | Partial fills when depth < quantity | DONE | `test_partial_fill_when_visible_depth_is_short` (300 of 500, walked average; < 1 lot ⇒ no fill) |
| B1 | No fill if no quote | DONE | `test_no_quote_no_fill` (no quote, stale, crossed; plus no sized quantity) |
| B1 | Every fill stores the quote snapshot; labelled SIMULATED | DONE | same test (`quote.asks`, `receive_ns`, `label`); `sim_fills.quote` / `label` columns |
| B2 | Actual-trade journal: taken with fill price / qty / time, or skipped with reason; labelled ACTUAL | DONE (API + CLI; UI is Phase 10, Q-9-12) | `test_ledgers_are_separate_tables_and_queryable_separately` |
| B2 | Two ledgers in separate tables; analytics never sum them | DONE | same test + `test_no_query_joins_…` + `test_daily_loss_is_per_ledger_never_summed`; `summary()` is per ledger only |
| B3 | Every tick: hard protective stop (contract and underlying) ⇒ EXIT_REQUIRED immediately with the triggering observation | DONE (option contract stop = warning, Q-9-15) | `test_stop_breach_exits_on_the_breaching_tick_not_at_the_review`, `test_tick_equal_to_stop_exits`, `test_short_trade_stop_is_above`, `test_futures_contract_stop_is_a_hard_stop` |
| B3 | Intraday square-off cutoff | DONE (15:10, Q-9-3) | `test_squareoff_cutoff` (fires at exactly 15:10:00.000 by timer) |
| B3 | Max loss ⇒ EXIT_REQUIRED | DONE (Q-9-4) | `test_max_loss_per_trade_on_net_pnl`, `test_daily_loss_limit_on_the_ledger` |
| B3 | Every 5 min (config) and on fresh OI change: thesis re-evaluation (positioning, VWAP, structure, spread/liquidity, opposite signals, exhaustion) | DONE (positioning is UNAVAILABLE on real data: Q-4-6 / Q-6-5) | `test_review_rules`, `test_fresh_oi_change_triggers_a_review`, `test_positioning_family_needs_positioning` |
| B3 | Outputs HOLD / TIGHTEN_STOP (breakeven after +1R, trail behind a confirmed swing) / PARTIAL_EXIT_CANDIDATE (T1) / EXIT_REQUIRED (hard, time, structural) / DATA_UNAVAILABLE | DONE | `test_tighten_breakeven_trail_and_t1`, `test_review_rules` |
| B3 | Pullback vs invalidation: premium decline without structural invalidation ⇒ not EXIT_REQUIRED | DONE | `test_brief_premium_dip_with_intact_structure_holds` |
| B3 | Gross and estimated net P&L live | DONE | every `Decision` (`pnl_gross_inr`, `pnl_net_inr` = gross − Phase 7 round-trip charges at the executable mark); `test_max_loss_per_trade_on_net_pnl` |
| B4 | Every decision change emits an alert with the exact triggering observations (values + timestamps) and rule id | DONE | `test_alerts_only_on_change_with_observations_and_rule` |
| B4 | In-app delivery; interface for later channels | DONE | `InAppSink` (alerts table), `AlertSink` protocol + `deliver`; `test_alert_sink_interface`, `test_run_results_are_stored_per_ledger` |
| B5 | Feedback: taken/skipped, actual entry/exit, slippage, execution quality, behaved yes/no/partly, notes; stored only | DONE (API + CLI) | `test_feedback_is_stored_and_changes_no_config` |
| B6 | Data STALE ⇒ DATA_UNAVAILABLE, the alert says so, nothing inferred | DONE | `test_feed_disconnect_is_data_unavailable_without_pnl`, `test_disconnect_with_a_fresh_book_still_shows_no_pnl`, `test_silent_feed_goes_stale` |
| AT1 | Stop breach fixture ⇒ EXIT_REQUIRED on the breaching tick, not at the next 5-minute review | DONE | `test_stop_breach_exits_on_the_breaching_tick_not_at_the_review` (exit at +37 s; review due at +300 s) |
| AT2 | Brief premium dip with intact structure ⇒ HOLD | DONE | `test_brief_premium_dip_with_intact_structure_holds` |
| AT3 | Paper fill with no quote ⇒ no fill | DONE | `test_no_quote_no_fill` |
| AT4 | Feed disconnect ⇒ DATA_UNAVAILABLE, no fabricated P&L | DONE | `test_feed_disconnect_…`, `test_disconnect_with_a_fresh_book_…` |
| AT5 | Ledgers queryable separately; a test asserts no analytics query joins them without a type filter | DONE | `test_ledgers_are_separate_…`; `test_no_query_joins_the_ledgers_or_reads_shared_tables_without_a_ledger_filter` (AST scan of every SQL string in ledger.py and paper.py: no statement names both `sim_` and `actual_`; every read of a shared table has `ledger=?`; no f-string builds ledger SQL; no UPDATE/DELETE; ≥ 15 statements seen) |
| AT6 | Feedback submission does not change any config | DONE | `test_feedback_is_stored_and_changes_no_config` (sha256 of every file under `config/` before = after) |
| RPT | Paper trading over all recorded sessions; trade list with fills, decisions and alerts for 5 trades | PARTIAL | Real run: 0 trades (§0). 5-trade list from synthetic fixtures (§5) and a labelled real-data plumbing check (§6) |

## 4. Mutation checks (`phase-9-evidence/mutation-checks.txt`)

Each guard was broken in turn and the Phase 9 tests run, with a 60 s timeout per run. All 13 mutations were caught. The first round surfaced three findings that are now fixed:
- **"DATA_UNAVAILABLE carries the last P&L"** survived, because every gap fixture also had a stale book. Fixed with a new fresh-book disconnect test.
- **"daily loss summed across ledgers"** survived. Fixed with a new mixed-ledger test.
- **"squareoff cutoff ignored"** hung the driver's timer loop, which relied on the cutoff closing the trade. The loop was rewritten so each due time fires exactly once.

```
MUTATION tick hard stop removed (stop only at the 5-min review): exit=1 -> 4 failing
MUTATION option contract stop treated as a hard exit: exit=1 -> 1 failing
MUTATION paper fill ignores the quote check: exit=1 -> 1 failing
MUTATION DATA_UNAVAILABLE carries the last P&L: exit=1 -> 1 failing
MUTATION gap events ignored: exit=1 -> 1 failing
MUTATION daily loss summed across ledgers: exit=1 -> 1 failing
MUTATION warnings exit (opposite positioning => EXIT): exit=1 -> 3 failing
MUTATION stale price not checked: exit=1 -> 1 failing
MUTATION squareoff cutoff ignored: exit=1 -> 1 failing
MUTATION max loss per trade ignored: exit=1 -> 1 failing
MUTATION ledger name not validated: exit=1 -> 1 failing
MUTATION shared-table read without the ledger filter: exit=1 -> 1 failing
MUTATION a query over both ledgers: exit=1 -> 1 failing
restored: OK OK
```

## 5. Five trades: SYNTHETIC fixtures (not market data)

Full output: `phase-9-evidence/synthetic-5-trades.txt`. Prices are in paise, the ledger is SIMULATED, quantity is 100 units (lot 100), and fills come from fixture books.

| # | Scenario | Entry fill | Decisions → alerts (time, rule, net ₹) | Exit fill |
|---|---|---|---|---|
| S1 | Stop breach on a tick | BUY 100 @ 100010 | 11:00:37.000 EXIT_REQUIRED HARD_STOP_UNDERLYING (ltp 98990 vs stop 99000), net −1,128.22 | SELL 100 @ 98985 |
| S2 | Option premium dip to 1350 (estimate 1400), underlying above stop | BUY 100 @ 1500 (CE) | 11:05:00 HOLD NO_EXIT_RULE, net −65.73; warnings `CONTRACT_BELOW_STOP_ESTIMATE … no structural invalidation` | none (still open) |
| S3 | +1.1R, confirmed 5m swing at 100500, T1, pullback | BUY 100 @ 100010 | 11:05:00 TIGHTEN_STOP TRAIL_CONFIRMED_SWING (stop 99000 → 100500), net 980.67; 11:05:03 PARTIAL_EXIT_CANDIDATE T1_REACHED; 11:05:31 EXIT_REQUIRED HARD_STOP_UNDERLYING at the trailed stop, net 380.99 | SELL 100 @ 100495 |
| S4 | Feed gap 11:00:31 → 11:01:30 | BUY 100 @ 100010 | 11:01:30 DATA_UNAVAILABLE FEED_GAP, net UNAVAILABLE ("cannot reassess, nothing inferred, P&L unavailable"); 11:05:00 HOLD at the next review once inputs are fresh | none |
| S5 | Square-off | BUY 100 @ 100010 (15:03:20) | 15:08:20 HOLD; 15:10:00.000 EXIT_REQUIRED SQUAREOFF_CUTOFF | SELL 100 @ 100095 |

Lifecycles: S1, S3 and S5 go ENTRY_ELIGIBLE → TRIGGERED → ACTIVE → EXIT_REQUIRED; S2 and S4 stay ACTIVE.
Ledger summary: SIMULATED has 5 trades, 3 closed, realized gross −₹455.00. ACTUAL has 0, and is reported separately.

## 6. Real-data plumbing check (2026-11-06): REJECTED recommendations, in memory, NOT paper trades

Full output: `phase-9-evidence/real-data-plumbing-smoke.txt` (21.6 s). Each recommendation was replayed through `paper_fill` and `run_trades`, using `day_events` and `_Inputs` over the recorded buffer and stores. Nothing was written to the ledger.

| Underlying (Phase 8: REJECTED) | Hypothetical entry | Stream | What the monitor did |
|---|---|---|---|
| TCS LONG | BUY 225 @ ₹2,519.00 (5-level book) | 19,660 events | 25 HOLD, T1 at 12:26:03, 2 THESIS_INPUT_UNAVAILABLE (Phase 6 1m close 5 min old), EXIT MAX_LOSS_PER_TRADE at 12:42:47 (net −₹2,054.36), exit @ ₹2,511.50 |
| RELIANCE LONG | BUY 500 @ ₹1,317.30 | 15,427 | T1 at 12:27:59, 5 STALE_QUOTE ↔ HOLD flips, EXIT HARD_STOP_UNDERLYING at 12:55:53 (ltp 131400 ≤ stop 131410), exit @ ₹1,314.20 |
| HCLTECH LONG | BUY 400 @ ₹1,452.40 | 16,930 | EXIT MAX_LOSS_PER_TRADE at 12:29:12 (net −₹2,014.90), 2 min after entry |
| IOC LONG | BUY 4,875 @ ₹144.42 | 13,424 | 4 STALE_QUOTE, 10 THESIS_INPUT_UNAVAILABLE, T1, EXIT MAX_LOSS_PER_TRADE at 13:08:01 (net −₹2,199.46) |
| JINDALSTEL LONG | — | — | NO_FILL: no sized quantity. This **crashed** `paper_fill` first; it now returns NO_FILL and is tested |

What this shows (not an edge claim, and none of these were tradable):
- **Entry costs are large against the max-loss budget (Q-9-17).** Spread plus round-trip charges put a one-lot future at −₹728 (TCS), −₹856 (HCLTECH) and −₹1,225 (IOC) net on entry. That is 21–61 % of the ₹2,000 limit.
- **The book looks stale when it isn't (Q-9-16).** The recorder writes depth only on change, so a quiet but current book trips the 5 s staleness rule.
- **Reviews run much more often than every 5 minutes (Q-9-18).** Liquid futures change OI every few seconds, and each fresh change triggers a review.

## 7. Open questions (this phase)

- **Q-9-15 (BLOCKING, OPEN): the option contract stop.** Phase 7's option `contract_stop_estimate` is an APPROXIMATE premium-model value. The phase text forbids EXIT_REQUIRED on a premium decline without structural invalidation.
  - Interim: a futures contract stop is a hard tick stop. An option premium below its estimate is a warning; the underlying stop and the ₹2,000 net max-loss still cap the loss.
  - Moot until options are recorded (Q-7-8). Please confirm or change.
- **Earlier BLOCKING rows still OPEN (16, minus Q-7-7 now answered = 15):** Q-0-2, Q-0-3, Q-0-6, Q-0-7, Q-0-8, Q-1-4, Q-3-1, Q-6-2, Q-6-5, Q-7-4, Q-7-5, Q-7-6, Q-7-8, Q-7-9, Q-7-10.
  - Q-6-2 bears on this phase directly: alerts quote observation timestamps, but Phase 5 detections still carry no receive time, so the trailing-swing observation carries `confirmed_ts` as its exchange-time basis and no receive time.
  - Q-0-3 also bears on this phase: a sleeping Mac means no monitoring of actual trades at all.

## 8. Test output (raw)

The whole repo was run as `python3 -m unittest discover -s tests -v` from the repo root (full file `phase-9-evidence/full-suite.txt`); the engine suite separately in `phase-9-evidence/engine-suite.txt`. The Phase 9 tests:
```
test_alert_sink_interface ... ok
test_feedback_is_stored_and_changes_no_config ... ok
test_ledgers_are_separate_tables_and_queryable_separately ... ok
test_no_query_joins_the_ledgers_or_reads_shared_tables_without_a_ledger_filter ... ok
test_run_results_are_stored_per_ledger ... ok
test_actual_trades_get_decisions_but_no_simulated_fills ... ok
test_alerts_only_on_change_with_observations_and_rule ... ok
test_brief_premium_dip_with_intact_structure_holds ... ok
test_daily_loss_is_per_ledger_never_summed ... ok
test_daily_loss_limit_on_the_ledger ... ok
test_disconnect_with_a_fresh_book_still_shows_no_pnl ... ok
test_feed_disconnect_is_data_unavailable_without_pnl ... ok
test_fresh_oi_change_triggers_a_review ... ok
test_futures_contract_stop_is_a_hard_stop ... ok
test_max_loss_per_trade_on_net_pnl ... ok
test_monitor_is_pure ... ok
test_paper_exit_fills_at_bid_and_lifecycle_is_legal ... ok
test_positioning_family_needs_positioning ... ok
test_review_rules ... ok
test_short_trade_stop_is_above ... ok
test_silent_feed_goes_stale ... ok
test_squareoff_cutoff ... ok
test_stop_breach_exits_on_the_breaching_tick_not_at_the_review ... ok
test_tick_equal_to_stop_exits ... ok
test_tighten_breakeven_trail_and_t1 ... ok
test_buy_at_ask_sell_at_bid_with_quote_snapshot_and_label ... ok
test_no_quote_no_fill ... ok
test_partial_fill_when_visible_depth_is_short ... ok
test_touch_only_quote_fills_touch_qty_with_estimated_slippage ... ok
test_both_ledgers_checked_separately ... ok
```
Whole repo tail:
```
FAIL: test_eod_compacts_writes_cadence_and_runs_retention (engine_tests.test_storage.TestAutomation.test_eod_compacts_writes_cadence_and_runs_retention)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/turagasanthoshkumar/Clade-NSE-Skills/tests/engine_tests/test_storage.py", line 270, in test_eod_compacts_writes_cadence_and_runs_retention
    self.assertEqual(sent, ["Engine recorder DIED and did not restart"])  # fixture day has no shutdown event
AssertionError: Lists differ: [] != ['Engine recorder DIED and did not restart']
Ran 252 tests in 36.559s
FAILED (failures=1)
exit=1
```
Engine suite: `Ran 189 tests in 37.240s`, `FAILED (failures=1)`, the same test.

**The one failure is pre-existing and not caused by Phase 9 (Q-9-24).**
- It failed identically in the baseline run, before any Phase 9 file existed (2026-11-07 ~11:00).
- `engine/eod.py:44` skips health alerts on weekends using the wall clock, and 2026-11-07 is a Saturday.
- With `engine.eod`'s clock pinned to Fri 2026-11-06 15:50 IST, it passes (`phase-9-evidence/preexisting-eod-failure-check.txt`: `weekday-pinned result: PASS`).
- It was not fixed: that is Phase 1 code, outside this phase. The fix is to inject `now`.

## 9. Verified facts used

- **No new external fact.** No Kite API method or field is used: the engine's Phase 9 code never imports `kiteconnect` (grep: no `kiteconnect` / `KiteConnect` / `KiteTicker` in `engine/paper.py` or `engine/ledger.py`).
- **Quantities are in units (F-QTY-1, measured futures only).** Option units are still Q-7-9.
- **Charges** come from the existing Phase 7 schedule (F-COST-*, `costs.entries`), with UNVERIFIED caveats Q-7-1 / Q-7-2.
- **F-NSE-7 (CTS 15:15, derivatives to 15:40) was only used to describe the options** in Q-9-3. The 15:10 cutoff is an owner decision, not a fact.
- **Depth is 5 levels of pending orders, not a full book** (F-WS-5). Fills say DEPTH_5_LEVELS, or ESTIMATED_SPREAD_MULTIPLE when only the touch is known.

## 10. Known limitations

- **No real paper trade exists yet** (0 ENTRY_ELIGIBLE). Every live-path claim rests on fixtures plus the §6 plumbing check.
- **Not wired into the live recorder** (Q-9-13 / Q-9-25). The thesis review needs Phases 4–6 live (Q-4-6). The tick rules could run live but don't.
- **Positioning is always UNAVAILABLE on real data** (Q-4-6 states not persisted; Q-6-5 OI windows disabled). Families A–D would therefore get DATA_UNAVAILABLE at every review; none exist today.
- **STALE_QUOTE flapping comes from change-only depth storage** (Q-9-16).
- **`portfolio_state` has no intraday worst-P&L latch replay** (`shortcut:` comment, Q-9-20). An open trade with no stored net P&L rejects new trades.
- **Paper exits are whole-position on EXIT_REQUIRED only.** PARTIAL_EXIT_CANDIDATE is advice, not a simulated fill (Q-9-19).
- **The actual-trade journal and feedback are API/CLI only** until Phase 10.
- **Option contract stop semantics** await Q-9-15.
