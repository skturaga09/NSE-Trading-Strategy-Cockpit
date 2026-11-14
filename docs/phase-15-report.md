# Phase 15 report: acceptance audit, fixes, intraday signals, runbook (2026-11-07)

Saturday, IST; market closed. Branch `stack/4-setup-radar`. Nothing committed. Advisory and paper-trading only: no order placement,
modification or cancellation exists (§5).

## 0. Owner answers this phase

| question | answer | decision |
|---|---|---|
| Max risk per paper trade | ₹10,000 (was ₹2,000) | D-61 |
| Futures margin estimate | 25 % of notional (own estimate, MARGIN_ESTIMATED) | D-62 |
| Capital settings | keep ₹2,00,000 / 20 % reserve / ₹1,00,000 per trade / ₹6,000 daily loss | D-63 |
| Long-option IV gate | keep (options blocked until 20 option sessions) | D-64 |
| "Fix all the issues and make it functional" | fix the Phase 15 gaps; signals during the session | D-65 |

## 1. What was built or changed

| file | change |
|---|---|
| `docs/acceptance-audit.md` | step 1 audit: 302 requirement rows, gaps G-1 … G-12, decisions vs config, ledger audit, facts re-verified, safety re-check. §8 has the status after fixes |
| `scripts/acceptance_audit.py`, `scripts/reverify_facts.py` | read-only audit helpers (re-runnable; runbook §6) |
| `config/engine/v18.yaml` | v15 + D-61 + D-62 only (not v16/v17, Q-13-9) |
| `engine/signals.py`, `engine/options.py`, `engine/paper.py` | `DEFAULT_CONFIG` → v18 (options too: IV history is keyed by config version) |
| `engine/intraday.py` (new) | re-runs option chain → signals → dashboard export on today's live recording, only while the recorder holds its lock |
| `scripts/launchd/com.clade.engine-intraday.plist` (new, **you install it**, runbook §2) | every 5 min, weekdays 09:20–15:35 |
| `engine/eod.py` | `run(..., now=None)` (G-3); `dashboard_chain(..., rerun, only, live)`: today's append-only steps re-run at EOD to add the tail; the intraday job never runs the paper ledger |
| `engine/signal_report.py` | `--live`: store nothing timed after the day's last received packet (prefix proof §3) |
| `dashboard/api_server.py`, `dashboard/app.py` | mock trade route: answers mode "mock" and "Recorded in the trade book only. No order was sent to the broker" (Q-0-6, D-65). Route kept: four tabs use it |
| tests | `test_storage` (pinned clock), `test_dashboard_api` (+2: today re-run, intraday gating), `test_signals` (+2: live horizon, market context; PASSING fixture pinned to the ₹2,000 it was sized on; default-version assertion v18), `test_positioning` (+2: F3–F6 values, ABNORMAL_BASIS), `test_structure` (+1: Detection fields), `test_recorder_replay` (+1: daily master snapshot) |
| `docs/runbook.md` (new) | operations, dashboard guide, troubleshooting, clean-machine setup |
| `docs/decisions.md`, `docs/questions-ledger.md` | D-61 … D-65; Q-15-1 … Q-15-13; 13 broken rows reformatted (G-10) |
| `data/engine/2026-11-06/signals.sqlite` | v18 rows added (append-only), so the Radar shows the day under your settings |

## 2. Requirement status (Phase 15 text)

| # | requirement | status | proof |
|---|---|---|---|
| 1a | Requirements audit with phase, files, test, latest result | DONE (against the phase reports; the traceability matrix and original spec are not in the repo, Q-15-3) | `docs/acceptance-audit.md` App. D, `scripts/acceptance_audit.py` |
| 1b | Gaps listed and owner asked which to fix | DONE | audit §2; answer D-65; Q-15-5 |
| 1c | Decisions reflected in config, blanks flagged | DONE (none blank) | audit §3 |
| 1d | Ledger: zero OPEN rows | **NOT DONE: 11 OPEN** (were 14) | App. A; they need facts or choices not given (Q-15-1) |
| 1e | Facts re-verified from their URLs | DONE: 46 DOC facts unchanged; F-NSE-1 expires 2026-12-06 | `phase-15-evidence/facts-reverify.jsonl`, audit App. C |
| 2 | Full-day dress rehearsal + reproducibility | PARTIAL: only one (partial) session exists. Done: the same day replayed twice gives identical rows (`replay_check` 86/86 identical; second v18 run wrote 0 new rows) and a 12:30 cut is an exact prefix of the full day (§3) | §3, `phase-15-evidence/prefix-check-2026-11-06.txt` |
| 3 | Live shadow day | NOT DONE (yours; first eligible Mon 2026-11-09, Q-15-11) | — |
| 4 | Failure drills | PARTIAL: not drilled live. Each behaviour is covered by an existing fixture test (runbook §5); clock skew has no handling and no test | runbook §5 |
| 5 | Safety re-check | DONE | audit §6; `phase-15-evidence/safety-recheck.txt` |
| 6 | Runbook | DONE | `docs/runbook.md` |
| + | Signals during the session (owner request) | DONE in code and tested; goes live once you install the plist | `test_intraday_runs_only_during_a_live_session`, `test_today_reruns_append_only_steps_but_never_the_paper_ledger`, `test_live_write_stores_nothing_after_the_last_packet` |

## 3. Intraday signals: why repeated runs are honest

