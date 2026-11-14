# Phase 10 report: React dashboard (read-only over backend state)

Date: built 2026-11-07 (IST, Saturday). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
- **Read first:** architecture.md, verified-facts.md, open-questions.md, decisions.md, questions-ledger.md, and the phase-0 … 9 reports.
- **Advisory and paper only.** No order placement exists; the UI has no order control. `test_no_order_methods_in_repo_code` passes.
- **Deployment is not done (Q-10-20).** The live `dashboard/web/dist` and the running server on :8080 are untouched. Every build and run used scratch directories and ports. See §9.

## 0. Headline

- **The F&O Engine tab exists.**
  - It is a lazy-loaded module (`dashboard/web/fo-engine/`) with its own design system: graphite with a periwinkle accent, Inter + JetBrains Mono.
  - It reads a new GET router, `/api/engine/*`, which accepts only loopback, same-origin requests.
  - All nine panels are built: A–H plus System health.
- **The existing app is unchanged.**
  - Its compiled CSS is byte-identical (sha256 `25dad898…` before and after).
  - Every visible existing tab is pixel-identical outside the nav strip, which gains one entry (§4).
- **Against the replayed session 2026-11-06, the dashboard shows what the engine knows, including what it doesn't:**
  - 86 recommendations, all REJECTED. The radar is empty until you tick "show rejected", and each rejected row lists its failed gates.
  - OI % is "—" everywhere, with reason OI_WINDOW_DISABLED (Q-6-5).
  - The positioning map has 97 of 97 underlyings "not evaluated".
  - 0 trades, so performance metrics are UNAVAILABLE, not 0.
  - The option chain says "available from Phase 11".
  - System health is UNAVAILABLE in replay, because its only snapshot is after the close (look-ahead guard, Q-10-17).

## 1. Questions and decisions

Asked once, at the start (rule Q2). Rows Q-10-1 … Q-10-21 are in [questions-ledger.md](questions-ledger.md).
- **Q-10-1 (BLOCKING):** stop and build Phase 9 first. Done the same day.
- **Q-10-2 (BLOCKING):** "do not proceed", then superseded by the owner's later "proceed with Phase 10" (D-46). 15 earlier BLOCKING rows stay OPEN: Q-0-2, Q-0-3, Q-0-6, Q-0-7, Q-0-8, Q-1-4, Q-3-1, Q-6-2, Q-6-5, Q-7-4, Q-7-5, Q-7-6, Q-7-8, Q-7-9, Q-7-10.
- **Q-10-3 (BLOCKING):** loopback + same-origin access (D-40), as built.
- **Q-10-4 … Q-10-11:** assumed at the start (module location, dependencies, theme, read model, SSE, visual method, replay session, radar default).
- **Q-10-12 … Q-10-21:** assumed during the build.
  - Dashboard thresholds are PROPOSED.
  - The frontend does unit formatting only.
  - POST routes exist for the Phase 9 forms.
  - Performance is not as-of.
  - The export is not scheduled.
  - The look-ahead guard.
  - Radar feature definitions.
  - Renderer noise in captures.
  - Deployment is left to you.
  - The cached Chromium is used.
- **D8 (NON-BLOCKING):**
  - The Radar was built first. The other sections were stubbed with "not built yet" text, which showed no numbers.
  - A screenshot next to an existing tab was taken before the other panels were built: `phase-10-evidence/screenshots/d8-radar-next-to-today.png`.
  - The build then continued without waiting, as the rule allows. Ask for design changes at any time.
- **Tests first (guardrail 14):**
  - The acceptance tests were written before the panels they cover were completed.
  - Four corrections to the tests during the build:
    - The Performance fixture collided: ACTUAL's expectancy was 222/2 = 111, so the numbers were changed to 111 and 250.
    - `/Inter/` matched `setInterval`, so the pattern was made exact.
    - The class scanner read the `[data-fo-engine]` selector as a class list, so selector strings are skipped.
    - The health assertion expected `data: null`, but the envelope correctly carries per-field reasons.

