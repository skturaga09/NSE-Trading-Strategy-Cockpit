# Open questions

Unverified facts and pending decisions. **Nothing here may be used as a value in code.** Where code
needs one of these, it becomes a config parameter with no default and the phase stops until it is set.

Status: OPEN = unanswered · ASK = needs the owner's decision · MEASURE = can be answered by the recorder

## Account / plan

| ID | Question | Why it matters | Status |
|---|---|---|---|
| Q-ACCT-1 | Which Kite Connect plan does this API key have, and does it include live WebSocket streaming and historical data? REST quotes and historical calls work today (F-ACCT-1), but no WebSocket connection has been made. | The recorder (Phase 1) depends on WebSocket `full` mode | ANSWERED 2026-11-05 for streaming: WebSocket full mode works (F-WS-10). Plan name still unconfirmed |
| Q-ACCT-2 | The token is refreshed by a headless login (`dashboard/scripts/refresh_kite_token.py`, Keychain secrets). Is that acceptable to keep as the only session source for the new engine? | The engine's broker adapter will reuse it, not build a new login | ASK |

## WebSocket (to measure in Phase 1)

| ID | Question | Status |
|---|---|---|
| Q-WS-1 | (Measured by `engine.oi_cadence` after the first full session → docs/measured-oi-cadence.md) Actual tick cadence per instrument in `full` mode, and how often the OI field changes on the tick stream (historical minute candles show ~every minute, F-HIST-8, but that is not the tick feed) | MEASURE |
| Q-WS-2 | Do index tokens send the documented 32-byte full packet on this account? | ANSWERED (F-WS-11) |
| Q-WS-3 | Reconnect/back-off behaviour and whether subscriptions must be re-sent after reconnect | ANSWERED from library source (F-WS-8); the recorder logs each reconnect attempt and the library resubscribes |
| Q-WS-4 | Are text (JSON) messages like order postbacks / errors sent on the same socket, and their format? | PARTIAL: `instruments_meta` text frame seen (F-WS-12). The recorder stores every text frame in `events`; others are still unmeasured |
| Q-WS-5 | Implementation: install the official `kiteconnect` Python library (its `KiteTicker` needs Twisted/Autobahn, not installed) **or** parse the documented binary packets with the already-installed `websockets` 17.0.1? | DECIDED 2026-11-05 (owner): kiteconnect 5.2.2, using KiteTicker only; packets decoded by engine/packets.py into raw ints |

## Historical data

| ID | Question | Status |
|---|---|---|
| Q-HIST-1 | Exact max range for `10minute`, `15minute`, `30minute` (15minute accepted 188 days; cap not reached) | MEASURE (cheap) |
| Q-HIST-2 | Does `continuous=1` return OI for **stock** futures before each name's earliest date reliably, and are roll days marked? (`dashboard/swing_backtest.py` drops roll weeks heuristically) | OPEN |
| Q-HIST-3 | Correction needed: project memory and `swing_backtest.py` comments say continuous OI exists only from ~2025-01; measurement shows NIFTY from 2016, RELIANCE from 2021 (F-HIST-6). The swing backtest's 2-year window was a choice, not a data limit. | Flag only — protected module not edited |
| Q-HIST-4 | Are expired **option** contracts' candles retrievable at all (tokens disappear from the master after expiry)? | OPEN |
| Q-HIST-5 | Meaning of OI = 0 in early continuous rows (2016 NIFTY): missing data or real zero? Treat as UNAVAILABLE until answered | OPEN |

## Market rules / reference data

