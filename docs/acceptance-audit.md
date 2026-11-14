# Phase 15 acceptance audit

Date: 2026-11-07 (Saturday, IST; market closed). Branch `stack/4-setup-radar`. Nothing committed.
Phase 15 step 1 rule: **no code changes**. This file, `docs/phase-15-evidence/*`, and two read-only helper scripts
(`scripts/acceptance_audit.py`, `scripts/reverify_facts.py`) are the only additions so far. No gap has been fixed. Every gap below waits for your answer.

Advisory and paper-trading only. No order-placement function exists in `engine/` (§6). Two legacy **mock** order routes still exist in `dashboard/` (G-4).

## 0. Summary

| Check | Result |
|---|---|
| Requirement rows audited (phase 0–13 report tables) | **302**: 243 tested and passing, **59 GAP** (16 PARTIAL, 43 DONE with only a run log or evidence file as proof) |
| Gaps outside the tables | **8** (G-1 … G-5, G-10 … G-12). G-1 = traceability matrix and original spec not in the repo; G-2 = no Phase 14 |
| Engine suite (`python3 -m unittest discover -s tests/engine_tests -t .`) | 300 tests, **1 failure** (`test_eod_compacts_writes_cadence_and_runs_retention`, wall clock, Q-9-24) |
| Dashboard suite (`python3 tests/test_*.py`) | 65 tests, all pass |
| Frontend (`npx vitest run -c fo-engine/vitest.config.ts`, `tsc --noEmit` app + module, `vite build`) | 27 pass; both type-checks exit 0; build exit 0 |
| Decisions D-1 … D-60 reflected in config | All 60 have a decision; none blank. Each config-backed one was found in the live configs (v14 recorder, v15 EOD). Two caveats: G-11 and G-12 |
| Questions ledger | **14 OPEN rows (all BLOCKING): acceptance needs 0.** 145 ASSUMED rows wait for confirmation (Appendix B). 14 rows looked broken (G-10; 13 were, see §8) |
| External facts re-opened | 46 DOC rows, each URL re-opened today, **all UNCHANGED**. 33 MEASURED rows are not URL facts. Flag: F-NSE-1 expires 2026-12-06 (G-12) |
| Safety re-check (step 5) | 0 order methods in engine, scripts or fo-engine; no credential value in any log, data file, config, doc or either bundle; simulated and actual ledgers are separate (tests pass). **The legacy mock routes break the "must not exist" rule** (G-4) |
| Steps 2, 3, 4, 6 | **Not started.** Rule Q5: 14 BLOCKING rows are OPEN. Waiting for your answer (Q-15-1) |

## 1. Inputs and how the audit was done

- **Inputs read:** architecture.md, verified-facts.md, open-questions.md, decisions.md, questions-ledger.md, build-plan.md and phase-0 … phase-13 reports.
- **Missing inputs (G-1):** the phase text says "walk both tables in the traceability matrix and every requirement in the original spec". Neither is in the repo; `grep -ri traceab docs` finds nothing. Q-8-2 already records that the original spec is missing. So the audit runs against the requirement table of every phase report, which is the most complete list that exists.
- **Missing phase (G-2):** there is no `docs/phase-14-report.md` and no Phase 14 text. build-plan.md's "Phase 14 — Dashboard" was built as Phase 10 (Q-0-4, Q-8-21: the phase texts' numbering wins). Nothing in the repo identifies a Phase 14 deliverable.
- **Method:** `scripts/acceptance_audit.py` parses each report's requirement table. For every row it collects the cited test names and joins them to the verbose results of this run (`docs/phase-15-evidence/engine-suite-baseline.txt`).
  - A row that says "see 3e" or "same test" inherits the tests of the row it points to.
  - 20 rows cite their proof only in prose ("property test", "§6"). Each was matched by hand to a test name in `tests/engine_tests`; the mapping is the `HAND_RESOLVED` table in the script.
  - vitest-cited rows count as passing because 27/27 passed. Every cited engine test name resolved, so no row points at a test that no longer exists.
- **GAP rule:** a row is a GAP if its report status is not DONE, or if no automated test proves it. One cited test fails (G-3), but the reports do not cite it, so it is listed separately.
- Full matrix: Appendix D. Raw runs: `docs/phase-15-evidence/`.

## 2. Gaps (each needs your decision: fix, or accept)

The owning phase is the phase whose report holds the row.

| id | gap | owning phase | rows | proposal (nothing done yet) |
|---|---|---|---|---|
| G-1 | Traceability matrix and original spec not in the repo | — | — | Paste them; I re-run the audit against them. Until then the phase reports are the requirement list (ASSUMED, Q-15-3) |
| G-2 | No Phase 14 text, report or code | 14 | — | Tell me what Phase 14 was, or confirm it was folded into Phase 10 (ASSUMED, Q-15-4) |
| G-3 | `test_eod_compacts_writes_cadence_and_runs_retention` fails on weekends: `engine.eod.run` reads the wall clock (breaks guardrail 11) | 1 (code) / 9 (ledger Q-9-24) | — | Add an optional keyword `now=None` to `engine.eod.run`, which the test pins. This is an additive change to a Phase 1 interface, so it needs your yes |
| G-4 | Legacy mock order routes: `dashboard/api_server.py:761` `POST /api/trade/place` and `dashboard/app.py:872/1289` `handle_place_trade`. They call no broker, but they are order-shaped and echo `mode: "live"` | 0 (Q-0-6, Q-0-7, OPEN) | — | Remove both routes, plus the frontend caller if one exists. The code is protected, so this needs your yes |
| G-5 | 14 OPEN BLOCKING ledger rows (Appendix A) | 0, 1, 3, 6, 7 | — | Answer each row (Q-15-1) |
| G-6 | **Waiting on recorded sessions** (only 1 partial session exists: 2026-11-06, outage 09:03–11:26): OI cadence doc for a full day, bytes/day, the storage-format decision (Q-STORE-1), size before and after, full-day latency, staleness incidents, the 3-session structure report, the paper-trade report, the chain report, survivorship, segments | 1, 3, 5, 9, 11, 12 | 1-6, 1-7, 1-8, 1-AT7, 3-R1, 3-R2, 5-Rep, 9-RPT, 11-R, 12-Data-3, 12-St-5 | Accept as "pending data"; each re-runs with an existing CLI once sessions exist. No code needed |
| G-7 | **Waiting on decisions**: charge effective dates (Q-COST-1); margin via the Kite API (Q-7-4, OPEN); full Phase 4–8 re-run on eventually-reported OI (not built); APPROXIMATE label not visible in the UI (Q-13-9: v17 not live) | 7, 12, 13 | 7-C1a, 7-S4, 12-St-4, 13-1c | Accept, or decide the linked rows. 12-St-4 is a new build: say if you want it |
| G-8 | **Behaviour with no unit test** (code exists and runs on real data, but no fixture test asserts the values) | 1, 4, 5, 8, 10 | 1-3f (daily master snapshot), 4-F3 RVOL, 4-F4 volume/OI ratio, 4-F5 VWAP-dev/ATR move/momentum, 4-F6 basis + ABNORMAL_BASIS, 5-R3 Detection fields, 8-SC4 market context (breadth), 10-STK SSE stream, 10-A…E panels, 10-D7 | Add fixture tests only, with no behaviour change. If a test exposes a bug, I stop and report it |
| G-9 | **Deliverables proven by evidence, not tests** (docs, reports, screenshots, Phase 0 doc tasks) | 0, 3, 6, 7, 8, 10, 12 | 0-T1…A4 (17) + 0-T6 (PARTIAL: build-plan.md was a proposal, superseded by the phase texts), 3-R3, 6-R, 7-RPT, 8-RPT, 10-D8, 10-D9, 10-AT4, 10-AT6, 10-RPT, 12-St-3, 12-Val-3, 12-Rep | Accept as evidence. 10-AT6 (type-check + bundle secret scan) was **re-run today and passes** (§6). 10-AT4 (Playwright visual regression) was not re-run: it needs the built app served |
| G-10 | Ledger hygiene: Q-11-3 and Q-12-3 split on a `\|` inside code; Q-12-1 and Q-12-2 repeat the class column; Q-12-4 … Q-12-13 carry the status in the answer column and the answer in the date column | 11, 12 | — | Reformat those 14 rows with identical text, deleting nothing (ASSUMED, Q-15-7) |
| G-11 | `config/engine/v15.yaml` `retention.archive_target` contains your Google account email (the Drive mount path). Not a secret, but it is personal data in a file that would be committed | 11 (D-53) | — | Leave as is, or read the mount path from an env var (ASSUMED: leave, Q-15-8) |
| G-12 | F-NSE-1 (F&O close 15:40) is valid only until **2026-12-06**. Still no NSE implementation circular for F-NSE-9 (CTS to 15:30, derivatives to 15:45). Config `sessions.*` has a single set of values. This is Q-3-1 (OPEN) | 3 | — | Covered by Q-3-1. Before 2026-12-07, config needs dated sessions or a new version |

## 3. Decisions vs config

All 60 rows in decisions.md have a decision; **no blank decision**. One caveat: decisions.md's own source note says the owner's pasted decisions table never arrived.

Config-backed decisions, checked in the live configs. The recorder runs on v14 (`scripts/launchd/com.clade.engine-recorder.plist`), the EOD job on v15. v14 and v15 differ only in `retention.archive_target` and `version`.

