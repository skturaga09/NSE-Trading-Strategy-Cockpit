# Phase 0 report — repository assessment, verified facts, architecture plan

Date: 2026-11-05 (IST). Repo: `Clade-NSE-Skills`, branch `stack/4-setup-radar`, HEAD `defa774`.
Phase 0 rule: **no production code**. Only docs, evidence files and the requested read-only
`scripts/verify_kite.py` were added.

## 1. What was produced

| File | Purpose |
|---|---|
| `docs/architecture.md` | protected assets, module map with reuse, data flow, storage + schema, interfaces, process model |
| `docs/verified-facts.md` | 43 facts: 34 backed by official docs (URL on the row; 2 of them also measured), 9 measured only on this account (evidence file on the row), all dated |
| `docs/open-questions.md` | 22 unverified facts / pending decisions, plus 3 findings in protected code |
| `docs/build-plan.md` | phases 1–14 (**proposed mapping**, see §6), file-level plans for 1 and 2 |
| `docs/phase-0-report.md` | this report |
| `docs/phase-0-evidence/unittest.txt` | raw output of the existing test suite |
| `docs/phase-0-evidence/selfchecks.txt` | raw output of the 10 module self-checks |
| `docs/phase-0-evidence/frontend-build.txt` | tail of `npm run build` (tsc + vite) |
| `docs/phase-0-evidence/measured-kite.txt` | raw output of read-only Kite measurements |
| `docs/phase-0-evidence/protected-sha256-before.txt` / `-after.txt` | checksums of untracked protected assets |
| `scripts/verify_kite.py` | read-only check: instrument master + one quote, prints which fields exist; env credentials only |

## 2. Requirement status

| # | Requirement | Status | Evidence |
|---|---|---|---|
| T1 | Inventory each component: path, purpose, works?, reusability for auth, instruments, WebSocket, historical, indicators, storage, backtesting (incl. backtest-expert costs), paper trading, frontend | DONE | §3 below; tests + self-checks in §7 |
| T1b | Locate the 5-year NIFTY data: location, format, granularity, OI?, range | DONE | architecture.md §1 table; 5-min SHA-256 matches its audit file |
| T2 | List strategies, configs, live/paper records as Protected assets in architecture.md | DONE | architecture.md §1 |
| T3 | verified-facts.md with URL + access date + short quote for each listed topic | DONE, with gaps | Each topic below; gaps go to open questions |
| T3a | KiteTicker modes and fields (OI, OI day high/low, depth, timestamps) | DONE | F-WS-3..7 (DOC) |
| T3b | Max instruments per connection, max connections per key | DONE | F-WS-2 (DOC: 3000, 3) |
| T3c | Historical: intervals, max days per request, `oi=1` support, rate limits | DONE | F-HIST-1..8. The docs give **no** per-request day caps, so these were **measured** from Kite's own error text (F-HIST-5); 10/15/30-minute caps not reached (Q-HIST-1) |
| T3d | Quote/LTP limits and rate limits | DONE | F-QUOTE-1..2, F-RATE-1 |
| T3e | Instrument master endpoint and fields | DONE | F-INST-1..3, measured columns identical |
| T3f | Session/token expiry | DONE | F-AUTH-5..8 |
| T3g | Paid Kite Connect plan with live + historical | **ASK** | REST + historical proven working (F-ACCT-1); WebSocket entitlement unverified → Q-ACCT-1 (please confirm) |
| T3h | SEBI retail algo framework status (context) | DONE (context only) | F-REG-1..2; post-April-2026 status not verified → Q-REG-1 |
| T4 | `scripts/verify_kite.py`, read-only, env credentials, no subscriptions/orders | DONE (owner to run) | §7.4 shows its no-credential path. Not run with live credentials by me, as you said you would run it |
| T5 | architecture.md: module map, data flow, storage choice, raw-observation schema, process model, interfaces, reuse marks | DONE | architecture.md §2–7 |
| T6 | build-plan.md: phases 1–14, file-level for 1 and 2, a paragraph for the rest | PARTIAL | Written, but the phase **definitions** for 1–14 were not provided, so the mapping is my proposal (Q-OPS-5) |
| A1 | The five docs exist | DONE | §1 |
| A2 | Every fact has URL + access date | DONE | verified-facts.md, every row |
| A3 | Protected assets untouched (git diff) | DONE | §7.5: `git diff --stat defa774` empty; untracked checksums identical |
| A4 | No new production modules | DONE | `git status` §7.5: only `docs/` and `scripts/verify_kite.py` (requested tool) added |