## 2. Existing app inspected (findings)

| Item | Finding | Used how |
|---|---|---|
| Router | No router library. `App.tsx` switches on a `TabId` state; `TabNav.tsx` holds the visible tab list | New `TabId` "foengine", one nav row, one `lazy()` route |
| Layout | `Header`, `TabNav`, a `<main>` max-width 1400 | Untouched; the module renders inside `<main>` |
| Theme | Dark default; `html[data-theme="light"]` set by Header (localStorage `theme`); colours are `:root` CSS variables in `src/index.css` | Untouched; the module observes the attribute read-only |
| Tailwind | 3.4.19, `tailwind.config.js` with content `./src/**`, no prefix, colours mapped to `--bg`, `--gold`, … | Untouched. The module has its own config (prefix `fo-`, scoped `important`, preflight off), and lives outside `src/` so the app's content glob never sees it |
| Fonts | System SF stack, IBM Plex fallbacks; no web fonts | Module fonts come from `@fontsource`, inside the module chunk only |
| Shared | react-query 5 (`QueryClientProvider`, 3 s default poll), motion, Toast | react-query reused (module queries poll 5–60 s, none in replay); nothing else shared |
| Tooling | Vite 5.4.21, TS 5.6 strict, no test runner | Added vitest 2.1.9 / RTL / jsdom / Playwright as devDependencies (§3) |
| Backend | FastAPI `dashboard/api_server.py` on 127.0.0.1:8080, CORS `*`, no auth, MCX router mounted in try/except | Engine router mounted the same way; access check per router (Q-10-3) |

## 3. Files

