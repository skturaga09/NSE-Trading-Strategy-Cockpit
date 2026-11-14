# Build plan — phases 1–14

**PROPOSED.** Only the Phase 0 text has been provided. Each phase's name and scope below is
inferred from three things: the module list in Phase 0 task 5, and the owner's timing rules (Phases
1–3 need live market hours; ≥5 recorded sessions before Phase 4; ≥4 weeks of data before trusting
Phase 12). The real phase texts replace this mapping (Q-OPS-5). Nothing here is built.

Every phase follows the global guardrails:
1. Read the earlier `docs/phase-*-report.md` files first.
2. Write tests first, using fixtures and no live calls.
3. Keep logic pure, with thresholds in versioned config.
4. Paste the raw test output.
5. Write `docs/phase-N-report.md`.

Modules are numbered as in [architecture.md](architecture.md) §2.

## Phase 1 — Read-only broker adapter, instrument master, config, recorder skeleton (live validation)

Pre-conditions: Q-ACCT-1 (WebSocket entitlement), Q-WS-5 (library vs own parser), Q-OPS-1/2 (universe, disk), Q-OPS-3 (always-on host) answered.

| File | Content |
|---|---|
| `engine/__init__.py` | package marker |
| `engine/core/types.py` | `IST`, `Unavailable`, `Provenance`, `Maybe`, `DepthLevel`, `Observation`, `Instrument`, `EngineConfig` (architecture §5) |
| `engine/core/config.py` | `load_config(path) -> EngineConfig`. Reads YAML (PyYAML 6.0.3 installed), computes SHA-256, **fails on any unset no-default key** |
| `config/engine/v1.yaml` | the recorder universe rule, connection/back-off parameters, retention. Values from open questions are left empty on purpose |
| `engine/broker/kite_rest.py` | `KiteRest(BrokerAdapter)`: `instruments`, `quote`, `historical` only; per-endpoint rate limiter (F-RATE-1..3); range-cap guard (F-HIST-5); token read from the existing `kite_config.json` / env, never logged |
| `engine/broker/kite_ws.py` | WebSocket connect / subscribe / mode-set for `full` (F-WS-1..3), per the Q-WS-5 decision; reconnect per Q-WS-3 once verified |
| `engine/instruments/master.py` | `load_master`, `InstrumentMaster` (pure), `snapshot_to_db` (edge) |
| `engine/store/db.py` | opens `data/engine/engine.db` (WAL), creates the §4 tables |
| `engine/store/raw_archive.py` | append-only daily raw-packet archive with `received_ts` framing; `RawArchive.read(day)` iterator |
| `engine/recorder/run.py` | `Recorder.run` + CLI; writes `recorder_session` |
| `scripts/launchd/` (engine plists) | master 08:30, recorder 09:00–15:35. **The owner installs them** (persistent jobs) |
| `tests/engine/test_no_order_code.py` | repo-wide scan: fails if order endpoints or `place/modify/cancel_order` appear in `engine/` |
| `tests/engine/test_master.py`, `test_config.py`, `test_rate_limit.py`, `test_raw_archive.py` | fixture-based |

Acceptance (proposed):
1. Fixture tests pass.
2. One live session is recorded end to end, with `recorder_session` showing connections, reconnects and gaps.
3. The raw archive replays byte-exact.
4. No order code exists.

## Phase 2 — Ingestion, observation store, data quality (live validation)

| File | Content |
|---|---|
| `engine/ingest/parse.py` | `parse_packet` for ltp/quote/full and index packets per the F-WS-4/5/7 byte tables. Fields absent from a mode become `Unavailable("not in <mode> packet")` |
| `engine/ingest/validate.py` | sanity checks (OHLC order, non-negative OI/volume, `exchange_ts` monotonic per token); failures are flagged, never fixed |
| `engine/ingest/gaps.py` | `detect_gaps` against config cadence (value from Q-WS-1 measurement) |
| `engine/ingest/load.py` | archive → `observation` rows (idempotent, keyed by `raw_ref`) |
| `engine/ingest/report.py` | per-session data-quality report: coverage per token, gap list, OI-change cadence (answers Q-WS-1) |
| `tests/engine/fixtures/packets/*.bin` | packets hand-built from the documented layout, plus recorded ones after Phase 1 |
| `tests/engine/test_parse.py`, `test_validate.py`, `test_gaps.py`, `test_load_idempotent.py` | — |

Acceptance (proposed):
1. Parser round-trips documented fixtures.
2. Observations reconcile with REST `/quote` snapshots taken during the session (same token, close timestamps), with the mismatches listed.
3. A quality report exists for ≥1 live session.

## Phase 3 — Candles + reconciliation (live validation)
Build candles from observations: 1-min and 5-min, with `complete` flags. Volume is the difference of
cumulative day volume. A separate loader turns Kite historical candles (F-HIST-2/3) into the same `Candle` type.
Acceptance would compare self-built candles with Kite's minute candles for the same tokens and sessions
and report every difference. Nothing gets adjusted to make them match.
Start the ≥5-session recording clock here.

## Phase 4 — Futures positioning (needs ≥5 recorded sessions)
Price × OI quadrant per futures contract and window, from candles. Labels describe the data
("price up, OI up"), never intent. Roll-window detection comes from the data, reusing the
`swing_backtest` roll-week logic. Output is `PositioningState` with provenance and config version.

## Phase 5 — Structure and liquidity
Swing pivots, support/resistance and sweep events as pure functions over candles. This reuses
`structure_exit.py` / `liquidity_sweep.py` semantics by import. Earlier results stay on record:
the sweep failed out of sample (memory note, 2026-10-22). That is context, not a gate.

## Phase 6 — Opportunity age and timing
How long a positioning or structure condition has held, when it was first seen, and the range used
so far against ADR. All are pure functions with `now` as an input.

## Phase 7 — Option chain and contract selector
Chain snapshots from observations: IV via `option_chain._iv`, plus IV rank. A contract selector applies
liquidity, spread, DTE and strike constraints, all from config. Strikes, intervals and expiries come only from the master.

## Phase 8 — Event gates
Scheduled events, results dates, expiry-day rules and the F&O ban list (Q-NSE-4). Sources must be
in verified-facts first. A gate blocks or annotates; it never creates a candidate.

## Phase 9 — Risk engine
Sizing from a rupee risk budget and the master lot size. Charges come from one versioned schedule (Q-NSE-3).
Includes daily loss and position caps. Pure.

## Phase 10 — Signal engine
Combines the outputs of Phases 4–9 into `Signal` objects carrying reasons, inputs, provenance and config
version. Ambiguous combinations resolve to *no signal* (guardrail 16).

## Phase 11 — Paper trading and monitoring
Simulated fills against recorded or live depth (5 levels only, labelled as such). Monitoring of open paper
positions. A separate DB from `journal.db` and `trade_book.json`.

## Phase 12 — Backtest / replay + analytics (trust only after ≥4 weeks of recordings)
Replays the raw archive through the identical pure code path. Results are out of sample and net of cost,
using day-clustered significance (`swing_journal.day_test`) and `backtest-expert`. Nothing is
reported as an edge below the configured minimum days and sample.

## Phase 13 — API
GET-only FastAPI router mounted into the existing server (pattern: `dashboard/api/mcx.py`). Every response
carries provenance and age. Never returns secrets.

## Phase 14 — Dashboard
A new React tab in `dashboard/web`. Every value shows its source and age, approximations are labelled
APPROXIMATE, and there is no order button.