## 3. Repository inventory

"Works" evidence: U = covered by `tests/` (63 tests pass); S = its `selfcheck` passes; L = in daily
live use, seen running in this week's sessions (launchd logs and ledger rows); — = not exercised in Phase 0.

**Backend (`dashboard/`, FastAPI + React, all Kite access via `requests` REST; no WebSocket code; `kiteconnect` library not installed)**

| Path | Purpose | Works | Reusable for |
|---|---|---|---|
| `scripts/refresh_kite_token.py`, `scripts/kite_secrets.py`, `scripts/verify_kite_refresh.py` | headless daily login (Keychain secrets, TOTP), writes `kite_config.json` | L (failed 2026-11-05 08:45 while asleep, re-run OK) | **auth/session** |
| `option_chain.py` (`ensure_fresh_config`, `_bs`, `_iv`, chain) | ATM chain, IV via Black-Scholes | L | auth header helper, **option chain**, IV |
| `fno_scanner.py` (`_instruments`, `_universe_quotes`, `_daily`, `_adr_pct`) | F&O universe scan, gap screen, shortlist | L | **instrument download**, quote batching, ADR |
| `swing_scan.py` (`_futures_map`, buildup labels, `_levels`) | EOD OI-buildup board | L | instruments → futures map, price×OI quadrant semantics, structure levels |
| `structure_exit.py`, `liquidity_sweep.py` | swing-structure exits; sweep detector + OOS harness | L / S | **structure/liquidity** |
| `iv_rank.py` | daily ATM-IV history, IV rank | S, L | option analytics |
| `intraday_ignite.py`, `rec_ledger.py`, `swing_journal.py` | radar; call ledger; signal learning layer with day-clustered test | S, U (`day_test`), L | **analytics**, sample gates |
| `journal.py`, `kite_import.py`, `fno_nav_snapshot.py` | trade outcome journal (SQLite), Kite trade import, NAV | L | **storage** pattern (SQLite), attribution |
| `exit_monitor.py`, `thesis.py`, `position_prob.py`, `target_calc.py` | rule-based exit alerts (ntfy), thesis drift | L | monitoring semantics |
| `*_backtest.py` (8 files) | OOS harnesses (overnight, gap, sweep, OI target, regime, radar exit, swing, trailing/breakeven) | S (6 with selfcheck) | **backtesting** pattern (train/test by date, net cost) |
| `zerodha_plumbing.py` | order validation, freeze slicing, costs, session | U | session checks. **Not** lot sizes (stale `LOT_SIZES`, Q-PROT-3) |
| `api_server.py`, `app.py`, `run_dashboard.py`, `api/mcx.py` | FastAPI server (+ legacy stdlib), MCX router | L | **API** (router mounting) |
| `mcx*.py`, `black76.py`, `config/*.json` | isolated MCX lane | U | config-with-provenance pattern, event calendar |
| `news_sweep.py`, `live_fii_dii.py`, `live_market.py`, `live_vcp.py` | filings, FII/DII, yfinance breadth, VCP | S / L | **event gates** (filings) |
| `web/` (React + Vite + Tailwind) | dashboard UI, 12 tabs | build passes (§7.3) | **frontend** |

**Skills (`skills/`)**: `backtest-expert` (`evaluate_backtest.py`, incl. `calculate_india_costs`: **cost model**, but its rates conflict with the lab schedule, Q-NSE-3), `options-strategy-advisor` (`black_scholes.py`), `nse-vcp-screener`, `technical-analyst`, `india-market-breadth`, `fii-dii-flow-tracker`, `india-news-tracker`, `india-stock-analysis`, `scenario-analyzer`, `weekly-fno-trade-planner`. Indicators live in these and in the dashboard modules above.