| File | Purpose |
|---|---|
| `engine/dashboard_export.py` (edge CLI) | `<date>/dashboard.sqlite`: Phase 4 primary/raw views + market context per 5-min mark, near-month 1m candles verbatim. 2026-11-06: 52,069 rows, 97 underlyings, 76 marks, ~2 min (`phase-10-evidence/dashboard-export-2026-11-06.txt`) |
| `engine/dashboard.py` (pure) | `envelope` (provenance, age, OK/STALE/UNAVAILABLE, look-ahead guard), `hypothesis`, `timeliness`, `radar_row`, `positioning_cell`, `performance` (one ledger, refuses another ledger's trade), `health` |
| `engine/api.py` (edge) | Router + `local_only` dependency; date validated by regex and `date.fromisoformat` before any path is built; read-only SQLite (`mode=ro`) closed after every request |
| `dashboard/api_server.py` | **edit:** one `include_router` block (same try/except as MCX) |
| `config/engine/v12.yaml` | v11 + `dashboard` (PROPOSED, Q-10-12) |
| `dashboard/web/src/App.tsx`, `src/components/TabNav.tsx` | **edits:** lazy import + route; one nav row ("09 F&O Engine") |
| `dashboard/web/package.json`, `package-lock.json` | **edits:** new exact pins only; no shared dependency upgraded (`npm ls --depth=0` diff shows additions only) |
| `dashboard/web/fo-engine/` | `FoEngineTab.tsx`, `core.tsx`, `api.ts`, `fo-design-tokens.ts`, `fo-tokens.css`, `fo-engine.css`, `tailwind.fo.config.js`, `panels/*.tsx` (9), `tsconfig.json`, `vitest.config.ts`, `playwright.config.ts`, `tests/` (component, isolation, visual spec + baselines, capture/shoot/compose scripts, bundle secret scan) |
| `tests/engine_tests/test_dashboard_api.py` | 15 backend tests |
| docs | `design-system.md`, this report, `phase-10-evidence/`, ledger Q-10-12 … 21, decisions D-45/46, architecture §17 |

Dependencies (verified on registry.npmjs.org on 2026-11-07, each version published before 2026-10-24):

| Package | Version | Kind |
|---|---|---|
| `lightweight-charts` | 4.2.3 | runtime |
| `@fontsource/inter` | 5.3.0 | runtime |
| `@fontsource/jetbrains-mono` | 5.3.0 | runtime |
| `vitest` | 2.1.9 | dev |
| `@testing-library/react` | 16.3.3 | dev |
| `@testing-library/dom` | 10.4.2 | dev |
| `jsdom` | 25.0.1 | dev |
| `@playwright/test` | 1.64.1 | dev |

## 4. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| INT | New tab inside the existing app; existing app inspected | DONE | §2; `isolation.test.ts` "existing-file edits are limited to the route and nav entry" (only App.tsx, TabNav.tsx under `src/`) |
| STK | React + TS + Tailwind at the app's versions; chart library verified; FastAPI REST + SSE | DONE | §3; `/api/engine/health/stream` (SSE) used by the System panel in live view |
| SEC | No Kite credentials to the frontend; local authenticated user only | DONE | `test_no_secret_is_read_or_returned`, `test_loopback_same_origin_only`, `test_router_requires_the_check_on_every_route`; live curl: cross-site 403, foreign Origin 403, `date=../../etc` 400; bundle scan below |
| R1 | No trading logic in the frontend; UNAVAILABLE ⇒ "—" + reason; no mock numbers | DONE (unit formatting only, Q-10-13) | `components.test.tsx` "renders UNAVAILABLE as an em dash with its reason…"; Option chain renders text only |
| R2 | Every panel shows data age; stale panels visibly marked | DONE | `Panel` + `AgeTag` on every panel; `components.test.tsx` "shows the data age … marks STALE visibly"; screenshots show STALE hatch (radar at 15:40 replay: newest recommendation 43 min old) |
| R3 | SIMULATED and ACTUAL visually distinct everywhere | DONE | dashed ◇ vs solid ◆ chips, separate sections and tabs; `components.test.tsx` both ledger tests |
| R4 | "Positioning hypothesis" language | DONE | disclaimers in Overview, Positioning, Signal (engine `G.DISCLAIMER`) |
| D1 | Global CSS / Tailwind config / theme / fonts / shared components untouched | DONE | `isolation.test.ts` "no diff in global style / theme / font files"; app CSS sha256 identical |
| D2 | One scoped root, no global selectors | DONE | `isolation.test.ts` "CSS is scoped to the module root" (2 CSS files); built module CSS: 102 top-level rules, all under `[data-fo-engine]` except `@font-face` |
| D3 | Separate Tailwind config, prefix, important scoped, preflight off | DONE | `isolation.test.ts` "tailwind module config…"; "every class in the module is fo- prefixed" (11 TSX files) |
| D4 | Portals inside the root | DONE | `Tip` → `[data-fo-portal]` inside the root; tested (tooltip's ancestors include `[data-fo-engine]`) |
| D5 | Fonts only for the module | DONE | `isolation.test.ts` "fonts load only in the module chunk"; fonts ship in the lazy chunk's CSS |
| D6 | Tokens in one file + scoped CSS variables, light and dark, semantic tokens | DONE | `fo-design-tokens.ts` + `fo-tokens.css`; `isolation.test.ts` tokens suite (CSS == TS, both themes, 8 semantic tokens) |
| D7 | Distinct look; tabular numerals; colour never the only signal | DONE | D8 screenshot; ▲/▼ + words, hatch + label, ◇/◆ |
| D8 | Radar first, screenshot next to an existing tab | DONE | `screenshots/d8-radar-next-to-today.png` |
| D9 | `docs/design-system.md` with an app-wide adoption guide | DONE | [design-system.md](design-system.md) §6 |
| A | Market overview | DONE (trend, positioning, VIX UNAVAILABLE on this data) | `dark-market.png`, `light-market.png` |
| B | Opportunity Radar: sortable, filterable, all columns, score with available max, timeliness, rejected behind a filter with reasons | DONE | `dark-radar.png` (default: empty, "86 rejected"), `dark-radar-rejected.png` |
| C | Positioning map: quadrants, suspected acc./dist., history scrubber, residual vs raw | DONE (all cells not evaluated on this data) | `*-positioning.png`, `*-positioning-raw.png` |
| D | Option chain placeholder, no fake data | DONE | `*-option-chain.png` |
| E | Signal detail: chart with VWAP / levels / zones / sweeps / structure marks; OI history with ages; confirmation timeline; score breakdown; opportunity age; evidence & contradictions; entry/exit criteria | DONE | `*-signal-open.png` (NIFTY, gaps for the 09:03–11:26 outage left blank) |
| F | Active trades: entry, qty/lots, current premium, P&L gross/net, stop, targets, decision, thesis, alerts | DONE (0 trades in the replay; rendering proven on fixtures) | `*-trades.png`; `components.test.tsx` active-trades test; `test_trades_and_performance_are_per_ledger` |
| G | Performance: daily/cumulative, win rate, expectancy, PF, drawdown, slippage, charges, breakdowns by strategy / time / instrument / score band / timeliness / regime; separate SIMULATED and ACTUAL tabs | DONE (regime UNAVAILABLE: no classifier; not as-of, Q-10-15) | `*-performance.png`, `*-performance-actual.png`; `test_metrics_for_one_ledger`, `test_never_mixes_ledgers` |
| H | Feedback forms (Phase 9) | DONE (POST, Q-10-14) | `*-journal.png`; `test_feedback_post_stores_and_changes_no_config` |
| SYS | Feed status, ticks/sec, stale instruments, gaps, allocator usage | DONE (UNAVAILABLE in replay of 2026-11-06: look-ahead, Q-10-17) | `*-system.png`; `test_health_from_status_files` |
| AT1 | Component test: UNAVAILABLE ⇒ "—" with reason | DONE | `values > renders UNAVAILABLE as an em dash…` |
| AT2 | Stale indicator when backend marks STALE | DONE | `panel age and staleness > …marks STALE visibly…` |
| AT3 | Simulated and actual never in the same total | DONE | 2 component tests + `test_never_mixes_ledgers` + `performance()` raises on a mixed list |
| AT4 | Visual regression of every existing tab (pixel-identical or differences explained) | DONE | §5 |
| AT5 | Grep test: no global selectors / unprefixed classes; no edits to global style files | DONE | `isolation.test.ts` (20 tests) |
| AT6 | Strict type-check; no secrets in the bundle | DONE | `tsc --noEmit` (app) and `tsc --noEmit -p fo-engine/tsconfig.json` (module incl. tests), exit 0; `bundle-secrets.py`: the real `kite_config.json` credential values and credential keywords searched across 42 built files — none found, exit 0 |
| RPT | Screenshots of each panel against a replayed session | DONE | `phase-10-evidence/screenshots/` (12 views × dark/light, replay 2026-11-06 15:40 IST) |

Mutation checks:
- **Frontend** (`phase-10-evidence/frontend-mutation-checks.txt`): 8 of 8 caught. The mutations were:
  - a global `body` rule
  - an unprefixed class
  - UNAVAILABLE rendered as 0
  - the stale mark removed
  - the portal pointed at `document.body`
  - the performance fetch ignoring the ledger
  - token drift
  - preflight on
- **Backend:** covered by the 15 tests above; this phase added no new risk logic.

## 5. Visual regression (existing tabs)

**Method.** Each visible existing tab was captured twice: on a scratch build made before any edit to `App.tsx` / `TabNav.tsx`, and on the Phase 10 build. In both captures:
- every `/api` call was stubbed to the same 503;
- the clock was frozen;
- JS animations were paused (the clock is paused after load);
- the viewport was 1440×900, full page.

Two tools:
- **Playwright** `toHaveScreenshot`, with the nav strip masked and `maxDiffPixels: 0`. 8/8 pass, and 3 stability runs on the baseline build were 8/8.
- **A direct PIL diff** of full pages (`visual-regression-direct.txt`).

| Tab | Pixels differing | Inside the nav strip | Outside |
|---|---|---|---|
| Today, Radar, Swing, Exits, Journal, Ideas, Screener, Commodities | 900 each | 900 each, all in the box x 1037–1144, y 98–130: the new "09 F&O Engine" entry | 0 in at least one before/after pair for every tab |

**Listed differences:**
1. **The new nav entry (expected).** It is the same 900 pixels on every tab.
2. **Renderer noise, not code.**
   - Radar, Swing and Commodities sometimes differ by 12 px (largest channel difference 2/255).
   - The same 12 px also appears between two captures of one unchanged build.
   - Every tab has before/after pairs with 0 px outside the nav strip.
   - An earlier runner-based capture showed 32 px (Exits) and 16 px (Today) at 2/255. A direct re-capture on a build containing only the nav entry, and on the full build, showed 0 px for both (Q-10-19).

The hidden tabs (Greeks, F&O Plan, Backtest, Plumbing) have no nav entry and cannot be opened, so they were not captured. Their code and the app CSS are unchanged.

## 6. Test output (raw)

Frontend: `npx vitest run -c fo-engine/vitest.config.ts`
```
 RUN  v2.1.9 /Users/turagasanthoshkumar/Clade-NSE-Skills/dashboard/web
 ✓ fo-engine/tests/isolation.test.ts (20 tests) 135ms
 ✓ fo-engine/tests/components.test.tsx (6 tests) 145ms
 Test Files  2 passed (2)
      Tests  26 passed (26)
exit=0
```
Visual: `npx playwright test -c fo-engine/playwright.config.ts` on the final build
```
  ✓  1 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Today (1.9s)
  ✓  2 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Radar (1.0s)
  ✓  3 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Swing (1.0s)
  ✓  4 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Exits (1.1s)
  ✓  5 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Journal (1.1s)
  ✓  6 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Ideas (951ms)
  ✓  7 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Screener (996ms)
  ✓  8 fo-engine/tests/existing-tabs.spec.ts:23:3 › existing tab Commodities (1.0s)
  8 passed (9.9s)
exit=0
```
Build: `tsc(app)+tsc(module, strict)+build exit=0`. App CSS `25dad8986851c36ceefbe28f252bdcfdce135ba231b3faaaa2bc52a750ec036b index-hfPMMTDg.css` (same as before Phase 10). Secret scan: `credential values from kite_config.json checked: ['access_token', 'api_key', 'token_refreshed_at'] -> found in bundle: none`, `credential keywords found: none`, `secret-scan exit=0`.

Backend: whole repo `python3 -m unittest discover -s tests -v` (full file `phase-10-evidence/full-suite.txt`). The Phase 10 tests:
```
test_date_is_validated_before_any_path_is_built ... ok
test_loopback_same_origin_only ... ok
test_no_secret_is_read_or_returned ... ok
test_router_requires_the_check_on_every_route ... ok
test_feedback_post_stores_and_changes_no_config ... ok
test_health_from_status_files ... ok
test_missing_stores_are_unavailable_envelopes ... ok
test_trades_and_performance_are_per_ledger ... ok
test_empty_ledger_is_unavailable_not_zero ... ok
test_metrics_for_one_ledger ... ok
test_never_mixes_ledgers ... ok
test_envelope_age_stale_and_unavailable ... ok
test_hypothesis_unavailable_vs_evaluated_neutral ... ok
test_no_look_ahead_in_a_replay ... ok
test_timeliness_mapping ... ok
FAIL: test_eod_compacts_writes_cadence_and_runs_retention (engine_tests.test_storage.TestAutomation.test_eod_compacts_writes_cadence_and_runs_retention)
Ran 267 tests in 36.845s
FAILED (failures=1)
exit=1
```
**The one failure is the pre-existing weekend wall-clock test (Q-9-24).**
- `engine/eod.py:44` skips alerts on weekends, and 2026-11-07 is a Saturday.
- With the clock pinned to a weekday it passes (`phase-9-evidence/preexisting-eod-failure-check.txt`).
- It is not related to Phase 10, and it was not changed.

## 7. Verified facts used

- **No new Kite / NSE / SEBI fact.**
  - The dashboard uses no kiteconnect method: `engine/api.py`, `dashboard.py` and `dashboard_export.py` never import it (test).
  - Session open/close for the replay slider come from config `sessions.fno` (served by `/sessions`, not hardcoded). That value is still Q-3-1.
  - Depth labels say "5 visible levels, pending orders, not a full book" (F-WS-5). Prices are exchange integers in paise (F-WS-9), formatted to ₹ for display.
- **npm package versions** were verified on the npm registry (§3). They are tooling, not market facts.

## 8. Known limitations

- **No real trade exists** (0 ENTRY_ELIGIBLE, Q-6-5 / Q-7-4 / Q-7-8). So F and G were shown on real data only in their empty state; their populated rendering is proven by tests and fixtures. No mock rows appear in the UI.
- **Positioning is UNAVAILABLE on real data** (OI windows disabled, Q-6-5): the map, the index positioning, the radar OI %, and the positioning score factor.
- **`dashboard.sqlite` needs `python3 -m engine.dashboard_export DATE`** after Phase 8 runs; it is not scheduled (Q-10-16).
- **System health has no per-time history**, so it is UNAVAILABLE in any replay before the day's last `status.json` (Q-10-17).
- **Performance is not as-of** (Q-10-15).
- **The positioning scrubber steps every 5 minutes**, not every minute (Q-10-12).
- **Charts are lightweight-charts canvases.** Their text is readable, but the chart content itself is not exposed to screen readers beyond an `aria-label`.
- **The SSE stream** keeps one generator per open System tab in live view and stops when the browser closes the connection.

## 9. To see it in the running dashboard (owner action, Q-10-20)

The engine router is mounted only when the server process restarts. `dist/` is the bundle the server serves:

```bash
cd dashboard/web && npm run build
```

```bash
launchctl kickstart -k gui/$(id -u)/com.clade.dashboard-server
```

```bash
python3 -m engine.dashboard_export 2026-11-06
```

The third command is already done for 2026-11-06; run it for each later date after `engine.signal_report`.

## 10. Follow-up 2026-11-07: dashboard data automated (owner request, Q-10-22)

- `engine/eod.py`: new `dashboard_chain(days)` called by the EOD CLI **before** compaction (the existing `com.clade.engine-eod` job, 15:50 weekdays; nothing new to install). Per recorded day: Phase 8 `signal_report` (needs `buffer.sqlite`) → Phase 9 `ledger run` (needs the buffer and signals done) → `dashboard_export` (needs snapshots; does not depend on Phase 8). Each is a subprocess with a 1800 s timeout and is skipped once its store records a run for its config version, so missed evenings are caught up. Results go to `eod_last.json`; a failed step fails the job's exit code.
- Config v13 = v12 + `dashboard.eod_step_timeout_s` (v12 kept unchanged, D-16). `dashboard_export` / the API now default to v13.
- Real run of the chain alone (`phase-10-evidence/eod-dashboard-chain-run.txt`): 2026-11-06 signals `done`, paper `done`, dashboard `ok` (v13 export, 1 min 58 s, same 37,248 states / 76 marks / 97 underlyings as v12).
- Fixed in passing: latest-config lookup sorted versions as text (`v9` > `v13`), now numeric (Q-10-23).
- Tests: `EodDashboardChain` (order and argv, done steps not rerun, compacted day → export only, failure skips dependents and fails the job, chain runs while the buffer still exists and compaction still follows) and `test_latest_config_version_is_numeric`. Whole repo: `Ran 272 tests`, `FAILED (failures=1)` — only the pre-existing weekend test (Q-9-24) (`phase-10-evidence/full-suite-after-eod-chain.txt`).
- Caveat: the EOD job is still SIGKILLed during compaction (Q-6-5), so its exit code stays failed; the chain runs first and is unaffected. The Mac must be awake at 15:50 (Q-0-3).