| decision | config key (v15) | value | ok |
|---|---|---|---|
| D-4 disk guard | `disk_guard.alert_below_gb / stop_depth_below_gb / stop_ticks_below_gb` | 5 / 3 / 2 | yes |
| D-4 + D-53 retention | `retention.raw_sessions_local`, `retention.archive_target` | 5, Drive `My Drive/EngineArchive` | yes (G-11) |
| D-6 constituents max age | `universe.constituents_max_age_days` | 3 | yes |
| D-10 tier A modes | `tiers.A.futures_mode / spot_mode` | full / quote | yes |
| D-13 data-quality thresholds | `candles.out_of_order_window_s`, `quality.stale_*`, `baselines.sessions`, `baselines.oi_change_windows_min` | 2; 10/10/5/300; 20; [5,15,60] | yes; cash close 15:30 still known wrong (Q-3-1) |
| D-14 feed watchdog | `ws.stall_after_s` | 10 | yes |
| D-19 positioning thresholds | `positioning.*` | as proposed in v5 | yes |
| D-25 / D-31 structure, opportunity | `structure.*`, `opportunity.*` | as proposed in v6 / v7 | yes |
| D-33 VWAP-extension ATR | `opportunity.exhaustion.vwap_atr_timeframe_min` | 15 | yes |
| D-43 square-off | `monitor.squareoff_cutoff` | 15:10 | yes |
| D-44 max-loss exit | `risk.max_risk_per_trade_inr`, `risk.max_daily_loss_inr` | 2000, 6000 | yes (values PROPOSED, Q-7-5 OPEN) |
| D-51 tier C | `tiers.C` | `{mode: full, max_tokens: 400}` | yes |
| D-56 half-life | `opportunity.half_life_file / half_life_multiple` | v16+ only (not live) | yes, by design (Q-13-9) |
| D-59 / D-60 profile | `profile.*`, `depth.*` | v17 only (not live) | yes, by design (Q-13-9) |

Decisions about architecture or behaviour (D-1 KiteTicker only, D-11 no Redis, D-12 event kinds, D-34 close = stop, D-40 API auth, D-42 separate ledgers, D-45 option stop) are code, not config. Their tests pass: `test_engine_never_uses_kiteconnect_rest_class`, `test_loopback_same_origin_only`, `test_both_ledgers_checked_separately`, `test_ledgers_are_separate_tables_and_queryable_separately`.
No live config (v14, v15, v17) has a null or empty key, so no open question hides as an unset value.

## 4. Questions ledger audit

- **OPEN rows: 14, all BLOCKING** (Appendix A). The acceptance rule needs zero. Phases 8–13 each went ahead with these rows open, on your word (D-36, D-41, D-46, D-50, D-54, D-58).
- **ASSUMED rows awaiting confirmation: 145** (Appendix B), each with its assumption and the files it affects. Q-12-4 … Q-12-13 were accepted by you (D-57); their columns are broken (G-10).
- Rule Q6: an ASSUMED row you never answer stands, and is reported again here. That is Appendix B.

## 5. External facts re-verified (Appendix C)

`scripts/reverify_facts.py` re-opened every DOC URL today (2026-11-07) and checked each quoted fragment on the page.

| result | rows |
|---|---|
| quote found automatically | 38 |
| no quote on the row (field tables, byte tables, interval list, SEBI titles) | 8, each checked by hand for its key strings: all present |
| flagged by the checker | 4. All are artefacts or format changes (Appendix C): F-NSE-1 (NSE served a bot page, broker mirror re-read and the quote is present), F-NSE-5 and F-COST-2 (quote belongs to the other URL on the row, which matched), F-COST-3 (same rates, "0.035530%" format) |
| MEASURED (not URL facts) | 33 |

**No fact changed.** The one dated risk is F-NSE-1's expiry on 2026-12-06 (G-12).

## 6. Safety re-check (step 5, read-only; raw output `docs/phase-15-evidence/safety-recheck.txt`)

| check | result |
|---|---|
| Order methods (`place_order`, `modify_order`, `cancel_order`, `exit_order`, GTT, `convert_position`, `/orders`) in engine/, scripts/, fo-engine/ | 0 hits |
| `KiteConnect` REST class in engine/ | only the docstring saying it is not used; the only import is `KiteTicker` (`engine/broker.py:101`) |
| `test_no_order_methods_in_repo_code`, `test_engine_never_uses_kiteconnect_rest_class` | pass |
| Order-shaped code anywhere else | **4 hits, legacy mock routes (G-4)** |
| Token or secret passed to print/log in engine/, scripts/ | 0 |
| Real `access_token` / `api_key` values (read from `dashboard/kite_config.json`, never printed) in dashboard/logs, data, config, docs, engine, scripts, tests, .github | 0 hits in 430 files |
| `kite_config.json` committed | no: git-ignored (`.gitignore:21`); not in `git ls-files` |
| Frontend bundle: fresh build of the current source and the deployed `dashboard/web/dist` | `bundle-secrets.py`: 42 files each, no credential value, no credential keyword |
| Simulated and actual never combined | `test_ledgers_are_separate_tables_and_queryable_separately`, `test_both_ledgers_checked_separately`, `test_actual_trades_get_decisions_but_no_simulated_fills` pass |
| Not checked | the API secret lives in the macOS Keychain; reading it would prompt you, so the scan used the two values in kite_config.json only |

## 7. Steps not started

| step | state | why |
|---|---|---|
| 2 dress rehearsal | not started | rule Q5 (14 BLOCKING rows OPEN); only one recorded session exists, and it is partial |
| 3 live shadow day | yours to run | first eligible session is Mon 2026-11-09 (2026-11-08 is the Muhurat special session; its timings are not verified) |
| 4 failure drills | not started | rule Q5 |
| 6 runbook | not started | rule Q5; its troubleshooting table depends on the drill results |

## 8. Status after fixes (2026-11-07, later the same day; owner: "fix all the issues", D-61 … D-65)

| gap | now |
|---|---|
| G-1 matrix / spec missing | still missing; audit stays against the phase reports (Q-15-3) |
| G-2 Phase 14 | ASSUMED folded into Phase 10 (Q-15-4) |
| G-3 weekend-clock test | **fixed**: `engine.eod.run(..., now=None)`, test pins a Friday |
| G-4 mock trade routes | **made honest, kept**: four tabs log manual trades through it; it answers mode "mock" and "No order was sent to the broker" |
| G-5 OPEN BLOCKING rows | 14 → **11**: Q-7-4, Q-7-5 (your risk answers), Q-0-6 (G-4) answered. The 11 left need facts or choices not given |
| G-6 waiting on sessions | accepted as pending data |
| G-7 waiting on decisions | 7-S4 now runs on your 25 % margin estimate (still MARGIN_ESTIMATED, not the Kite API); 12-St-4 not built; 13-1c unchanged (v17 not live) |
| G-8 no unit test | **tests added** for 1-3f, 4-F3, 4-F4, 4-F5, 4-F6, 5-R3, 8-SC4. Still none for 10-A…E panels, 10-STK SSE, 10-D7 |
| G-9 evidence-only | accepted as evidence |
| G-10 ledger columns | **fixed**: 13 rows (Q-11-3 and Q-12-3 were not broken; their `\|` is escaped) |
| G-11 email in config | left as is (Q-15-8) |
| G-12 F-NSE-1 expiry | unchanged; runbook §6 reminds before 2026-12-07 |
| (new) signals only after the close | **fixed**: intraday job, prefix-proven (phase-15-report §3) |

Matrix re-run against the final test log (`docs/phase-15-evidence/requirements-matrix-final.md`): phases 0–13 = 302 rows, **52 GAP** (was 59; the 7 G-8 rows are now tested). Engine suite 308 tests, all pass.

## Appendix A. OPEN rows (all BLOCKING)