**Separate repo `~/Documents/Codex/2026-08-11/nifty-trading-lab`**: `src/nifty_lab/` (backtesting, paper_trading, storage, market_data incl. `kite_historical.py`, risk, indicators). Versioned charges schedule with sources (`config/execution/zerodha_charges_2021_2026.yaml`), NSE 2026 session/holiday calendar with circular references, frozen strategy configs, and the historical datasets (architecture.md §1). Its test suite: **276 passed, 2 failed** (both in `test_market_context.py`; §7.6). Its data files are iCloud placeholders, which makes first reads slow.

**Paper trading today**: `POST /api/trade/place` writes `MOCK_ORD_*` rows to `trade_book.json` (no Kite call). The lab has a separate `paper_trading` engine. No live order code exists anywhere in this repo (searched for order POSTs and `place/modify/cancel_order`: none).

## 4. Verified facts used

All in [verified-facts.md](verified-facts.md). Official URLs used (accessed 2026-11-05):
- https://kite.trade/docs/connect/v3/user/
- https://kite.trade/docs/connect/v3/exceptions/
- https://kite.trade/docs/connect/v3/market-quotes/
- https://kite.trade/docs/connect/v3/websocket/
- https://kite.trade/docs/connect/v3/historical/
- https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html
- https://www.sebi.gov.in/legal/circulars/sep-2025/extension-of-timeline-for-implementation-of-sebi-circular-dated-february-04-2025-on-safer-participation-of-retail-investors-in-algorithmic-trading-_96979.html

Library-source citations (guardrail 5): the `kiteconnect` Python library is **not installed**
(`pip3 show kiteconnect` → not found), so no library method is cited. `scripts/verify_kite.py` uses
only the documented REST endpoints and headers (F-AUTH-2, F-INST-1, F-QUOTE-1) via `requests`.

## 5. Open questions needing you (full list in open-questions.md)

1. **Q-ACCT-1**: Is your Kite Connect plan entitled to live WebSocket data? (REST and historical are proven working.)
2. **Q-WS-5**: Should I install the official `kiteconnect` library (it pulls in Twisted/Autobahn), or parse the documented binary packets with the installed `websockets`?
3. **Q-OPS-1/2**: What should the recorder universe be, and how long should raw ticks be kept? Only **21 GB of disk is free**.
4. **Q-OPS-3**: Will there be an always-on host? This Mac sleeps on battery, and that cost this morning's session.
5. **Q-OPS-5**: Please send the texts for Phases 1–14. build-plan.md is my proposal.
6. **Q-NSE-3**: Which charges schedule is authoritative? The two in your code disagree.
7. **Q-PROT-1/2/3**: Do you want the mock-order `mode` label and the stale `LOT_SIZES` constant addressed? They are in protected code, so I didn't touch them.

## 6. Known limitations, assumptions, interpretations

- **Phase definitions**: I interpreted "phases 1–14 of this pack" without having the pack. The mapping follows your timing rules (recorder in 1–3, ≥5 sessions before 4, ≥4 weeks before trusting 12). It's marked PROPOSED.
- **Correction to earlier work**: my 2026-11-03 swing backtest said continuous futures OI starts around 2025-01. Today's measurement shows NIFTY from 2016 and RELIANCE from 2021 (F-HIST-6). That backtest's 2-year window was therefore a choice, not a data limit (Q-HIST-3). Its conclusions weren't re-run.
- `tests/test_dashboard_and_plumbing.py::test_lot_size_validation` passes against the hardcoded NIFTY lot of 75, while the live master says 65. That test locks in a stale value.
- The tick-storage estimate in architecture.md §4 (~9 M packets, ~1.6 GB a day for ~400 instruments) assumes about one tick per second. Cadence is unmeasured (Q-WS-1).
- The measurement runs used the dashboard's existing token through `dashboard.swing_scan._headers` (read-only GETs, about 40 calls at ≤3 per second). No WebSocket connection was opened and no orders were placed.
- `journal.db` and the exit-monitor state files are rewritten by live jobs, so they're excluded from the checksum comparison. The engine plan never writes to them.

## 7. Raw outputs