| ID | Question | Status |
|---|---|---|
| Q-NSE-1 | OI update cadence as disseminated by NSE (official source) | OPEN |
| Q-NSE-2 | Trading holidays and session times for 2026–2027: `nifty-trading-lab/config/context/nse_sessions_2026.yaml` cites NSE circulars CMTR71775/CMTR72260 — re-verify against NSE before use | PARTIAL: F&O session hours (F-NSE-1) and **2026 F&O holidays** (F-NSE-5) verified. 2027 and cash-segment CAS times still unverified (Q-NSE-6) |
| Q-NSE-3 | F&O charges (brokerage, STT, exchange, SEBI, stamp, GST) for the period the engine will cost trades: `nifty-trading-lab/config/execution/zerodha_charges_2021_2026.yaml` has a versioned schedule with sources; `skills/backtest-expert` has its own cost function. Which is authoritative, and re-verify rates against zerodha.com/charges. **They disagree:** `evaluate_backtest.calculate_india_costs` uses futures STT 0.0125% on sell and a flat options exchange rate of 0.05%; the lab schedule has futures STT 0.02% from 2024-10-01. The backtest-expert model looks stale, but neither has been re-verified | ASK + OPEN |
| Q-NSE-4 | Market-wide position limit / ban-period list source for F&O names | ANSWERED (F-NSE-4): fo_secban.csv, fetched every refresh |
| Q-REG-1 | Any SEBI/NSE retail-algo changes after the April 2026 milestone | OPEN (context only) |

## Infrastructure / operating decisions