The store is append-only (INSERT OR IGNORE), so a mid-session run must produce exactly the rows the full-day run would produce for the
same times, or a wrong row is kept forever. Check: 2026-11-06 was cut at 12:30 IST, keeping ticks and depth received by then and the
minute snapshots published by then. It was run through the same code under v18 and compared with the full-day v18 run:

| store | rows in the 12:30 run | not identical in the full run |
|---|---|---|
| recommendations | 4 | 0 |
| observations | 18 | 0 |
| lifecycle, before the fix | 247 | **20**: retest plans "expired" at 12:37+ although the data ended at 12:30 |
| lifecycle, rows up to the last packet (`--live`) | 209 | 0 |
| dashboard export (positioning / market / candles) | 7,372 / 38 / 18,818 | 0 / 0 / 0 |

So the intraday run passes `--live`, and the EOD job re-runs today's steps without it to add the tail. The option chain step could not be
checked (no option was recorded on 2026-11-06).

## 4. Signals on real data under v18 (2026-11-06)

86 recommendations, **0 ENTRY_ELIGIBLE**. Failed gates: TIMELINESS 86, RISK_CHECK 86, SPREAD 70. Risk reasons: CAPITAL_ABOVE_LIMIT 81
(25 % of a ₹5–10 lakh lot = ₹1.25–2.5 lakh > ₹1 lakh per trade), MIN_NET_RR 80, CAPITAL_RESERVE 76, SPREAD_TOO_WIDE 65, MAX_RISK_PER_TRADE 12
(was ~76 at ₹2,000). Your settings now let futures in on risk; per-trade capital and the engine's timeliness and R:R filters still decide.

## 5. Safety

0 order methods in engine/, scripts/, fo-engine/; only `KiteTicker` is imported from kiteconnect; no credential value in logs, data,
config, docs or either frontend bundle; SIMULATED and ACTUAL never combined (tests pass). The two legacy mock trade routes remain: they
record to the trade book and never reach the broker, and now say so. Whether `dashboard/app.py` is still needed stays Q-0-7 (OPEN).

## 6. Verified facts used

No new external fact. F-NSE-1 (15:40 close, valid to 2026-12-06), F-AUTH-6 (token expiry 06:00), F-WS-2 (connection limits) are cited in
the runbook; all re-opened today (audit App. C).

## 7. Open questions, assumptions, limitations

- OPEN (11): Q-0-2, Q-0-3, Q-0-7, Q-0-8, Q-1-4, Q-3-1, Q-6-2, Q-7-6, Q-7-8, Q-7-9, Q-7-10.
- New ASSUMED: Q-15-3, Q-15-4, Q-15-6, Q-15-8 … Q-15-13.
- Not done: 12-St-4 full re-run on eventually-reported OI; tests for the 10-A…E panels and the SSE stream; Playwright visual regression
  not re-run; live failure drills; live shadow day.
- Signals reach the Radar 5–10 minutes after their decision time (5-minute interval + 3–6 minute run).
- The radar envelope's `config_version` field reports the API's dashboard config (v14), not the signals version (v18).

## 8. Test suite (raw output)

Engine: `python3 -m unittest discover -s tests/engine_tests -t . -v` (full log `docs/phase-15-evidence/engine-suite-final.txt`), tail:

```

----------------------------------------------------------------------
Ran 308 tests in 46.650s

OK

fixture storage report: {"before_bytes": {"ticks": 20480, "depth": 8192, "oi_changes": 8192, "events": 8192, "gaps": 8192, "meta": 8192, "frames.bin": 21659, "buffer.sqlite(file)": 40960, "instrument_master(csv.gz)": 235}, "A_parquet_bytes": {"ticks": 19537, "depth": 19721, "oi_changes": 4732, "events": 1298, "gaps": 716, "meta": 346}, "B_frames_zst_bytes": 1300, "replay": {"events_buffer": 202, "events_parquet": 202, "events_frames": 252, "seconds_buffer": 0.0007, "seconds_parquet_A": 0.0036, "seconds_frames_B": 0.0009, "method": "streamed passes (Q-6-5); no event list is built"}}
exit 0
```

Dashboard: `python3 tests/test_*.py`:

```
=== tests/test_dashboard_and_plumbing.py
----------------------------------------------------------------------
Ran 12 tests in 0.543s

OK
=== tests/test_day_test.py
----------------------------------------------------------------------
Ran 4 tests in 0.000s

OK
=== tests/test_mcx.py
----------------------------------------------------------------------
Ran 49 tests in 0.017s

OK
```

Frontend: `npx vitest run -c fo-engine/vitest.config.ts`, tail:

```
 ✓ fo-engine/tests/components.test.tsx (7 tests) 168ms

 Test Files  2 passed (2)
      Tests  27 passed (27)
   Start at  21:58:42
   Duration  1.10s (transform 93ms, setup 0ms, collect 196ms, tests 244ms, environment 357ms, prepare 89ms)

exit 0
```

Reproducibility on real data: `python3 -m engine.signal_report 2026-11-06` run a second time under v18
(`docs/phase-15-evidence/v18-signals-2026-11-06-second-run.txt`):

```
{"date": "2026-11-06", "setups": 988, "lifecycles": 865, "recommendations": 86, "rows_written": 0, "replay_check": {"checked": 86, "identical": 86, "different": []}}
exit 0
```