### 7.1 Existing test suite: `python3 -m unittest discover -s tests -v` (full file: `phase-0-evidence/unittest.txt`)
```
test_black_scholes_engine_importable (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_black_scholes_engine_importable) ... ok
test_black_scholes_pricing (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_black_scholes_pricing) ... ok
test_full_trade_validation (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_full_trade_validation) ... ok
test_gtt_validation (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_gtt_validation) ... ok
test_lot_size_validation (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_lot_size_validation) ... ok
test_market_session (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_market_session) ... ok
test_order_freeze_slicing (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_order_freeze_slicing) ... ok
test_order_safety_validation (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_order_safety_validation) ... ok
test_symbol_resolution (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_symbol_resolution) ... ok
test_trade_costs_calculation (test_dashboard_and_plumbing.TestZerodhaPlumbingInspector.test_trade_costs_calculation) ... ok
test_consistent_edge_across_days (test_day_test.TestDayTest.test_consistent_edge_across_days) ... ok
test_one_big_day_is_not_an_edge (test_day_test.TestDayTest.test_one_big_day_is_not_an_edge) ... ok
test_skips_none (test_day_test.TestDayTest.test_skips_none) ... ok
test_too_few_days (test_day_test.TestDayTest.test_too_few_days) ... ok
[... 49 test_mcx.* lines, all "... ok" — see unittest.txt ...]
----------------------------------------------------------------------
Ran 63 tests in 0.018s

OK
exit=0
```
pytest is not installed; the suite is stdlib `unittest`.

### 7.2 Module self-checks (`phase-0-evidence/selfchecks.txt`)
```
$ python3 -m dashboard.iv_rank selfcheck                → selfcheck ok  exit=0
$ python3 -m dashboard.liquidity_sweep selfcheck        → selfcheck ok  exit=0
$ python3 -m dashboard.news_sweep selfcheck             → selfcheck ok  exit=0
$ python3 -m dashboard.overnight_backtest selfcheck     → selfcheck ok  exit=0
$ python3 -m dashboard.oi_target_backtest selfcheck     → selfcheck ok  exit=0
$ python3 -m dashboard.rec_ledger selfcheck             → selfcheck ok  exit=0
$ python3 -m dashboard.regime_filter_backtest selfcheck → selfcheck ok  exit=0
$ python3 -m dashboard.premarket_gap_backtest selfcheck → selfcheck ok  exit=0
$ python3 -m dashboard.radar_exit_backtest selfcheck    → selfcheck ok  exit=0
$ python3 -m dashboard.swing_backtest selfcheck         → selfcheck ok  exit=0
```
(Compressed to one line each here; the file holds the raw two-line form.)

### 7.3 Frontend build (`cd dashboard/web && npm run build` = `tsc --noEmit && vite build`)
```
- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 1.32s
```

### 7.4 `scripts/verify_kite.py` without credentials
```
$ env -u KITE_API_KEY -u KITE_ACCESS_TOKEN python3 scripts/verify_kite.py
Set KITE_API_KEY and KITE_ACCESS_TOKEN in the environment.
exit=1
```
To run it yourself: `KITE_API_KEY=… KITE_ACCESS_TOKEN=… python3 scripts/verify_kite.py` (exit 0 = both calls OK).

### 7.5 Protected assets untouched
```
$ git status --short
?? dashboard/ignite_seen.json          (pre-existing, written by the radar job)
?? docs/architecture.md
?? docs/build-plan.md
?? docs/open-questions.md
?? docs/phase-0-evidence/
?? docs/verified-facts.md
?? scripts/
$ git diff --stat defa774
(empty)
$ diff protected-sha256-before.txt protected-sha256-after.txt   (headers excluded)
PROTECTED CHECKSUMS IDENTICAL
```

### 7.6 nifty-trading-lab test suite
`cd nifty-trading-lab && .venv/bin/python -m pytest -q` (raw: `phase-0-evidence/nifty-lab-pytest.txt`):
```
=========================== short test summary info ============================
FAILED tests/test_market_context.py::test_derivatives_are_discovered_from_current_instrument_metadata
FAILED tests/test_market_context.py::test_context_database_is_not_created_by_config_or_tests_in_project
2 failed, 276 passed in 1191.17s (0:19:51)
```
**2 failures in the lab's market-context module.** I did not investigate them (Phase 0, protected repo).
The second test name suggests it objects to `data/context/market_context_v1.sqlite3` existing inside the project.
The lab's market-context code should not be reused until these are understood. The lab's protected-file checksums
were identical after the run (re-checked: "LAB CHECKSUMS IDENTICAL AFTER PYTEST").

Stopping here for review.