| ID | Question | Why | Status |
|---|---|---|---|
| Q-OPS-1 | Recorder universe: futures only (~219 names), futures + ATM±N options for indices, or the full option chain? Full-mode packets for 3000 instruments ≈ tens of millions of ticks/day | Sizes storage and connection count (3 × 3000 cap, F-WS-2) | DECIDED for Phase 1 (owner, 2026-11-05): NIFTY + RELIANCE HDFCBANK ICICIBANK INFY TCS near-month futures + spot (config/engine/v1.yaml) |
| Q-OPS-2 | Disk: the Mac has **21 GB free (90% used)** (`df -h`, 2026-11-05). Raw tick retention period and compression? | A tick archive can fill the disk within days | DECIDED (owner, 2026-11-05): raw kept 5 sessions, archived to ~/EngineArchive; disk guard 5/3/2 GB |
| Q-OPS-3 | The Mac sleeps on battery during market hours (missed today's 08:00 token refresh and morning scans; `caffeinate -s` only holds on AC). Is a dedicated always-on host available, or is "Mac on charger" the operating rule? | Phases 1–3 need ≥5 complete sessions | ASK |
| Q-OPS-4 | Storage engine: reuse SQLite (WAL) or add PostgreSQL + Redis (neither installed)? See architecture.md §Storage | ASK |
| Q-OPS-5 | Phase definitions 1–14: only Phase 0 text was provided. build-plan.md maps phases to modules as a PROPOSAL; the real phase texts are needed before Phase 1 starts | ASK |

## Findings in protected code (reported, not changed)

| ID | Finding | Status |
|---|---|---|
| Q-PROT-1 | `POST /api/trade/place` (`dashboard/api_server.py:753`) is a **mock** order: it writes `MOCK_ORD_*` to the local `trade_book.json`, never calls Kite. But it echoes a client-supplied `mode` in "Order executed successfully in {mode} mode", so a request with `mode: "live"` would *say* LIVE. No live order code exists (grep for `/orders` POST, `place_order`, `modify_order`, `cancel_order`: none). Rename/relabel? | ASK |
| Q-PROT-3 | `dashboard/zerodha_plumbing.py:30` hardcodes `LOT_SIZES` (NIFTY 75, BANKNIFTY 15, FINNIFTY 25, MIDCPNIFTY 50) and `FREEZE_LIMITS`. The instrument master today says **NIFTY lot = 65** (measured-kite.txt) — the constant is stale. The new engine will not use it (guardrail 6); fix or retire the constant in the old code? | ASK |
| Q-PROT-2 | `dashboard/app.py` (legacy stdlib server) still has `handle_place_trade` routes alongside FastAPI — same mock behaviour; is the legacy server still needed? | ASK |

## Added in Phase 1 (2026-11-05)

| ID | Question | Status |
|---|---|---|
| Q-STORE-1 | Long-term raw format: A (typed Parquet zstd, change-only ticks) vs B (zstd raw frames, decoded on replay). Both are written today. Pick by measured bytes/day and replay speed on the first full session (`engine.compact` writes `storage_report.json`) | MEASURE then ASK |
| Q-STORE-2 | Step 1 says duplicate ticks are "stored as received"; step 9 says "skip ticks where nothing changed except timestamps". These conflict for exact duplicates. Today the frames log keeps every frame as received and the ticks table is change-only. If B is retired, exact duplicates disappear from the record. OK? | ASK |
| Q-STORE-3 | The instrument master is ~1.66 MB/day gzipped (F-INST-4), about 0.6 GB/year, and it is kept forever as derived data. OK, or should it be kept as diffs? | ASK |
| Q-OPS-6 | Who runs `engine.compact` and `engine.retention` after the close? | ANSWERED 2026-11-05 (owner asked to automate): `scripts/launchd/com.clade.engine-recorder.plist` (weekdays 09:00 + 15-min retry, stops 15:45) and `com.clade.engine-eod.plist` (weekdays 15:50 → `engine.eod`). The owner installs them |

## Added in Phase 2 (2026-11-05)

| ID | Question | Status |
|---|---|---|
| Q-UNI-1 | What does fo_secban.csv look like on a day with **no** ban? Never observed. The parser accepts a header-only file as "no bans"; any other form (e.g. `NIL`) is rejected, so that day's ban status is RESTRICTION_UNVERIFIED (safe). | MEASURE (first no-ban day) |
| Q-UNI-2 | `BLOCKED_*_CONSTITUENTS` currently blocks **every** contract, INDEX family included, although NIFTY index F&O doesn't depend on the stock lists. Keep that, or let INDEX stay tradable? | DECIDED 2026-11-05 (owner): INDEX stays tradable; constituent flags apply to STOCK contracts only |
| Q-UNI-3 | The ban file is published for the next trade date by the evening (F-NSE-4). The 08:35 refresh should find today's date in it, but that is unmeasured. If it still shows yesterday's date, the day stays RESTRICTION_UNVERIFIED until a later refresh (the recorder's 09:00 start retries). | MEASURE (first 08:35 run) |
| Q-NSE-5 | Weekend sessions: a Saturday/Sunday not in any circular is treated as RESTRICTION_UNVERIFIED (not tradable), and so is the Muhurat session 2026-11-08 (timings not yet notified). No source was verified that says "no session on weekends". | OPEN |
| Q-NSE-6 | 2027 F&O holiday circular (and hours: F-NSE-9 changes them on 2026-12-07): until it is verified and added to config (`holiday_years`, `holidays`, `holiday_circulars`), every 2027 date is RESTRICTION_UNVERIFIED. NSE published the 2026 one on 12 Dec 2025. | OPEN (due ~Dec 2026) |
| Q-WS-1 note | Phase 2 subscribes everything in **quote** mode (owner confirmed 2026-11-05). Quote packets have no OI or exchange timestamp (F-WS-6), so the OI change log is empty and the Q-WS-1 cadence measurement waits for Phase 3 tiering | NOTE |
| Q-UNI-4 | `engine.eod.check_today` still alerts "NOTHING recorded today" on NSE holidays. The holiday calendar now exists (F-NSE-5) and could suppress it | DONE 2026-11-05 (owner asked): `check_today` skips all its alerts on a holiday whose circulars were re-verified that day; unverified ⇒ alerts still fire |

## Added in Phase 3 (2026-11-06)

| ID | Question | Status |
|---|---|---|
| Q-NSE-7 | **Cash-market close.** ANSWERED 2026-11-06 (F-NSE-7/9): F&O stocks' CTS ends 15:15 (CAS 15:15–15:35, auction print from 15:30) from 2026-08-03; from 2026-12-07 CTS to 15:30, CAS 15:30–15:40, derivatives to 15:45 (expiring index contracts 15:30 on expiry days). Config `sessions`/`market_hours` are single values and are wrong for cash now and for F&O from 2026-12-07. How to model it (date-effective sessions, a CAS window, the expiry-day index exception) | ASK |
| Q-OPS-3 update | Mac slept on battery 09:00–09:57 on 2026-11-06 despite `caffeinate -s` (AC only), F-WS-15. Recorder rule "Mac on charger" or an always-on host is still undecided | ASK |
| Q-OPS-4 | Live store | DECIDED 2026-11-05 (owner): no Redis; SQLite per day + event stream + in-process map; EOD → Parquet |
| Q-STORE-4 | Snapshot volume: ~810 B/candle row as JSON; 112 MB by 11:40 on 2026-11-06 (the stuck morning wrote ~85k EMPTY rows). EOD compaction to Parquet decided (owner 2026-11-06); measure the compressed size at the first EOD | MEASURE |
| Q-HIST-6 | Is Kite historical minute `volume` the same quantity as our tick-delta candle volume (same minute, same token)? Relative volume divides one by the other; unverified until compared on a full session | ANSWERED 2026-11-07 by measurement (F-HIST-11, Q-3-4): same quantity. Spot per-minute values shift at minute boundaries (receive-time buckets) |
| Q-CFG-1 | v3 changed under the same version string on 2026-11-06 | DONE 2026-11-06 (owner): split. `v3.yaml` = the morning bytes (sha256 66d7eb60…, verified against `meta`); `v4.yaml` (default) = the 11:34 values; the 11:34 run is recorded as v3 / sha256 b732f9de… |
| Q-QUAL-1 | `quality.stale_price_s: 10` marks far/next-month futures STALE often: every STALE incident after the 11:34 restart was a future, mostly Dec/Jan expiries (change-only ticks: no change in 10 s = no new data). Keep, or make thresholds per instrument kind? Review with the EOD `feed_report.json` | ASK |
| Q-WS-1 | OI cadence on the tick stream: now measurable (tier A futures in full mode; 659 OI changes in the first minutes after the 11:26 restart). The EOD job writes docs/measured-oi-cadence.md | MEASURE (first full day) |

## Added in Phase 4 (2026-11-06)

| ID | Question | Status |
|---|---|---|
| Q-CFG-2 | `config/engine/v5.yaml` (= v4 + `positioning`) is loaded only by `engine.positioning`. `engine.config.DEFAULT_PATH` stays v4 so the recorder running today is untouched. Switch the global default to v5 after the 2026-11-06 EOD? | ASK |
| Q-POS-1 | The primary view is mostly OI_STALE: combined OI is DEGRADED whenever a Dec/Jan component's OI has not changed for `quality.stale_oi_s` (300 s), and far months often go 15–100 min without a change. Owner kept it strict (2026-11-06); decide together with Q-QUAL-1 (per-instrument staleness) | ASK (with Q-QUAL-1) |
| Q-POS-2 | history.sqlite is filled by a manual backfill (last run 2026-11-05). Nothing refreshes it daily, so after today the distributions age and `*_oi_chg_prev_close_pct` becomes UNAVAILABLE ("previous session not in the history store"). Schedule `engine.backfill` in EOD? | ASK |
| Q-POS-3 | Sector residual skipped: no sector mapping from an official source is in verified-facts (phase text: skip and note) | OPEN |
| Q-POS-4 | ROLLOVER_WINDOW is read as "suppress the near-month view, flag the combined views" (phase text: "combined OI mitigates but still flag"). Confirm | ASK |
| Q-POS-5 | Only events are stored (`<date>/positioning.sqlite`). Per-minute states are recomputed by the CLI (deterministic, ~90 s per day), not persisted, and nothing runs live inside the recorder. Persist states or run live? (Phase 13/14 will need one of them) | ASK |
| Q-POS-6 | RVOL divides tick-built volume by a Kite historical volume baseline; equivalence is Q-HIST-6 (unverified) | ANSWERED 2026-11-07 (F-HIST-11): equivalent for futures |

## Added in Phase 5 (2026-11-06)

| ID | Question | Status |
|---|---|---|
| Q-CNDL-1 | **Phase 3 finding.** The 2026-11-06 snapshots (EOD replay) have no candle that ends at 15:40. For every token the last 1m candle is 15:38-15:39, the last 5m is 15:30-15:35 and the last 15m is 15:15-15:30, so the 15:39 minute and the cut final 5m/15m buckets are missing. The minute after the last one is probably never finalized (the stream clock stops before 15:40 + finalize delay). Phase 5 uses what exists; the end-of-day LevelMap price is the 15:38 close. Fix in Phase 3? | ASK |
| Q-STR-1 | PDH/PDL/PDC and PWH/PWL come from history.sqlite, which nothing refreshes daily (Q-POS-2). Without a backfill after each session, the next day has **no** previous-day levels (not wrong values: the detections are absent). The re-run at 3 sessions needs 2026-11-06 and 2026-11-09 in the store | ASK (with Q-POS-2) |
| Q-STR-2 | Rejection/reaction RVOL divides tick-built candle volume by a Kite historical volume baseline (Q-HIST-6, unverified). Some values look implausible (BOSCHLTD 3m 14:36: 60x) | ANSWERED 2026-11-07 (F-HIST-11): equivalent; BOSCHLTD's spike is real volume (tick = Kite in every minute 14:30–14:40) |
| Q-STR-3 | "COMPLETE and quality OK" excludes COMPLETE bars marked STALE (no tick in the last 10 s of the bar) and DEGRADED. Today 59.8 % of near-month 3m bars were usable, most of the loss being the 09:03-11:26 outage; COMPLETE+STALE was about 4 %, mostly illiquid names. Revisit with Q-QUAL-1 | ASK (with Q-QUAL-1) |
| Q-STR-4 | LevelMap reports distance in the ATR of every timeframe (3m/5m/15m) and does not pick one; swept or broken swings remain obstacles. Phase 6 may need one ATR and an "active level" rule | ASK (Phase 6) |
| Q-STR-5 | CHoCH heuristic as built: in an UP (DOWN) trend, the first close below (above) the last confirmed swing low (high), at most one per trend state. Labelled HEURISTIC. Confirm | ASK |
| Q-STR-6 | Detections are produced by the batch CLI only (deterministic, ~10 s per day); nothing runs live in the recorder (cf. Q-POS-5) | ASK |

## Added in Phase 6 (2026-11-06)

| ID | Question | Status |
|---|---|---|
| Q-OPP-1 | VWAP_EXTENSION uses the setup timeframe's ATR (3m for most setups). On 2026-11-06 it fired on 14,029 evaluations, with a median distance of 6.1 ATR (p90 9.5): on a trending day the session VWAP is many 3m ATRs away, so EXHAUSTED is common (25.5 % at confirmation). Change the ATR or the multiple? Decide with Q-STR-4 | DECIDED 2026-11-06 (owner): **15m ATR** for VWAP extension, whatever the setup timeframe. Config v8 (`opportunity.exhaustion.vwap_atr_timeframe_min: 15`). Re-run: 8,599 flagged evaluations, median 3.47 × 15m ATR; EXHAUSTED at confirmation 16.0 % (was 25.5 %) |
| Q-OPP-2 | A 1m close **equal** to the stop counts as invalidation (conservative). Two defended zones were invalidated at their own confirmation this way | DECIDED 2026-11-06 (owner): **keep** — a close equal to the stop invalidates (long and short); locked by `test_invalidation_and_retest_expiry_end_the_setup` |
| Q-OPP-3 | `current_rr_net` is NET_UNAVAILABLE. The phase text expects "Phase 7's cost model"; the charges schedule itself is still unverified (Q-NSE-3) | OPEN |
| Q-OPP-4 | Guardrail 8 (source, exchange / receive / processing timestamps, age on every derived value). Phase 6 evaluations carry them for the price input; Phase 5 detections carry only candle-close times (no receive time). Adding them changes the Phase 5 `Detection` interface | ASK |
| Q-OPP-5 | MFE/MAE need every 1m bar in the horizon to be usable (COMPLETE + OK). 5,265 of 20,181 MFE/MAE rows on 2026-11-06 are UNAVAILABLE for that reason (plus 3,962 NEVER_TIMELY and 1,140 past the close). Strict on purpose; revisit with Q-QUAL-1 | ASK (with Q-QUAL-1) |
| Q-OPP-6 | The timing recorder runs inside the CLI after the close (as_of = 15:40). Nothing schedules it: add to the EOD job (with Q-POS-2 / Q-STR-1, since it needs fresh history)? | DECIDED 2026-11-06 (owner): run it in the EOD job — `engine.eod` calls `engine.opportunity.eod` after the cadence doc; catch-up of any recorded day not done for the current config. Blocked in practice by Q-EOD-1 |
| Q-OPP-7 | No Phase 4 positioning setups exist yet (2026-11-06: 0 events; cause = OI_WINDOW_DISABLED for 37,238 of 37,248 primary evaluations because the cadence doc does not exist, Q-EOD-1 — not mainly OI_STALE), so "did price move before the positioning signal?" has no data. The wiring is tested with a fixture event | OPEN (with Q-POS-1) |
| Q-EOD-1 | **The EOD job is being killed.** 2026-11-06: the 15:50 launchd run and two manual runs (21:24, 21:33) all died with SIGKILL (exit 137, empty logs) during the Phase 1 raw compaction of 2026-11-06 (buffer.sqlite 385 MB + frames.bin 446 MB; 8 GB Mac, heavy paging; kernel log gave no reason). Snapshot compaction (15:53) had finished. Effects: raw buffer not compacted, `eod_last.json` stale (2026-11-05), **`docs/measured-oi-cadence.md` never written ⇒ Phase 4 disables every OI window** (and so Phase 6 has no positioning setups), retention and the Phase 6 EOD step never reached. Fix the compaction's memory use (Phase 1) — how? | FIXED 2026-11-07 (owner: fix it): streamed compaction, peak 1.13 GB on 2026-11-06, cadence doc written — see questions-ledger Q-6-5 |

## Added in Phase 7 (2026-11-06)

| ID | Question | Status |
|---|---|---|
| Q-COST-1 | Brokerage, exchange, SEBI, stamp, IPFT and GST rates (F-COST-1/3/4/5/6) were read as current on 2026-11-06, but no source states when they took effect. Their config entries use `effective_from: 2026-11-06` (the read date), so any trade date before it is costed UNVERIFIED. Only STT has an official start (2026-04-01). Find the NSE circular for 0.00183 % / 0.03553 % (third-party pages still list 0.00173 % / 0.03503 % from 2024-10-01), or accept the read date | OPEN |
| Q-COST-2 | zerodha.com/charges says "SEBI charges will be reduced to ₹15 per crore once the regulator announces a date". ₹15 is not a reduction from ₹10, so the wording is unclear. Until a dated SEBI source exists, config keeps ₹10 / crore | OPEN |
| Q-COST-3 | Kite's virtual contract note (`POST /charges/orders`, F-MARGIN-1) could check the cost model against Zerodha's own numbers, and contract-note rounding is not modelled. Wire it at the edge? | ASK |
| Q-RISK-1 | **Futures margin is always MARGIN_ESTIMATED at full notional** (`contracts.futures_margin.fraction: 1.0`). The Kite margin API (F-MARGIN-1) is a POST and lives only on the `KiteConnect` class, which the engine bans, and the broker adapter is GET-only by design. Wiring it means adding a POST method to `engine/broker.py`. Without it, or a lower fraction backed by a source, **no stock or index future fits the ₹1,00,000 per-trade capital limit** (10 of 10 on 2026-11-06). The selector already accepts `margins={token: INR per lot}` (`MARGIN_API`). Add the POST call? | ASK (blocking for futures) |
| Q-RISK-2 | Every `contracts.*` and `risk.*` value in v9 is PROPOSED, not an owner decision: capital ₹2,00,000 (the dashboard's figure), 20 % reserve, ₹1,00,000 max per trade, ₹2,000 max risk per trade, ₹6,000 daily loss, 3 open positions, 5 trades a day, 3 losses then a 60 min cooldown, max spread 0.05 % futures / 2 % options, spread ≤ 20 % of the move to T1, net R:R ≥ 1.5, slippage ≤ 0.05 % / 2 %, volume ≥ 200 / 1,000 lots, OI ≥ 500 lots, depth ≥ 1 × order, cutoff 15:00, min DTE 2, premium model 30 bars / 20 pairs / R² 0.5, no-depth slippage 1 × spread, gap risk 1 ATR | ASK |
| Q-RISK-3 | Event days are a config list (`risk.event_days: []`, empty). Sourcing an event calendar is Phase 8's job, so until then the EVENT_DAY check blocks nothing | ASK (Phase 8) |
| Q-RISK-4 | `PortfolioState` (P&L, open positions, trades, consecutive losses, the latched worst P&L of the day) is an input. No paper ledger exists yet (Phase 11), so the report uses a flat state. The daily-loss latch depends on the caller tracking `worst_day_pnl_inr` | OPEN (Phase 11) |
| Q-CON-1 | **No option contract has ever been recorded** (2026-11-06: 0 CE/PE tokens in ticks or depth; tier C, "options selected by later phases", is unused). So on real data every option candidate is NO_TRADE (NO_PREMIUM_MODEL + DATA_NOT_OK:NO_QUOTE), and options cannot be evaluated until ATM ± N strikes are recorded. Which strikes and expiries go into tier C, and from when? | ASK (blocking for options) |
| Q-CON-2 | Option quantities are assumed to be in units like futures (F-QTY-1 measured futures only). Verify on the first recorded option session | MEASURE |
| Q-CON-3 | Interface: Phase 0 planned `select_contract(direction, chain, master, cfg, now) -> ContractChoice` and `size_position(choice, stop, budget, charges, cfg) -> SizedPlan`; neither was ever built. Phase 7 built the phase text's shapes instead: `select_contracts(setup, contracts, tradable, quotes, spot, bars, margins, cfg) -> Selection` (sizing inside) and `risk_check(candidate, portfolio_state, cfg) -> RiskDecision`. No built interface changed. Replace the Phase 0 entries (as for Phases 4 and 5)? | ASK |
| Q-CON-4 | Net R:R includes the full round-trip charges. On 2026-11-06, ₹962 of charges on one NIFTY lot (STT alone ~₹810) took a Phase 6 TIMELY setup (gross R:R ≥ 1.5 at its evaluation) to **0.07 net**. Phase 6's gross `min_rr: 1.5` lets through setups that the cost model then rejects. Intended (Phase 6 is gross by design, Q-OPP-3)? | NOTE |

## Added in Phase 11 (2026-11-07)

| ID | Question | Status |
|---|---|---|
| Q-EVT-1 | Minimum prior intimation a listed company must give NSE before a board meeting (results / other purposes). Unverified, so a symbol absent from the event calendar is labelled NO_KNOWN_EVENT, never "no event" | OPEN |
| Q-OPT-1 | Physically settled stock options (F-OPT-2) may trade away from Black-76 values near expiry (delivery margins). Not modelled; `options.min_dte_days`-style gates and the existing EXPIRY_DAY check apply | OPEN |
| Q-OPT-2 | Option feed quantity units (Q-CON-2 / Q-7-9) | MEASURE on the first recorded option session (2026-11-09) |