| id | phase | question | interim behaviour | files |
|---|---|---|---|---|
| Q-0-2 | 0 | (Q-ACCT-2) Is the headless Keychain login (`dashboard/scripts/refresh_kite_token.py`) acceptable as the engine's only session source? | Interim: the engine reuses that token; it builds no login of its own and never logs or sends the token | engine/broker.py, engine/recorder.py |
| Q-0-3 | 0 | (Q-OPS-3) Is there an always-on host, or is "Mac on charger" the operating rule? The Mac slept 09:00–09:57 on 2026-11-06 despite `caffeinate -s`. From Phase 9, a sleeping Mac means no stop alerts on trades actually taken | Interim: Mac on charger, unenforced. Gaps are recorded as gaps | scripts/launchd/*.plist |
| Q-0-6 | 0 | (Q-PROT-1) `POST /api/trade/place` (`dashboard/api_server.py:753`) is a mock, but it echoes a client `mode`, so `mode: "live"` prints "executed … in live mode". Relabel? | Interim: untouched (protected code). Nothing calls Kite | dashboard/api_server.py |
| Q-0-7 | 0 | (Q-PROT-2) Legacy `dashboard/app.py` still has `handle_place_trade` routes (same mock). Is the legacy server still needed? | Interim: untouched (protected code) | dashboard/app.py |
| Q-0-8 | 0 | (Q-PROT-3) `dashboard/zerodha_plumbing.py:30` hardcodes `LOT_SIZES` (NIFTY 75; the master says 65) and `FREEZE_LIMITS`; `test_lot_size_validation` locks in the stale 75. Fix or retire? | Interim: untouched (protected code). The engine never reads it (guardrail 6) | dashboard/zerodha_plumbing.py, tests/test_dashboard_and_plumbing.py |
| Q-1-4 | 1 | Phase 1 interface deviations from the Phase 0 plan (`Recorder` signature, per-date storage instead of `engine.db`, `replay()` signature), architecture §8, "for owner review"; never signed off | Interim: built and used by Phases 2–8 | docs/architecture.md §8, engine/recorder.py, engine/replay.py, engine/store.py |
| Q-3-1 | 3 | (Q-NSE-7) Session hours: F&O stocks' CTS ends 15:15 now (CAS to 15:35); from 2026-12-07 CTS to 15:30, derivatives to 15:45, expiring index contracts 15:30. Config `sessions` is a single value. How to model date-effective sessions? Phase 9's square-off cutoff depends on it | Interim: single session values (cash close wrong now; F&O wrong from 2026-12-07) | config `sessions` / `market_hours`, engine/candles.py, engine/universe.py |
| Q-6-2 | 6 | (Q-OPP-4) Guardrail 8: Phase 5 detections carry only candle-close times (no source, receive or processing timestamps, no age). Adding them changes the Phase 5 `Detection` interface. Phase 9 alerts must quote observations with their timestamps | Interim: Phase 6 evaluations carry the full timestamps for their price input only | engine/structure.py, engine/opportunity.py |
| Q-7-4 | 7 | (Q-RISK-1) Futures margin is MARGIN_ESTIMATED at full notional (`contracts.futures_margin.fraction: 1.0`), so no future fits the ₹1,00,000 per-trade limit. Add the Kite margin POST to `engine/broker.py`, or give a sourced lower fraction? | Interim: full notional ⇒ every future fails capital | engine/broker.py, engine/contracts.py, config v9/v10 |
| Q-7-5 | 7 | (Q-RISK-2) Every `contracts.*` / `risk.*` value is PROPOSED: capital ₹2,00,000, 20 % reserve, ₹1,00,000 per trade, ₹2,000 risk per trade, ₹6,000 daily loss, 3 open, 5 trades/day, 3 losses ⇒ 60 min cooldown, spreads 0.05 % / 2 %, spread ≤ 20 % of move to T1, net R:R ≥ 1.5, slippage 0.05 % / 2 %, volume 200 / 1,000 lots, OI 500 lots, depth ≥ 1 × order, cutoff 15:00, min DTE 2, premium model 30/20/R² 0.5, no-depth slippage 1 × spread, gap risk 1 ATR | Interim: the proposed values are in use | config v9/v10 `contracts` / `risk`, engine/risk.py, engine/contracts.py |
| Q-7-6 | 7 | (Q-RISK-3) No event calendar: `risk.event_days: []`, so EVENT_DAY blocks nothing (Phase 8 did not build one, Q-8-17) | Interim: an empty list, i.e. no day is blocked as an event day | config `risk.event_days`, engine/risk.py |
| Q-7-8 | 7 | (Q-CON-1) No option contract has ever been recorded; tier C is unused. Which strikes and expiries go into tier C, and from when? | Interim: every option candidate is NO_TRADE (NO_PREMIUM_MODEL + NO_QUOTE) | engine/tiers.py, engine/recorder.py, config |
| Q-7-9 | 7 | (Q-CON-2) Option quantities are assumed to be in units, like futures (F-QTY-1 measured futures only). Sizing depends on it | Interim: units, unverified; moot while Q-7-8 is open | engine/contracts.py |
| Q-7-10 | 7 | (Q-CON-3) Phase 0's planned `select_contract(...)` / `size_position(...)` were never built; Phase 7 built `select_contracts(...)` and `risk_check(...)`. Replace the Phase 0 entries in architecture §5? | Interim: Phase 7 shapes in use; no built interface changed | docs/architecture.md §5, engine/contracts.py, engine/risk.py |

## Appendix B. ASSUMED rows awaiting your confirmation (145)

| id | phase | question | assumption in force | files affected |
|---|---|---|---|---|
| Q-0-1 | 0 | (Q-ACCT-1) Which Kite Connect plan is this? Streaming is proven (F-WS-10) and historical too (F-ACCT-1); the plan name is not | The plan name does not matter while streaming and historical data both work | — |
| Q-0-4 | 0 | (Q-OPS-5) The texts for Phases 1–14 were never supplied together; build-plan.md is a proposal | Each pasted phase text wins over build-plan.md (see Q-8-21 for the numbering) | docs/build-plan.md |
| Q-0-5 | 0 | (Q-NSE-3) Which charges schedule is authoritative? backtest-expert and the lab schedule disagree | Neither: the verified F-COST-* schedule in `config/engine/v9.yaml` `costs.entries` (Phase 7); both old schedules are stale for 2026. Remaining gaps: Q-7-1, Q-7-2 | engine/costs.py, config v9/v10 |
| Q-0-9 | 0 | (Q-HIST-1) Max request range for 10/15/30-minute historical data | Not used by any phase; measure if needed | — |
| Q-0-10 | 0 | (Q-HIST-2) Is `continuous=1` stock-future OI reliable before each name's earliest date, and are roll days marked? | The engine does not use continuous data | — |
| Q-0-11 | 0 | (Q-HIST-3) The 2026-11-03 swing backtest's "OI only from 2025-01" claim is wrong (NIFTY from 2016, F-HIST-6) | Flag only: the protected module was not edited and its conclusions were not re-run | dashboard/swing_backtest.py |
| Q-0-12 | 0 | (Q-HIST-4) Are expired option contracts' candles retrievable at all? | Unknown; nothing relies on them | — |
| Q-0-13 | 0 | (Q-HIST-5) Does OI = 0 in early continuous rows mean missing data or a real zero? | Treated as UNAVAILABLE; not used by any phase | — |
| Q-0-14 | 0 | (Q-NSE-1 / Q-WS-1) Official OI cadence, and the measured tick/OI cadence on the feed | Measured cadence only (`docs/measured-oi-cadence.md`). Without that doc every OI window is disabled, and the doc has never been written (Q-6-5) | engine/oi_cadence.py, engine/positioning.py |
| Q-0-15 | 0 | (Q-REG-1) SEBI/NSE retail-algo changes after April 2026 | Context only: advisory and paper only, no orders | — |
| Q-0-16 | 0 | (Q-WS-4) Text frames on the socket other than `instruments_meta` | Every text frame is stored in `events` | engine/recorder.py |
| Q-1-1 | 1 | (Q-STORE-1) Long-term raw format: A (Parquet, change-only ticks) or B (zstd raw frames)? Parquet replay was 10–100× slower at fixture size | Both are written until a full session is measured | engine/compact.py |
| Q-1-2 | 1 | (Q-STORE-2) "Duplicates stored as received" vs "skip unchanged ticks": if format B is retired, exact duplicate frames disappear | Both stores are kept, so nothing is lost. Retiring B deletes raw data and will be asked as BLOCKING first | engine/recorder.py, engine/compact.py |
| Q-1-3 | 1 | (Q-STORE-3) The instrument master is kept forever (~0.6 GB/yr). Keep, or store diffs? | Kept forever (no deletion) | engine/universe.py |
| Q-1-5 | 1 | "Instrument family" for Parquet partitioning was undefined | The master `segment` (`NFO-FUT`, `NSE`, `INDICES`) | engine/compact.py |
| Q-1-6 | 1 | The REST adapter has no rate limiter | Phase 1 makes 2 REST calls per run; add a limiter when a phase calls REST in a loop | engine/broker.py |
| Q-1-7 | 1 | Disk-guard unit | GB = 10^9 bytes | engine/recorder.py |
| Q-2-1 | 2 | (Q-UNI-1 / Q-UNI-3) The no-ban `fo_secban.csv` format and whether the 08:35 refresh sees today's date have never been observed | Header-only = no bans; any other form, or yesterday's date ⇒ RESTRICTION_UNVERIFIED (not tradable) | engine/universe.py |
| Q-2-2 | 2 | (Q-NSE-5) No source says there is no session on weekends; the 2026-11-08 Muhurat timings are not notified | Weekends and Muhurat ⇒ RESTRICTION_UNVERIFIED (not tradable) | engine/universe.py, config |
| Q-2-3 | 2 | (Q-NSE-6) The 2027 F&O holiday circular (due ~Dec 2026) is not in config | Every 2027 date is RESTRICTION_UNVERIFIED (nothing tradable) until it is added | config `holiday_years` / `holidays` |
| Q-2-4 | 2 | Spot rows are not checked against the F&O ban list | BANNED applies to NFO contracts only | engine/universe.py |
| Q-2-5 | 2 | A new amending holiday circular is not detected automatically | Config dates + a daily checksum of the known circulars; a new circular must be added by hand | engine/universe.py |
| Q-2-6 | 2 | NSE files fetched with a self-identifying User-Agent; the NSE JSON holiday API is not used (the cookie route was blocked as bot-check circumvention) | Official circular PDFs only | engine/sources.py |
| Q-3-2 | 3 | (Q-QUAL-1) `quality.stale_price_s: 10` marks far/next-month futures STALE very often (change-only ticks). Make staleness per instrument kind? Linked: Q-4-2, Q-5-4, Q-6-3 | Strict 10 s for every instrument (more STALE, fewer signals) | config `quality`, engine/candles.py |
| Q-3-3 | 3 | (Q-STORE-4) Compressed snapshot size after EOD compaction | To measure at the first EOD that completes (blocked by Q-6-5) | engine/snapshots.py |
| Q-3-5 | 3 | Chosen, not asked: `candles.finalize_delay_s: 15`; VWAP = the exchange `atp`, not recomputed; trade-count proxy = ticks where cumulative volume rose; OI-change baseline in % (OI ≤ 0 skipped); candle quality measured at the candle close | As listed | engine/candles.py, engine/baselines.py, config v4+ |
| Q-3-6 | 3 | A gap marks every instrument's overlapping candles PARTIAL, whatever its connection | Conservative while there is one connection; `shortcut:` noted for > 1 | engine/candles.py |
| Q-3-7 | 3 | Baselines with fewer than N = 20 sessions are stored as they are; consumers must read `n_sessions` | Thin baselines are stored and used, with `n_sessions` attached | engine/baselines.py |
| Q-4-1 | 4 | (Q-CFG-2) The global `engine.config.DEFAULT_PATH` is still v4; each phase loads its own version (v5 … v10) | Unchanged; each module names its own config | engine/config.py |
| Q-4-2 | 4 | (Q-POS-1) Combined OI is DEGRADED (primary view OI_STALE) whenever a far month's OI is unchanged ≥ 300 s. Decide with Q-3-2 | Strict (owner kept it, D-22) | engine/positioning.py |
| Q-4-3 | 4 | (Q-POS-2 / Q-STR-1) Nothing refreshes `history.sqlite` daily: distributions age, `*_prev_close_pct` and PDH/PDL/PDC/PWH/PWL become UNAVAILABLE on later days. Schedule `engine.backfill` in EOD? | Not scheduled; missing values are UNAVAILABLE, never stale values | engine/backfill.py, engine/eod.py |
| Q-4-4 | 4 | (Q-POS-3) Sector residual: no official sector mapping in verified-facts | Skipped (phase text) | engine/positioning.py |
| Q-4-5 | 4 | (Q-POS-4) ROLLOVER_WINDOW reading | Suppress the near-month view; only flag the combined views | engine/positioning.py |
| Q-4-6 | 4 | (Q-POS-5 / Q-STR-6) Phases 4–8 run as batch CLIs after the close; nothing is live and Phase 4 states are not persisted. Phase 9's 5-minute thesis re-evaluation needs them live | Batch only (no live signals at all) | engine/positioning.py, engine/structure.py, engine/opportunity.py, engine/signals.py |
| Q-4-7 | 4 | Chosen, not asked: an OI step during a recorder gap is unchecked; unmeasurable liquidity ⇒ INSUFFICIENT_DATA (not ILLIQUID_FUTURE); a STALE EMPTY minute counts as 0 trades; cadence per series = max over recorded dates; distributions fixed for the day (no same-day lookahead) | As listed | engine/positioning.py, engine/oi_cadence.py |
| Q-4-8 | 4 | Previous-session close OI comes from the history store's last minute, not the exchange's closing OI | Last history minute | engine/positioning.py |
| Q-4-9 | 4 | ATR mixes history 5-minute bars (from Kite minutes) with tick-built candles until 14 of today's exist (also Phase 5) | Mixed sources | engine/positioning.py, engine/structure.py |
| Q-5-1 | 5 | (Q-CNDL-1) Phase 3 never finalizes the last minute: no candle ends at 15:40 (last 1m 15:38–15:39; the final 5m/15m buckets are missing). Fix in Phase 3? | Missing bars stay missing; the EOD LevelMap price is the 15:38 close | engine/candles.py |
| Q-5-2 | 5 | (Q-STR-3) COMPLETE bars marked STALE or DEGRADED are unusable (≈ 4 % of near-month 3m bars, mostly illiquid names) | Strict; revisit with Q-3-2 | engine/structure.py |
| Q-5-3 | 5 | (Q-STR-4) LevelMap gives distance in every timeframe's ATR and picks none; swept or broken swings remain obstacles | As built; Phase 6 uses the setup-timeframe ATR (15m for VWAP extension, D-33) | engine/structure.py, engine/opportunity.py |
| Q-5-4 | 5 | (Q-STR-5) CHoCH rule: in an UP (DOWN) trend, the first close below (above) the last confirmed swing low (high), at most one per trend state. Labelled HEURISTIC | As built | engine/structure.py |
| Q-5-5 | 5 | Chosen, not asked (structure rules): no in-progress candle; pivot 2/2 (right side non-strict); trend from the last swing labels; one BOS per swing; one consolidation box per timeframe; acceptance = N consecutive closes / hold M min; failure = close back inside within K bars; sweep = wick beyond a level + close back inside within K bars; equal highs/lows clustered within 0.10 ATR; zones = ≤ 3 base bars (body ≤ 0.5 ATR) before an impulse (body ≥ 1.5 ATR); reclaim = 2 contiguous closes; VWAP extension flag at ≥ 2 ATR; a pending breakout/sweep cut by a gap is dropped without an event | As listed (phase-5-report §0) | engine/structure.py, config v6 |
| Q-6-1 | 6 | (Q-OPP-3 / Q-CON-4) Phase 6 R:R is gross (`current_rr_net` NET_UNAVAILABLE); Phase 7's net check then rejects setups Phase 6 passed (one NIFTY lot 0.07 net) | Phase 6 stays gross; net R:R is judged in Phase 7/8 | engine/opportunity.py, engine/risk.py |
| Q-6-3 | 6 | (Q-OPP-5) MFE/MAE require every 1m bar in the horizon to be usable; 5,265 of 20,181 rows are UNAVAILABLE | Strict; revisit with Q-3-2 | engine/opportunity.py |
| Q-6-4 | 6 | (Q-OPP-7) No Phase 4 positioning setups exist on real data (OI windows disabled, Q-6-5) | Wiring proven on a fixture event only | engine/opportunity.py |
| Q-6-6 | 6 | Interpretations: a setup is evaluated at every 1m close until 15:40 / invalidation / retest expiry; retest expiry ends the setup; precedence UNKNOWN > EXHAUSTED > TIMELY / VALID_BUT_LATE; no obstacle in the trade direction ⇒ R:R undefined ⇒ UNKNOWN | As listed (the more conservative reading) | engine/opportunity.py |
| Q-6-7 | 6 | Interpretations (retest): entered by a 1m close inside the zone, not a wick; one plan at a time; zone = the nearer of the broken level and the setup VWAP strictly between stop and price, else NO_VALID_LEVEL | As listed | engine/opportunity.py |
| Q-6-8 | 6 | Interpretations (exhaustion): OI progress falling strictly over 3 × 15m windows with OI expanding in all three; RVOL falling strictly while price rises strictly; ≥ 3 SWING/SWEEP/BREAKOUT_FAILED detections within 0.1 ATR of the obstacle; high-volume-zone check always skipped (no volume profile); window features only for `window_min` 15 | As listed | engine/opportunity.py, config v7/v8 |
| Q-6-9 | 6 | Interpretations (measurement): pre_signal_move_atr against the 1m close 5 setup bars earlier; time to target/invalidation at 1m-close resolution, UNAVAILABLE after an unusable bar | As listed | engine/opportunity.py |
| Q-6-10 | 6 | The Phase 6 CLI recomputes Phase 4 and stamps those states v7 (same values as v5), so the recorded config version is not the one the values were first computed under | Same values, restamped; accepted while Phases run as batch | engine/opportunity.py |
| Q-7-1 | 7 | (Q-COST-1) Brokerage, exchange, SEBI, stamp, IPFT and GST rates have no official effective date; `effective_from` = the read date 2026-11-06 | Any earlier trade date is costed UNVERIFIED and fails NET_RR_VERIFIED (fewer candidates) | config v9/v10 `costs.entries`, engine/costs.py |
| Q-7-2 | 7 | (Q-COST-2) zerodha.com/charges: SEBI "reduced to ₹15 per crore once the regulator announces a date"; ₹15 is not a reduction from ₹10 | Config keeps ₹10 / crore. Note: ₹15 would be the more conservative (costlier) value | config v9/v10 `costs.entries` |
| Q-7-3 | 7 | (Q-COST-3) Check costs against Kite's virtual contract note (`POST /charges/orders`)? Contract-note rounding is not modelled | Not wired (it would add a POST to the GET-only adapter) | engine/broker.py, engine/costs.py |
| Q-7-11 | 7 | Slippage model: entry = walked fill on the executable side; exit slippage at stop / T1 = the decision-time book's other side (ESTIMATED; the real book at a stop is usually worse); more than 5 levels needed ⇒ ILLIQUID:DEPTH; no depth ⇒ 1 × spread per side | As listed | engine/contracts.py |
| Q-7-12 | 7 | Option pricing: EMPIRICAL_DELTA_OLS (30 bars, ≥ 20 pairs, R² ≥ 0.5, APPROXIMATE, premium floored at 0); ATM = strike nearest spot, tie ⇒ ITM; no Black-Scholes (no reliable IV); rollover (DTE ≤ 3) ⇒ next month with BASIS_ASSUMED_CONSTANT | As listed | engine/contracts.py |
| Q-7-13 | 7 | Sizing and capital: lots = the most whose risk (net of round-trip costs and exit slippage, fill re-walked per size) ≤ max risk; option `required_capital_inr` = premium × qty, while the capital checks use premium + costs | As listed | engine/contracts.py, engine/risk.py |
| Q-7-14 | 7 | Daily-loss latch: `worst_day_pnl_inr` = the lowest realized + unrealized seen today, tracked by the caller; a breach stays for the day even if P&L recovers | As listed | engine/risk.py |
| Q-7-15 | 7 | Liquidity score = min(1, visible executable depth / (5 × qty)) × max(0, 1 − spread % / max spread %); volume and OI thresholds in lots (feed units ÷ lot size) | As listed | engine/contracts.py |
| Q-7-16 | 7 | Cost scope: one executed order per leg for brokerage; exercise STT not modelled (V1 exits before expiry); IPFT included | As listed | engine/costs.py |
| Q-8-10 | 8 | Is CONFLICTING_EVIDENCE a gate? | No: a classification only. The phase's gate list is followed exactly. A setup whose raw / near-month positioning view or a later BOS/CHOCH opposes it is labelled CONFLICTING_EVIDENCE, and its gates decide its status | engine/signals.py |
| Q-8-11 | 8 | Classification precedence and non-TIMELY evaluations | NO_TRADE (no defensible stop / target / R:R) > UNCERTAIN (DATA_QUALITY failed) > CONFLICTING_EVIDENCE > the family label. Phase 6 EXHAUSTED and UNKNOWN fail TIMELINESS ⇒ REJECTED. WAIT_FOR_RETEST only when VALID_BUT_LATE is the **only** failed gate | engine/signals.py |
| Q-8-12 | 8 | How points are given inside a factor | Each factor's weight is split equally across its parts. futures_positioning: buildup in the trade direction = full, covering / unwinding = `covering_fraction`. volume_vwap: RVOL (continuation) or the sweep's rejection RVOL (reversal) at or above its family threshold; price on the trade side of the setup-timeframe VWAP. structure: setup direction; a BOS/CHOCH in the trade direction after the setup. profile_depth: volume profile UNAVAILABLE; visible-depth part = Phase 7 liquidity score. broad_market: index trend, breadth, index positioning. A counter-direction score has no candidate (depth part UNAVAILABLE) | engine/signals.py |
| Q-8-13 | 8 | When does a non-terminal signal end? | ENTRY_ELIGIBLE ⇒ EXPIRED (NO_LONGER_TIMELY) at the first later evaluation that is not TIMELY. Every non-terminal state ⇒ EXPIRED at `risk.intraday_cutoff` (15:00) and at the session close; INVALIDATED / EXPIRED follow Phase 6 INVALIDATED / RETEST_EXPIRED | engine/signals.py |
| Q-8-14 | 8 | Broad-market inputs | Index trend = latest Phase 5 BOS/CHOCH on the index near-month future at `signals.market.trend_timeframe_min` (15m). Breadth = share of universe near-month futures whose usable 1m candle closing **at** as_of is above that candle's session VWAP (F-QUOTE-6 average traded price), UNAVAILABLE below 20 underlyings. Index futures positioning = the index's Phase 4 primary hypothesis | engine/signals.py, engine/signal_report.py |
| Q-8-15 | 8 | Format of the stored recommendation inputs | zlib + pickle of the `SignalInputs` object (exact replay), written and read only by the engine; the recommendation itself is stored as JSON | engine/signal_report.py |
| Q-8-16 | 8 | Standalone observations | POSSIBLE_EXHAUSTION: one per Phase 6 setup (any family), at its first flagged ACTIVE evaluation. SUSPECTED_ACCUMULATION / _DISTRIBUTION: checked at every 15m mark from the open; every positive mark is stored | engine/signal_report.py |
| Q-8-17 | 8 | Q-RISK-3 said the event calendar is "Phase 8's job", but this phase text's gate list has no event gate | Not built (scope rule 15). `risk.event_days` stays empty, so EVENT_DAY still blocks nothing; Q-RISK-3 stays OPEN | — |
| Q-8-18 | 8 | E/F need a BOS/CHOCH after the sweep, and by then every E/F setup on 2026-11-06 was LATE / EXHAUSTED. Since REJECTED is terminal (Q-8-3), a setup rejected while LATE for another reason (e.g. capital) never gets a retest | Keep it: REJECTED is terminal, and only "TIMELINESS alone failed" waits for a retest (fewer candidates). Masked today by Q-7-4 | engine/signals.py |
| Q-8-19 | 8 | SPREAD_VS_MOVE_TOO_WIDE (20 %) failed 70 of 86 recommendations: sweep targets are close, so one tick is a large share of the move | Keep 20 % (a Q-7-5 value) | config `risk` |
| Q-8-20 | 8 | `signals.sqlite` is INSERT OR IGNORE per config version: re-running changed code under the same version keeps the old rows. Once in Phase 8 a derived store created minutes earlier was deleted and regenerated | Rule: bump the config version whenever logic changes. Only derived stores are ever regenerated | engine/signal_report.py |
| Q-8-21 | 8 | Earlier answers send the paper ledger and paper fills to "Phase 11" (Q-8-3, Q-RISK-4: build-plan.md numbering), but the Phase 9 text builds paper trading | "Phase 11" in earlier rows means "the phase that builds the paper ledger" = Phase 9 | docs/build-plan.md |
| Q-10-4 | 10 | Where the dashboard module lives and how its CSS is isolated | `dashboard/web/fo-engine/` (outside the main Tailwind content glob `./src/**`, so the app's compiled CSS stays byte-identical); own Tailwind config, prefix `fo-`, `important: '[data-fo-engine]'`, preflight off, loaded by `@config`. Existing-file edits: one lazy import in `App.tsx`, one row in `TabNav.tsx`, one `include_router` in `api_server.py` | dashboard/web/fo-engine/*, App.tsx, TabNav.tsx, api_server.py |
| Q-10-5 | 10 | New npm dependencies (none upgraded). Verified on the npm registry 2026-11-07 | `lightweight-charts@4.2.3`; `@fontsource/inter`, `@fontsource/jetbrains-mono` (local files, no Google request); dev: `vitest@2.1.9` (Vite 5 compatible), `@testing-library/react`, `jsdom`, `@playwright/test`. Exact versions pinned at install | dashboard/web/package.json |
| Q-10-6 | 10 | Light/dark theme source for the module | Mirror the app's existing `data-theme` from JS onto the module root; no global selector | dashboard/web/fo-engine/* |
| Q-10-7 | 10 | Phase 4 states are not persisted (Q-4-6), but Panels A and C need them | A dashboard export CLI writes a derived read model `<date>/dashboard.sqlite` (INSERT OR IGNORE, config-versioned); Phases 4–8 code untouched | engine/ (new export module) |
| Q-10-8 | 10 | Live transport | REST for every panel + one SSE stream for system health / data-age heartbeat (Phases 4–8 are batch-only; nothing else to push) | engine/api.py |
| Q-10-9 | 10 | Visual-regression method (existing tabs poll live data, so raw screenshots are never identical) | Playwright with `/api/*` stubbed and the clock frozen, before and after; the new nav entry is the one expected, explained difference | tests (web) |
| Q-10-10 | 10 | Replayed session for screenshots | 2026-11-06 (the only Phase 3+ session) | — |
| Q-10-11 | 10 | Opportunity Radar default view | REJECTED hidden by default (fewer candidates shown); on 2026-11-06 the radar is empty until "show rejected" is on (all 86 recommendations REJECTED) | dashboard/web/fo-engine/* |
| Q-9-5 | 9 | Lifecycle vs monitor decisions | Phase 8 `ALLOWED` unchanged: a fill moves ENTRY_ELIGIBLE → TRIGGERED → ACTIVE; only EXIT_REQUIRED moves the lifecycle on. HOLD / TIGHTEN_STOP / PARTIAL_EXIT_CANDIDATE / EXIT_REQUIRED / DATA_UNAVAILABLE are a separate append-only decision stream; WEAKENING unused | engine/paper.py |
| Q-9-6 | 9 | Storage | `data/engine/ledger.sqlite` (new): separate `sim_*` and `actual_*` tables + `monitor_decisions`, `alerts`, `feedback`. Never `journal.db` | engine/ledger.py |
| Q-9-7 | 9 | Paper fill model | Phase 7 executable quote + 5-level walk; partial fill = what visible depth holds, no resting order simulated; no quote ⇒ no fill | engine/paper.py |
| Q-9-8 | 9 | Hard stop on ticks | A tick price at or through the underlying's structural stop, or the contract stop, ⇒ EXIT_REQUIRED on that tick (equal counts, as D-34) | engine/paper.py |
| Q-9-9 | 9 | Predefined thesis rules | Breakeven at +1R; trail behind a Phase 5 confirmed swing; PARTIAL_EXIT_CANDIDATE at T1; structural exit = a 1m close through the stop. Opposite signals, exhaustion, VWAP flip, spread widening ⇒ HOLD with warnings, never an exit. Thresholds in config v11 | engine/paper.py, config v11 |
| Q-9-10 | 9 | Stale data | Price older than `quality.stale_price_s` ⇒ DATA_UNAVAILABLE; P&L UNAVAILABLE, never the last value | engine/paper.py |
| Q-9-11 | 9 | Alert delivery | "In-app" = the `alerts` table, behind an `AlertSink` interface; the existing phone channel is not used for these | engine/paper.py, engine/ledger.py |
| Q-9-12 | 9 | Actual-trade journal and feedback entry | Python API + CLI only; the UI is Phase 10 | engine/ledger.py |
| Q-9-13 | 9 | Running mode | Pure monitor over an event stream (same code live and replay), run as a replay over recorded sessions; not wired into the live recorder (as Q-8-4) | engine/paper.py |
| Q-9-14 | 9 | The report asks for 5 trades, but recorded data has 0 ENTRY_ELIGIBLE recommendations | The real-data run reports 0 paper trades. The 5-trade list comes from synthetic fixtures, labelled SYNTHETIC. No gate is loosened | docs/phase-9-report.md |
| Q-9-16 | 9 | Real-data smoke: STALE_QUOTE (book older than `quality.stale_depth_s` 5 s) fires every few minutes on liquid futures, because the recorder writes depth only on change (≤ 1/s, Phase 1 step 9): an unchanged book has no new row, so it looks old | Strict, as Q-3-2: DATA_UNAVAILABLE, left only at the next review (≤ 1 alert pair per review interval). Revisit with Q-3-2 (per-kind staleness, or treat a full-mode tick as confirming an unchanged book) | engine/paper.py, config `quality` |
| Q-9-17 | 9 | Real-data smoke: on entry, spread + round-trip charges alone put a one-lot stock future at −₹420 … −₹1,225 net (TCS −₹728, HCLTECH −₹856, IOC −₹1,225), i.e. 21–61 % of the ₹2,000 `risk.max_risk_per_trade_inr`, so MAX_LOSS_PER_TRADE fires on small adverse moves (3 of 4 smoke positions) | Kept as the owner set it (Q-9-4); the value itself is still PROPOSED (Q-7-5) | config `risk` |
| Q-9-18 | 9 | "On each fresh OI change" re-evaluates the thesis: on liquid futures OI changes every few seconds, so reviews run far more often than every 5 minutes (TCS smoke: 25 reviews in 27 min) | As the phase text says. Decisions are all stored; alerts fire only on a change | engine/paper.py |
| Q-9-19 | 9 | Paper exits | The paper broker exits only on EXIT_REQUIRED, the whole open quantity at the bid (sell) / ask (buy) of the book at that moment; a partial or no fill is retried on each later book event and every NO_FILL is stored. PARTIAL_EXIT_CANDIDATE and TIGHTEN_STOP are recorded, not simulated as fills | engine/paper.py |
| Q-9-20 | 9 | Ledger PortfolioState details | Realized = exit fills net of round-trip charges; unrealized = each open trade's latest stored net P&L; an open trade without one ⇒ state UNAVAILABLE ⇒ `risk_both` rejects (fewer trades). `worst_day_pnl_inr` = the current day P&L (no intraday latch replay; `shortcut:` comment). Futures capital = notional × `contracts.futures_margin.fraction` | engine/ledger.py |
| Q-9-21 | 9 | Critical thesis inputs (DATA_UNAVAILABLE when missing) | Fresh price-token tick, fresh contract tick, fresh contract book, Phase 6 setup state, a Phase 6 1m close no older than one review interval, and the positioning hypothesis only for families A–D (as Q-8-9). Opposite positioning, VWAP side, exhaustion, spread and opposite signals are warnings | engine/paper.py |
| Q-9-22 | 9 | Where Phase 9 lifecycle transitions go | `ledger.sqlite` table `lifecycle` (with a ledger column), checked against Phase 8 `ALLOWED`; Phase 8's `signals.sqlite` is not written | engine/ledger.py |
| Q-9-23 | 9 | `risk_check` rejects a candidate whose config version differs (CONFIG_VERSION check), and Phase 8 candidates are v10 | `risk_both` is called with the candidate's own config (v10); `risk.*` in v11 is byte-identical to v10 | engine/ledger.py |
| Q-9-24 | 9 | Pre-existing failure: `test_eod_compacts_writes_cadence_and_runs_retention` reads the wall clock (`engine/eod.py`: no health alerts on weekends); 2026-11-07 is a Saturday. With the clock pinned to a weekday it passes (`phase-9-evidence/preexisting-eod-failure-check.txt`) | Not fixed (Phase 1 code, outside this phase). Fix = inject `now` into `engine.eod.run` (guardrail 11) | engine/eod.py, tests/engine_tests/test_storage.py |
| Q-9-25 | 9 | The paper monitor is not wired into the live recorder, so no live alerts reach a trade the user actually takes (with Q-0-3, a sleeping Mac stops everything anyway) | Replay only (Q-9-13). Wiring it live needs Phases 4–6 live (Q-4-6) for the thesis review; the tick rules alone could run live | engine/paper.py, engine/recorder.py |
| Q-10-12 | 10 | Dashboard thresholds have no external source | PROPOSED in `config/engine/v12.yaml` `dashboard`: scrub step 5 min; panel stale-after overview 120 s, radar 120 s, positioning 600 s, signal 120 s, trades 30 s, health 30 s; SSE every 5 s | config v12 |
| Q-10-13 | 10 | "Every number comes from a backend field": is unit formatting allowed in the frontend? | Yes, display only: paise → ₹ (÷100), ns → IST clock, fraction → %. Every value (incl. lots, executable mark, metrics) is a backend field; the frontend computes no trading quantity | dashboard/web/fo-engine/core.tsx |
| Q-10-14 | 10 | The phase is "read-only over backend state" but Panel H needs the Phase 9 journal / feedback forms | Four POST routes (`journal/take`, `journal/skip`, `journal/exit`, `feedback`) write only the Phase 9 ACTUAL ledger and feedback tables, with the same loopback + same-origin check and pydantic validation; prices typed in ₹, stored in paise. Every other route is GET | engine/api.py |
| Q-10-15 | 10 | Performance has no replay clock | `/performance` is per ledger over all closed trades to now (labelled LIVE), not as-of; every other panel honours `as_of` | engine/api.py |
| Q-10-17 | 10 | Look-ahead in replay: `status.json` is one latest snapshot (2026-11-06 15:45:02), later than any replay time of that day | Any envelope whose newest observation is after the view time is UNAVAILABLE ("look-ahead") and its data withheld; a recommendation made after the view time cannot be opened. So System health is UNAVAILABLE in a replay of 2026-11-06 (no per-time recorder status history exists) | engine/dashboard.py, engine/api.py |
| Q-10-18 | 10 | Radar OI % / Price % / RVOL definitions | From the recommendation's stored Phase 4 state at the decision: `combined_oi_chg_15m_pct`, `fut_price_chg_15m_pct`, `rvol_15m` (`positioning.feature_window_min`, near-month future vs near-month history, Q-3-4). Timeliness: TIMELY / LATE (= VALID_BUT_LATE) / RETEST (TIMELY with reason RETEST) / EXHAUSTED, and UNKNOWN shown as UNKNOWN | engine/dashboard.py |
| Q-10-19 | 10 | Visual-regression residue: across repeated captures of the SAME build, Radar / Swing / Commodities sometimes differ by 12 px (max channel diff 2/255) outside the nav strip | Treated as renderer noise: the same 12 px appears between two runs of one build, and every tab has before/after pairs with 0 px outside the nav strip (`phase-10-evidence/visual-regression-direct.txt`) | dashboard/web/fo-engine/tests |
| Q-10-20 | 10 | Deploying the tab means rebuilding `dashboard/web/dist` and restarting the running `com.clade.dashboard-server` (it imports routers at start) | Not done by me: `dist/` and the live server on 8080 are untouched; all builds and runs used scratch directories and ports 8091/8092/4180/4181. The owner runs `npm run build` and restarts the server | dashboard/web/dist, launchd |
| Q-10-21 | 10 | Playwright 1.64.1 expects Chromium build 1248; the cached build is 1234 | Tests launch the cached `chromium_headless_shell-1234` via `FO_CHROMIUM` (no browser download); it ran every check here | dashboard/web/fo-engine/playwright.config.ts |
| Q-10-22 | 10 | How to automate the dashboard data (owner request 2026-11-07) given that the EOD job dies in compaction (Q-6-5) and `signal_report` / the paper run read `buffer.sqlite`, which a verified compaction deletes | Inside the already-installed `com.clade.engine-eod` (15:50 weekdays), before compaction, under the recorder lock: per day, signals (needs buffer) → paper run (needs buffer + signals done) → dashboard export (needs snapshots; independent of Phase 8). Subprocesses free memory before compaction; per-step timeout `dashboard.eod_step_timeout_s` 1800 s (config v13 = v12 + that key; v12 not edited in place, D-16). Failures are recorded in `eod_last.json` and fail the job's exit code. No new launchd job | engine/eod.py, config v13, engine/dashboard_export.py |
| Q-11-4 | 11 | IV model and forward | Black-76 on the same-expiry future: NSE index options are European (phase-11-evidence/sources-2026-11-07.txt), and the future price already carries dividends and carry, so no dividend forecast is needed; the rate only discounts. Reuse `dashboard/black76.py` `price` by import (unmodified); the solver with reasons, Greeks incl. theta are in the engine. An expiry with no listed same-expiry future (weekly index options) ⇒ IV UNAVAILABLE (NO_SAME_EXPIRY_FUTURE); a put-call-parity forward is not built. Stock options verified European the same day (F-OPT-2), so stock options get IV too | engine/options.py |
| Q-11-5 | 11 | Risk-free rate source | RBI 91-day T-bill cut-off YTM 5.8970 % of 2026-11-04 (F-RATE-RBI-1), simple annualised over 91 days ⇒ continuous in code; older than `options.risk_free.max_age_days` (21, PROPOSED) ⇒ every IV UNAVAILABLE (RATE_STALE) until a newer auction is typed into a new config version | config v14 |
| Q-11-6 | 11 | Time to expiry in trading-calendar years | Remaining trading sessions from the config holiday calendar + the remaining fraction of today's session, ÷ `options.trading_days_per_year` (PROPOSED 252, a convention). An expiry in a year whose holidays are unverified (2027, Q-2-3) ⇒ UNAVAILABLE. The intraday fraction uses the single session values (wrong from 2026-12-07, Q-3-1) | engine/options.py |
| Q-11-7 | 11 | IV percentile history | Engine-recorded tier C history only (not `journal.db iv_history`: different method, protected). UNAVAILABLE below `options.iv_pct_min_sessions` (PROPOSED 20). The long-option IV gate rejects when the percentile is UNAVAILABLE (IV_PERCENTILE_UNAVAILABLE), so no option candidate passes for ≥ 20 recorded sessions | engine/options.py, engine/contracts.py |
| Q-11-8 | 11 | Event calendar details | Source `https://www.nseindia.com/api/event-calendar` (official NSE, HTTP 200 without cookies, F-EVT-1). Every board meeting counts, not only results. Window in trading days, the meeting day included. Calendar older than 1 day or fetch failed ⇒ EVENT_UNVERIFIED (all option candidates rejected, index included). Index options are not gated on constituents' results. Absence from the calendar is labelled NO_KNOWN_EVENT, not "no event" | engine/events.py |
| Q-11-9 | 11 | Thresholds (IV spread, hypothesis change minimums, unusual OI change, liquid expiry, event window, IV percentile max, strikes ± N) | PROPOSED values in config v14 `options.*`, none an owner decision | config v14 |
| Q-11-10 | 11 | Options factor points | Supportive = full weight; neutral = 0; contradicting = 0 with the reason in the explanation (fewer points). Not a gate | engine/signals.py |
| Q-11-11 | 11 | Report data: no option has ever been recorded | Chain snapshots for 3 underlyings from one read-only REST `/quote` after-hours snapshot (labelled AFTER_HOURS; books are likely empty ⇒ IV UNAVAILABLE, shown as such) plus SYNTHETIC fixtures, labelled. Re-run on the first recorded session | docs/phase-11-report.md |
| Q-11-12 | 11 | Reuse `dashboard/black76.py`? | Not imported: it imports `dashboard.option_chain`, which imports `dashboard.app` (legacy server with the mock `handle_place_trade` routes) and reads `kite_config.json` at import (hidden I/O, guardrails 11/13). The engine has its own ~20-line Black-76; both give 1.11664 (Hull) and 1.70105 (Haug) on the references (phase-11-evidence/sources-2026-11-07.txt) | engine/options.py |
| Q-11-13 | 11 | Chain-report conventions | Underlying reference = near-month future mid (ATM and underlying move). OI age = its own tick row's receive time. Changes over `options.change_window_min` (15). IV history = one ATM IV per underlying per session: the last snapshot of the day that has one (so intraday IV is ranked against close-ish values) | engine/chain_report.py |
| Q-11-14 | 11 | Planner priority: "underlyings with active setups" | Phases 4–6 are batch (Q-4-6), so no live setups exist. Order: INDEX family, then underlyings with Phase 6 setups on the latest earlier recorded session (by count), then the rest by scanned ATM option volume. Level strikes = the strike nearest each previous-EOD LevelMap level (levels are near-month future prices; basis ignored, only for choosing what to record) | engine/recorder.py, engine/options.py |
| Q-11-15 | 11 | Owner action for live tier C | The repo plist now runs `engine.recorder --config config/engine/v14.yaml`; the installed `~/Library/LaunchAgents/com.clade.engine-recorder.plist` was not touched (D-5: the owner installs). v14 shares every v4 recorder key byte-for-byte (checked), plus tier C full / cap 400 and the planner. **Reinstalled 2026-11-07 ~17:00 IST at the owner's request** (unload → copy → load; previous copy kept in the session scratchpad); the first v14 run is the next weekday 09:00 | scripts/launchd/com.clade.engine-recorder.plist |
| Q-11-16 | 11 | Interpretations: IV and hypotheses | "Never use LTP from a stale trade" ⇒ IV never uses LTP at all. Labels need all four inputs in the classic direction (table in phase-11-report §1); OI or premium change below its minimum counts as flat. SPREAD_OR_HEDGE_SUSPECTED = CE and PE OI both rising at one strike within the ratio band (the only spread rule built). Concentration is shown with its strike and share, never called resistance | engine/options.py |
| Q-11-17 | 11 | Selector V2 details | Greeks path when the chain has Greeks, else the V1 empirical model (moot in practice: without IV the IV-percentile gate excludes the option). The move is measured on the setup's near-month future; another expiry gets BASIS_ASSUMED_CONSTANT. Theta over `options.holding_min` (30) is inside both the stop and target premium estimates (lowers both). Expiry sensitivity is a label, not a gate (min DTE and EXPIRY_DAY still gate) | engine/contracts.py |
| Q-11-18 | 11 | Recorded option books are change-only, like futures (Q-9-16): an unchanged book has no new row and looks older than `quality.stale_depth_s` (5 s) | Strict: STALE_QUOTE ⇒ IV UNAVAILABLE. Expect low IV coverage on illiquid strikes; revisit with Q-3-2 | engine/options.py |
| Q-11-19 | 11 | Report's after-hours REST snapshot | Labelled AFTER_HOURS. Its OI counts as fresh because it was received now; every book is empty after the close, so IV coverage is 0 % there by construction | docs/phase-11-evidence/after-hours-chain-2026-11-07.json |
| Q-11-20 | 11 | Config wiring | `engine.signals` default → v14 (Phase 8 outputs change; v10 rows stay). EOD chain: `chain_report` → signals → paper → dashboard; signals re-run once per recorded day that still has its buffer. The API reads v14 (`dashboard.stale_after_s.chain` 900, PROPOSED); `dashboard_export` stays v13 | engine/signals.py, engine/eod.py, engine/api.py |
| Q-11-21 | 11 | `engine.snapshots.jsonable` did not recurse into dicts, so a Phase 8 `opportunity_age` holding an UNAVAILABLE could not be serialized | Fixed additively: dicts are recursed; any dict that serialized before gives identical output | engine/snapshots.py |
| Q-12-14 | 12 | "Competing simultaneous signals resolved by the live ranking + risk rules": the live paper path (`ledger.run_day`) has no score ranking; it takes ENTRY_ELIGIBLE recommendations in (as_of, recommendation_id) order and applies Phase 7 risk on the SIMULATED ledger | The backtest reuses `run_day` unchanged (phase rule 1: no backtest-only strategy code), so it inherits exactly that order plus the risk rules (single position per underlying, max open positions, daily loss, cooldown). No ranking was added | engine/backtest_report.py |
| Q-12-15 | 12 | HISTORICAL_CANDLES data rules | Derived config `v16:HIST(cash session, index 5m/15m)` (never on disk): `sessions.fno` = `sessions.cash` 09:15–15:30, `structure.timeframes_min` [5, 15] (3m not buildable). Holidays only from config (2021–2025 holidays are not in it: the day after one gets no PDH/PDL/PDC, never a guessed previous day). A day missing any bar is excluded (8 of 1,383). ATR = the Phase 5 Detector's own state after each bar. Pre-signal move on setup-timeframe closes (no 1m). Phase 6 evaluations at each 5m close. Opening range, 3m timeframe and 1/3-minute horizons are UNAVAILABLE. Previous-day/week levels relabelled `LAB_CSV:<file>` (never HISTORICAL_API) | engine/backtest.py, engine/backtest_report.py |
| Q-12-16 | 12 | Price-path outcome model for event rows, half-life and class entries | Stop on touch; a bar opening beyond the stop exits at that open (gap-through); target on touch exits at the target (never better); a bar touching both = stop; otherwise exit at the last bar ending by `monitor.squareoff_cutoff` (15:10). Gross R, no fills, no costs. MULTI_SESSION = target hit on a later session (up to `backtest.multi_session_days` = 5) before the stop; a target after the cutoff on the same session, or > 90 min after the anchor, is INCONCLUSIVE | engine/backtest.py |
| Q-12-17 | 12 | Half-life method and file | Fresh hypothetical entry at the bar close at each age edge [0, 5, 15, 30, 60, 120] min after confirmation while the setup is still open and price is between stop and target; half-life = the lower edge of the first bucket with expectancy ≤ half the age-0 expectancy (each bucket needs ≥ `min_trades`; age-0 ≤ 0 ⇒ NO_POSITIVE_EDGE). Basis: gross price-path R. Keyed by Phase 6 setup type (Phase 6 does not know the Phase 8 family). `config/engine/half_life/v<N>.json`: a new version only when entries change; a partial run carries the other dataset's latest entries. Phase 6 uses only RECORDED + MEASURED + stage TENTATIVE/FINAL; multiple 1.0 | engine/backtest.py, engine/backtest_report.py, engine/opportunity.py, config v16 |
| Q-12-18 | 12 | Segment definitions | Time of day: edges 09:15/10:15/11:30/13:30/14:30/15:40 at confirmation. Regime: latest NIFTY 15m TREND state (Phase 5) confirmed by then; the Detector restarts each day, so early-session setups are UNAVAILABLE. Expiry proximity: Phase 4 calendar-day rule from the day's master (RECORDED only; the index dataset has no expiry calendar). Score band: Phase 8 score (RECORDED only). VIX: UNAVAILABLE (Q-12-11) | engine/backtest.py, engine/backtest_report.py |
| Q-12-19 | 12 | Recorded sessions whose buffer was deleted after compaction; where backtest trades are stored; which Phase 8 config | Rebuilt from Parquet (the day dir, else the retention archive path; an `s3://` target cannot be read back) into a temporary buffer with the Phase 1 replay readers; derived stores are linked, not copied. Trades go to `<root>/backtest/<run>/backtest_ledger.sqlite`. Recommendations are re-derived under the live Phase 8 config (`signals.load()`, v14) | engine/backtest_report.py |
| Q-12-20 | 12 | Recorded walk-forward "score floor" grid | Implemented as a post-filter on the trades' recommendation score (60 / 80). Limitation: a filtered-out trade still occupied its position slot in the run. Not run yet (0 development sessions) | engine/backtest_report.py |
| Q-12-21 | 12 | Verdict rules and which results can give one | Verdicts are per Phase 8 family on RECORDED paper trades only. Fewer than `min_trades`, or stage below FINAL ⇒ INSUFFICIENT_SAMPLE. At FINAL: DROP if the net expectancy CI upper bound ≤ 0; otherwise REVISE (no KEEP without go-live criteria, Q-12-4). HISTORICAL_CANDLES never gives a verdict (index proxy, no fills, no costs) | engine/backtest.py |
| Q-12-22 | 12 | Precision basis per table | Each event counted once at its CONFIRMATION anchor (target before stop by the cutoff). RECORDED: grouped by Phase 8 family letter. Tables with no target concept (age / class entries) show no precision | engine/backtest_report.py |
| Q-13-4 | 13 | "Depth behaviour (Tier B only)": no token was ever in Tier B (3 `tier_plan` events on 2026-11-06, 0 B tokens; nothing promotes live, Q-8-4), although Tier A futures record raw 5-level depth in `full` mode | Strict: depth behaviour only for tokens whose recorded tier plan includes B at that time; otherwise UNAVAILABLE `NOT_TIER_B`. On real data today that is always UNAVAILABLE; only fixtures exercise it | engine/profile.py |
| Q-13-5 | 13 | Thresholds (no external source) | PROPOSED in config v17 `profile.*` / `depth.*`: value area 70 %; bin = first session price × 5 bps rounded up to a whole multiple of the master tick size (fixed for the day); snapshot every 5 min; min coverage 0.95; HVN = local max of 3-bin-smoothed volume over ±2 bins and ≥ 0.6 × POC; LVN = local min over ±2 bins, ≤ 0.25 × POC, strictly between two HVN/POC; rejection = 1m bar reaches POC/HVN within 0.25 ATR and closes ≥ 0.25 ATR back, flag window 15 min; depth window 60 s; replenish = level qty falls ≥ 50 % then recovers ≥ 80 % at the same price; withdrawal = level qty falls ≥ 50 % with no trade at that price and a volume rise below the drop; absorption = LTP range ≤ 3 ticks while the opposite best level refills ≥ 3 times | config/engine/v17.yaml |
| Q-13-6 | 13 | Score factor weights before any out-of-sample evidence | Parts volume_profile and depth_behaviour get weight 0 (config part weights); the existing Phase 8 visible_depth part keeps its 5 points, so Phase 8 scores are unchanged. Scores gate nothing (no gate uses them) | engine/signals.py, config v17 |
| Q-13-7 | 13 | Profile instrument and session | Near-month future (Phase 4/5 instrument); today's `sessions.fno` open to as_of only; no prior-day or composite profile; months not combined | engine/profile.py |
| Q-13-8 | 13 | Phase 12 re-run: how "adds value out-of-sample" is judged | Recorded event study only, split by factor value (flag / part points), development vs validation per the Phase 12 split. HISTORICAL_CANDLES = NOT_REPRESENTABLE (index has no volume or depth, F-WS-7). With 0 GOOD sessions the verdict is INSUFFICIENT_SAMPLE ⇒ weights stay 0 | engine/backtest.py, engine/backtest_report.py |
| Q-13-9 | 13 | v17 live? The dashboard API (`api._latest_version`) and the paper ledger (`ledger._latest_version`) pick the numerically latest config version in each store, so writing v17 rows to signals.sqlite / opportunity.sqlite would change what the dashboard shows and what the paper run reads | v17 is not made the EOD / live default and no v17 rows are written; real-data runs are dry-run / in-memory. Making v17 live is an owner decision | config/engine/v17.yaml, engine/eod.py (unchanged) |
| Q-13-10 | 13 | How depth behaviour reaches Phase 8 without changing `SignalInputs` | Extension of D-59: profile, rejection and depth outputs are all Phase 5-shaped `Detection`s (PROFILE_* / PROFILE_UNAVAILABLE timeframe `session`, HVZ_REJECTION `1m`, DEPTH_BEHAVIOUR `depth`; label TICK_BASED / APPROXIMATE / OBSERVED_IN_5_LEVEL_DEPTH), recomputed by the Phase 6 / 8 edges (`profile.add_profile`), not written to structure.sqlite. So the UI chart draws no profile lines; the labels reach the UI in the score-part details, once v17 signals are exported (Q-13-9) | engine/profile.py |
| Q-13-11 | 13 | Timing details | A minute counts from its candle close (the Phase 5 convention; Phase 3 publishes it `finalize_delay_s` later) and only once all its ticks were received by as_of. A HVZ_REJECTION inside the flag window flags even when the latest profile snapshot is UNAVAILABLE (more flags = fewer TIMELY). Depth behaviour is computed for the near-month future only (the profile and price instrument) | engine/profile.py, engine/opportunity.py |
| Q-13-12 | 13 | Values of the new score parts (weight 0) | volume_profile = 1.0 when the price is on the trade side of the latest session POC, else 0.0; depth_behaviour = 1.0 when the visible 5-level imbalance agrees with the trade and there is no POSSIBLE_ABSORPTION against it, else 0.0. UNAVAILABLE carries the profile / NOT_TIER_B reason | engine/profile.py |

## Appendix C. External facts, re-opened 2026-11-07

| fact | url | http | automatic result | hand check | verdict |
|---|---|---|---|---|---|
| F-AUTH-1 | https://kite.trade/docs/connect/v3/user/ | 200 | OK | — | UNCHANGED |
| F-AUTH-2 | https://kite.trade/docs/connect/v3/user/ | 200 | OK | — | UNCHANGED |
| F-AUTH-3 | https://kite.trade/docs/connect/v3/user/ | 200 | OK | — | UNCHANGED |
| F-AUTH-4 | https://kite.trade/docs/connect/v3/user/ | 200 | OK | — | UNCHANGED |
| F-AUTH-5 | https://kite.trade/docs/connect/v3/user/ | 200 | OK | — | UNCHANGED |
| F-AUTH-6 | https://kite.trade/docs/connect/v3/user/ | 200 | OK | — | UNCHANGED |
| F-AUTH-7 | https://kite.trade/docs/connect/v3/exceptions/ | 200 | OK | — | UNCHANGED |
| F-AUTH-8 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-RATE-1 | https://kite.trade/docs/connect/v3/exceptions/ | 200 | OK | — | UNCHANGED |
| F-RATE-2 | https://kite.trade/docs/connect/v3/exceptions/ | 200 | OK | — | UNCHANGED |
| F-RATE-3 | https://kite.trade/docs/connect/v3/exceptions/ | 200 | OK | — | UNCHANGED |
| F-RATE-4 | https://kite.trade/docs/connect/v3/exceptions/ | 200 | OK | — | UNCHANGED |
| F-QUOTE-1 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-QUOTE-2 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-QUOTE-3 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | NO_QUOTE_TO_CHECK | all 17 field names present | UNCHANGED |
| F-QUOTE-4 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-QUOTE-5 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-QUOTE-6 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-QUOTE-7 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-QUOTE-8 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-QUOTE-9 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-QUOTE-10 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-INST-1 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-INST-2 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | NO_QUOTE_TO_CHECK | all column names present | UNCHANGED |
| F-INST-3 | https://kite.trade/docs/connect/v3/market-quotes/ | 200 | OK | — | UNCHANGED |
| F-WS-1 | https://kite.trade/docs/connect/v3/websocket/ | 200 | OK | — | UNCHANGED |
| F-WS-2 | https://kite.trade/docs/connect/v3/websocket/ | 200 | OK | — | UNCHANGED |
| F-WS-3 | https://kite.trade/docs/connect/v3/websocket/ | 200 | OK | — | UNCHANGED |
| F-WS-4 | https://kite.trade/docs/connect/v3/websocket/ | 200 | NO_QUOTE_TO_CHECK | byte offsets 0–44 present | UNCHANGED |
| F-WS-5 | https://kite.trade/docs/connect/v3/websocket/ | 200 | NO_QUOTE_TO_CHECK | byte offsets 44–184 present | UNCHANGED |
| F-WS-6 | https://kite.trade/docs/connect/v3/websocket/ | 200 | NO_QUOTE_TO_CHECK | follows from F-WS-4/5 (both re-checked) | UNCHANGED |
| F-WS-7 | https://kite.trade/docs/connect/v3/websocket/ | 200 | OK | — | UNCHANGED |
| F-HIST-1 | https://kite.trade/docs/connect/v3/historical/ | 200 | NO_QUOTE_TO_CHECK | all 8 interval names present | UNCHANGED |
| F-HIST-2 | https://kite.trade/docs/connect/v3/historical/ | 200 | OK | — | UNCHANGED |
| F-HIST-3 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-HIST-4 | https://kite.trade/docs/connect/v3/historical/ | 200 | OK | — | UNCHANGED |
| F-HIST-5 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-HIST-6 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-HIST-7 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-HIST-8 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-HIST-11 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-ACCT-1 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-REG-1 | https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html | 200 | NO_QUOTE_TO_CHECK | title and date present | UNCHANGED |
| F-REG-2 | https://www.sebi.gov.in/legal/circulars/sep-2025/extension-of-timeline-for-implementation-of-sebi-circular-dated-february-04-2025-on-safer-participation-of-retail-investors-in-algorithmic-trading-_96979.html | 200 | NO_QUOTE_TO_CHECK | title and date present | UNCHANGED |
| F-NSE-1 | https://nsearchives.nseindia.com/content/circulars/FAOP74467.pdf | error | FETCH_FAILED | nseindia.com returned an HTML bot page (no PDF), as on 2026-11-05; broker mirror PDF re-read, quote present. **Valid only until 2026-12-06** (F-NSE-9, Q-3-1) | UNCHANGED |
| F-NSE-1 | https://flattrade.in/kosh/wp-content/uploads/2026/05/FAOP74467.pdf | 200 | OK | — | UNCHANGED |
| F-WS-8 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-WS-9 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-WS-10 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-WS-11 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-WS-12 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-INST-4 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-2 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-3 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-4 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-5 | https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf | 200 | QUOTE_NOT_FOUND | quote is from the amending circular FAOP72262, which matched; FAOP71777 itself never held it (checker artefact) | UNCHANGED |
| F-NSE-5 | https://nsearchives.nseindia.com/content/circulars/FAOP72262.pdf | 200 | OK | — | UNCHANGED |
| F-NSE-6 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-INST-5 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-INST-6 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-WS-13 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-WS-14 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-WS-15 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-HIST-9 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-HIST-10 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-7 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-8 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-9 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-NSE-10 | https://nsearchives.nseindia.com/content/circulars/FAOP76940.pdf | 200 | OK | — | UNCHANGED |
| F-COST-1 | https://zerodha.com/charges/ | 200 | OK | — | UNCHANGED |
| F-COST-2 | https://zerodha.com/marketintel/bulletin/445377/revision-in-stt-securities-transaction-tax-from-1st-april-2026 | 200 | OK | — | UNCHANGED |
| F-COST-2 | https://zerodha.com/charges/ | 200 | QUOTE_NOT_FOUND | quote is from the bulletin URL, which matched; zerodha.com/charges carries the rates, not the sentence (checker artefact) | UNCHANGED |
| F-COST-3 | https://zerodha.com/charges/ | 200 | OK | — | UNCHANGED |
| F-COST-3 | https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges | 200 | QUOTE_NOT_FOUND | support page shows the same rates as 0.00183% and 0.035530% (format change only); zerodha.com/charges matched | UNCHANGED |
| F-COST-4 | https://zerodha.com/charges/ | 200 | OK | — | UNCHANGED |
| F-COST-5 | https://zerodha.com/charges/ | 200 | OK | — | UNCHANGED |
| F-COST-6 | https://zerodha.com/charges/ | 200 | OK | — | UNCHANGED |
| F-MARGIN-1 | https://kite.trade/docs/connect/v3/margins/ | 200 | OK | — | UNCHANGED |
| F-QTY-1 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |
| F-OPT-1 | https://www.nseindia.com/static/products-services/equity-derivatives-bank-nifty-option-contract-specification-monthly | 200 | OK | — | UNCHANGED |
| F-OPT-2 | https://www.nseindia.com/static/products-services/equity-derivatives-individual-securities | 200 | OK | — | UNCHANGED |
| F-RATE-RBI-1 | https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63918 | 200 | OK | — | UNCHANGED |
| F-EVT-1 | — (MEASURED) | — | SKIPPED_MEASURED | measured on this account; re-measured by running the engine, not by a URL | not re-opened |

## Appendix D. Requirements matrix (generated by `python3 scripts/acceptance_audit.py`)

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
