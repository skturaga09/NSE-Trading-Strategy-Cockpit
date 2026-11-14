# F&O Positioning Engine — architecture (Phase 0 plan)

Status: **PLAN, not built.** Written 2026-11-05. Facts referenced as `F-…` are in
[verified-facts.md](verified-facts.md); `Q-…` are in [open-questions.md](open-questions.md).

Hard rules carried into every module: advisory and paper-trading only. **No function that places,
modifies or cancels an order may exist** (enforced by a repo-wide test from Phase 1). Strategy and
classification logic are pure functions (time is an input). Every threshold is in versioned config.
Missing data is `UNAVAILABLE(reason)`, never filled.

---

## 1. Protected assets (must stay untouched)

Baseline checksums: [phase-0-evidence/protected-sha256-before.txt](phase-0-evidence/protected-sha256-before.txt).
Git-tracked assets are protected by `git diff` against commit `defa774`.

**Live and paper trade records (data)**
- `dashboard/journal.db`: tables `trade_journal` (96 rows), `swing_signals` (944), `rec_ledger` (1547), `iv_history` (1800), `news_items` (1091), `decision_log` (1). Gitignored. **Written continuously by the live launchd jobs**, so its checksum changes without anyone editing it. The engine never writes to it.
- `dashboard/trade_book.json` (mock/paper positions), `dashboard/fno_nav_history.jsonl` (daily F&O NAV).
- Exit-monitor state: `dashboard/exit_config.json`, `exit_levels.json`, `exit_peaks.json`, `exit_*_seen.json`, `exit_summary.json`, `exit_candidate_last.json`, `ignite_seen.json`.
- `dashboard/kite_config.json` holds the **access token**. Never read into logs, never sent to the frontend.
- `~/Documents/Codex/2026-08-11/nifty-trading-lab/data/paper/paper_trading_v1.sqlite3` (lab paper trades).

**Strategies and configs**
- Live strategy and scan modules in `dashboard/`: `swing_scan.py`, `fno_scanner.py`, `intraday_ignite.py`, `exit_monitor.py`, `structure_exit.py`, `thesis.py`, `position_prob.py`, `target_calc.py`, `mcx_setups.py`, `rec_ledger.py`, `swing_journal.py`, `iv_rank.py`, `news_sweep.py`.
- `config/broker_mcx_operations.json`, `config/mcx_contract_profiles.json`, `config/mcx_events.json`.
- `skills/*` (10 skills, including `backtest-expert` and `options-strategy-advisor`).
- launchd jobs: `dashboard/scripts/launchd/com.clade.*.plist` (12) and token refresh `dashboard/scripts/refresh_kite_token.py`.
- nifty-trading-lab: `config/strategies/nifty_0945_one_trade_v1.yaml`, `config/experiments/*.yaml` (frozen candidates), `config/execution/*.yaml`, `config/regime/*.yaml`, `config/context/*.yaml`.

**Historical datasets (read-only inputs)**, in `~/Documents/Codex/2026-08-11/nifty-trading-lab/data/processed/`:

| Dataset | Format | Granularity | Range | Volume | OI |
|---|---|---|---|---|---|
| `nifty50_5m_2021_2026.csv` | CSV `timestamp,open,high,low,close`, tz +05:30 | 5-min, NIFTY 50 **index** | 2021-01-01 09:15 → 2026-07-31 15:25, 103,238 rows, 1,383 days | no | **no** |
| `nifty50_15m_2021_2026.csv` | same | 15-min index | 2021-01-01 → 2026-07-31, 34,418 rows | no | no |
| `universe_daily_kite/*_day_2021_2026.csv` (182 files) | CSV `timestamp,open,high,low,close,volume` | daily, Nifty-200 **cash** | 2021-01-01 → 2026-08-18 | yes | no |
| `universe_intraday/*_5m_2021_2026.csv` (11 large caps) | CSV OHLC | 5-min cash | 2021-01-01 → 2024-12-31 | no | no |

Each dataset has an `*.audit.json`. The 5-min file's SHA-256 matches its audit `processed_sha256` (`926a901a…`), so the file is intact. These files are iCloud "dataless" placeholders that download on first read, so the first access is slow.

**None of the historical sets contain OI.** OI history is available live from Kite instead (F-HIST-3, F-HIST-6).

---

## 2. Module map

`R` = reuses existing code (path given); `N` = new. All new code goes in a new top-level package
`engine/`, so no protected module is edited. Existing code is **imported, never copied**.

| # | Module | Responsibility | Reuse |
|---|---|---|---|
| 1 | `engine/broker/` broker adapter | Read-only Kite REST and WebSocket access with rate limiting (F-RATE-1..3). **No order methods.** | R: session from `dashboard/scripts/refresh_kite_token.py` + `kite_config.json` (token source); REST call pattern from `dashboard/option_chain.py` / `fno_scanner.py` |
| 2 | `engine/instruments/` instrument master | Daily dump (F-INST-1..3) stored as a dated snapshot. Lookups for futures, options, strikes, expiries and lot sizes. | R: parsing approach of `fno_scanner._instruments`, `swing_scan._futures_map`. **Not** `zerodha_plumbing.LOT_SIZES` (stale, Q-PROT-3) |
| 3 | `engine/recorder/` recorder | WebSocket `full`-mode capture (F-WS-3..6). Archives raw packets losslessly with receive timestamps. Gap and reconnect log. | N (Q-WS-5: library vs own parser) |
| 4 | `engine/ingest/` ingestion | Packet → `Observation` parse (documented byte layout), validation, UNAVAILABLE marking, gap detection | N |
| 5 | `engine/candles/` candles | Builds candles from observations, with completeness flags. Separate loader for Kite historical candles (F-HIST-*). Volume = difference of cumulative day volume; never interpolated. | R: candle fetch helpers in `fno_scanner._daily`, `swing_backtest._fetch` (patterns) |
| 6 | `engine/positioning/` futures positioning | Price × OI quadrant per futures contract and window (price up + OI up, etc.). Labels describe the data only, never "institutional buying". | R: buildup quadrant logic in `dashboard/swing_scan.py` (rule semantics); roll-week detection from `swing_backtest.evaluate` |
| 7 | `engine/structure/` structure and liquidity | Swing pivots, support/resistance, sweep events | R: `dashboard/structure_exit.py`, `swing_scan._levels`, `liquidity_sweep.py` detector |
| 8 | `engine/timing/` opportunity age and timing | How long a condition has held, time since first seen, room left vs ADR | R: ADR room-left logic `fno_scanner._adr_pct`; first-seen freezing pattern `rec_ledger` |
| 9 | `engine/contracts/` contract selector | Picks a futures or option contract (expiry, strike) under liquidity, spread and DTE constraints | R: `dashboard/option_chain.py` (`_bs`, `_iv`, chain build), `iv_rank.rank` |
| 10 | `engine/risk/` risk engine | Sizing from a risk budget with the lot size from the master. Charges from versioned config. Daily loss and position caps. | R: cost model `skills/backtest-expert/scripts/calculate_india_costs` **or** lab `zerodha_charges_2021_2026.yaml` (Q-NSE-3) |
| 11 | `engine/signals/` signal engine | Pure combination of module outputs into `Signal` objects that carry `config_version` and provenance | N |
| 12 | `engine/paper/` paper trading and monitoring | Simulated fills on recorded or live observations; monitoring of open paper positions | R: journal schema ideas `dashboard/journal.py` (new tables, **separate DB**); exit-rule semantics `exit_monitor._exit_signal` |
| 13 | `engine/chain/` option chain | Full option-chain snapshot per underlying and expiry, from observations | R: `dashboard/option_chain.py` |
| 14 | `engine/events/` event gates | Blocks signals around scheduled events, results and expiry; F&O ban list (Q-NSE-4) | R: `dashboard/news_sweep.py` (filings), event-calendar pattern `dashboard/mcx_events.py` |
| 15 | `engine/replay/` backtest and replay | Feeds recorded observations through the same pure functions as live. Out-of-sample harness, net of cost. | R: `skills/backtest-expert/scripts/evaluate_backtest.py`; OOS split pattern of `dashboard/*_backtest.py`; day-clustered test `swing_journal.day_test` |
| 16 | `engine/analytics/` analytics | Scoreboards, calibration, sample gates | R: `swing_journal.day_test`, `rec_ledger.scoreboard` pattern |
| 17 | `engine/api/` API | FastAPI router mounted into the existing server, read-only GET endpoints | R: mounting pattern of `dashboard/api/mcx.py` into `dashboard/api_server.py` |
| 18 | dashboard | New React tab | R: `dashboard/web` (React + Vite + Tailwind), tab pattern `dashboard/web/src/tabs/*` |

---

## 3. Data flow

```
08:30  instruments dump ──► instrument_master snapshot (dated)
                                  │ universe (config: Q-OPS-1)
09:00–15:35  wss://ws.kite.trade (full) ──► recorder ──► raw packet archive (lossless, + received_ts)
                                                 │
                                                 ▼
                                   ingest.parse + validate ──► observation table (+ UNAVAILABLE reasons)
                                                 │
            ┌────────────────────────────────────┼─────────────────────────────┐
            ▼                                    ▼                             ▼
     candles.build (pure)              chain.snapshot (pure)          positioning.classify (pure)
            │                                    │                             │
            └──────► structure / timing / contracts / events (pure) ◄──────────┘
                                                 │
                                        signals.evaluate(snapshot, config, now)   (pure)
                                                 │
                       risk.size ──► paper.simulate / monitor ──► analytics ──► API ──► dashboard
replay: raw archive ──► same ingest + pure chain ──► same signals (identical code path)
```

Every derived object carries a `Provenance` (§5). The pure layer reads no clock, network or disk.
The edges (recorder, scheduler, API) inject `now` and data snapshots.

---

## 4. Storage

**Recommendation: reuse SQLite (already used by `journal.db`; stdlib `sqlite3` 3.50.4) in a NEW,
separate file `data/engine/engine.db` (WAL mode), plus a lossless daily raw-packet archive.**
PostgreSQL and Redis are not installed (checked 2026-11-05). Add them only if a measured
SQLite limit is hit; that would be its own decision (Q-OPS-4).

Why the raw archive is separate: `full` packets are 184 bytes (F-WS-3). Roughly 400 instruments
ticking about once a second over a 6¼-hour session would be ~9 M packets and ~1.6 GB a day uncompressed.
That is an *estimate*, because tick cadence is unmeasured (Q-WS-1). The disk has **21 GB free** (Q-OPS-2).
So the universe, retention and compression must be decided before Phase 1 runs (Q-OPS-1/2).
Raw packets are kept byte-exact for honest replay. The `observation` table can be rebuilt from them.

### Schema: raw observations

```sql
-- One row per parsed packet. Nothing forward-filled: a field the packet did not carry is NULL
-- and named in `unavailable` with a reason.
CREATE TABLE observation (
  id               INTEGER PRIMARY KEY,
  session_date     TEXT    NOT NULL,          -- IST trading date, YYYY-MM-DD
  source           TEXT    NOT NULL,          -- 'kite.ws.full' | 'kite.ws.quote' | 'kite.rest.quote' | 'kite.hist.<interval>'
  instrument_token INTEGER NOT NULL,
  exchange_ts      TEXT,                      -- ISO-8601 with +05:30 (F-WS-5 / F-QUOTE-4); NULL ⇒ unavailable
  received_ts      TEXT    NOT NULL,          -- when our process received it (+05:30)
  processed_ts     TEXT    NOT NULL,          -- when it was parsed (+05:30)
  last_price       REAL,
  last_qty         INTEGER,
  avg_price        REAL,                      -- day VWAP (F-QUOTE-6)
  volume_day       INTEGER,                   -- cumulative traded volume for the day
  pending_buy_qty  INTEGER,                   -- PENDING orders, not traded (F-QUOTE-5)
  pending_sell_qty INTEGER,                   -- PENDING orders, not traded
  open REAL, high REAL, low REAL, close REAL,
  last_trade_ts    TEXT,
  oi               INTEGER,
  oi_day_high      INTEGER,
  oi_day_low       INTEGER,
  depth_json       TEXT,                      -- 5 levels/side as received (F-WS-5); NOT a full book
  unavailable      TEXT,                      -- JSON {field: reason}
  raw_ref          TEXT,                      -- '<archive-file>:<offset>' for byte-exact replay
  config_version   TEXT    NOT NULL
);
CREATE INDEX obs_tok_ts ON observation(instrument_token, exchange_ts);
CREATE INDEX obs_day   ON observation(session_date);

CREATE TABLE instrument_master (            -- one dated snapshot per download (F-INST-3)
  master_date TEXT NOT NULL, instrument_token INTEGER NOT NULL, exchange_token INTEGER,
  tradingsymbol TEXT, name TEXT, expiry TEXT, strike REAL, tick_size REAL, lot_size INTEGER,
  instrument_type TEXT, segment TEXT, exchange TEXT, fetched_ts TEXT NOT NULL,
  PRIMARY KEY (master_date, instrument_token)
);

CREATE TABLE recorder_session (             -- the honesty log: what was and wasn't captured
  session_date TEXT, started_ts TEXT, ended_ts TEXT, universe_size INTEGER,
  connections INTEGER, reconnects INTEGER, gaps_json TEXT, config_version TEXT
);

CREATE TABLE config_version (
  version TEXT PRIMARY KEY, sha256 TEXT NOT NULL, created_ts TEXT NOT NULL, path TEXT NOT NULL
);
```

Later phases add their own tables (signals, paper fills, …) in the same file. They never go in `journal.db`.

---

## 5. Core interfaces (contracts for later phases)

Python 3.13, `dataclasses(frozen=True)`, `zoneinfo.ZoneInfo("Asia/Kolkata")`. Every datetime is
timezone-aware. Signatures only; nothing below is implemented in Phase 0.

```python
# engine/core/types.py
IST = ZoneInfo("Asia/Kolkata")

@dataclass(frozen=True)
class Unavailable:
    reason: str                          # e.g. "not in quote-mode packet", "index has no OI"

@dataclass(frozen=True)
class Provenance:
    source: str                          # 'kite.ws.full', 'derived:positioning.v1', …
    observed_at: datetime | None         # exchange timestamp; None ⇒ unavailable
    received_at: datetime
    processed_at: datetime
    def age(self, now: datetime) -> timedelta | None: ...

T = TypeVar("T")
Maybe = T | Unavailable                  # every market field is Maybe[...]

@dataclass(frozen=True)
class DepthLevel:
    price: Decimal; quantity: int; orders: int     # pending, 5 levels max (F-WS-5)

@dataclass(frozen=True)
class Observation:
    instrument_token: int
    last_price: Maybe[Decimal]; last_qty: Maybe[int]; avg_price: Maybe[Decimal]
    volume_day: Maybe[int]; pending_buy_qty: Maybe[int]; pending_sell_qty: Maybe[int]
    ohlc: Maybe[tuple[Decimal, Decimal, Decimal, Decimal]]
    last_trade_at: Maybe[datetime]; oi: Maybe[int]; oi_day_high: Maybe[int]; oi_day_low: Maybe[int]
    bids: Maybe[tuple[DepthLevel, ...]]; asks: Maybe[tuple[DepthLevel, ...]]
    prov: Provenance

@dataclass(frozen=True)
class Instrument:
    token: int; exchange_token: int; tradingsymbol: str; name: str
    expiry: date | None; strike: Decimal | None; tick_size: Decimal; lot_size: int
    instrument_type: str; segment: str; exchange: str; master_date: date

@dataclass(frozen=True)
class EngineConfig:
    version: str; sha256: str; values: Mapping[str, Any]   # loaded from config/engine/<version>.yaml
```

```python
# 1 broker (edge; does I/O) — read-only by construction
class BrokerAdapter(Protocol):
    def instruments(self, exchange: str | None = None) -> list[dict[str, str]]: ...
    def quote(self, keys: Sequence[str]) -> dict[str, dict]: ...          # ≤500 keys, ≤1 req/s
    def historical(self, token: int, interval: str, start: datetime, end: datetime,
                   *, oi: bool, continuous: bool) -> list[list]: ...      # ≤3 req/s, range caps F-HIST-5

# 2 instruments (pure)
def load_master(rows: Iterable[Mapping[str, str]], master_date: date) -> "InstrumentMaster": ...
class InstrumentMaster:
    def by_token(self, token: int) -> Instrument | None: ...
    def futures(self, name: str, as_of: date) -> list[Instrument]: ...    # live, sorted by expiry
    def options(self, name: str, expiry: date) -> list[Instrument]: ...
    def expiries(self, name: str, segment: str, as_of: date) -> list[date]: ...

# 3 recorder (edge)
class Recorder:
    def __init__(self, broker: BrokerAdapter, archive: "RawArchive", cfg: EngineConfig, clock: Callable[[], datetime]): ...
    def run(self, universe: Sequence[int], until: datetime) -> "RecorderSessionLog": ...

# 4 ingest (pure)
def parse_packet(raw: bytes, received_at: datetime, processed_at: datetime, segment_of: Callable[[int], str]) -> list[Observation]: ...
def detect_gaps(obs: Sequence[Observation], cfg: EngineConfig) -> list["Gap"]: ...

# 5 candles (pure)
@dataclass(frozen=True)
class Candle:
    token: int; start: datetime; interval: str
    open: Maybe[Decimal]; high: Maybe[Decimal]; low: Maybe[Decimal]; close: Maybe[Decimal]
    volume: Maybe[int]; oi_close: Maybe[int]; complete: bool; n_obs: int; prov: Provenance
def build_candles(obs: Sequence[Observation], interval: str, session: "SessionWindow") -> list[Candle]: ...
def candles_from_kite(rows: Sequence[list], token: int, interval: str, received_at: datetime) -> list[Candle]: ...

# 6 positioning (pure)
@dataclass(frozen=True)
class PositioningState:
    token: int; window: str; price_chg_pct: Maybe[float]; oi_chg_pct: Maybe[float]
    quadrant: Literal["PRICE_UP_OI_UP", "PRICE_DOWN_OI_UP", "PRICE_UP_OI_DOWN", "PRICE_DOWN_OI_DOWN"] | Unavailable
    roll_window: bool; config_version: str; prov: Provenance
def classify_positioning(prev: Candle, cur: Candle, cfg: EngineConfig, now: datetime) -> PositioningState: ...

# 7 structure (pure)
def swing_levels(candles: Sequence[Candle], cfg: EngineConfig) -> "StructureLevels": ...
def sweep_events(candles: Sequence[Candle], levels: "StructureLevels", cfg: EngineConfig) -> list["SweepEvent"]: ...

# 8 timing (pure)
def opportunity_age(history: Sequence[PositioningState], now: datetime) -> "OpportunityAge": ...
def room_left(day: Candle, adr_pct: Maybe[float], cfg: EngineConfig) -> Maybe[float]: ...

# 9 contracts (pure)
def select_contract(direction: Literal["LONG", "SHORT"], chain: "ChainSnapshot", master: InstrumentMaster,
                    cfg: EngineConfig, now: datetime) -> "ContractChoice | Unavailable": ...

# 10 risk (pure)
def size_position(choice: "ContractChoice", stop: Decimal, budget_inr: Decimal, charges: "ChargeSchedule",
                  cfg: EngineConfig) -> "SizedPlan | Unavailable": ...

# 11 signals (pure)
@dataclass(frozen=True)
class Signal:
    id: str; created_at: datetime; underlying: str; direction: Literal["LONG", "SHORT"]
    inputs: Mapping[str, Any]; reasons: tuple[str, ...]; plan: "SizedPlan | None"
    config_version: str; prov: Provenance
def evaluate_signals(snapshot: "MarketSnapshot", cfg: EngineConfig, now: datetime) -> list[Signal]: ...

# 12 paper (pure core + edge store)
def simulate_fill(signal: Signal, book: Observation, cfg: EngineConfig, now: datetime) -> "PaperFill | Unavailable": ...
def monitor(position: "PaperPosition", obs: Observation, cfg: EngineConfig, now: datetime) -> "PaperEvent | None": ...

# 13 chain (pure)
def chain_snapshot(underlying: str, expiry: date, obs: Mapping[int, Observation], master: InstrumentMaster,
                   spot: Maybe[Decimal], now: datetime) -> "ChainSnapshot": ...

# 14 events (pure)
def event_gate(underlying: str, now: datetime, calendar: "EventCalendar", cfg: EngineConfig) -> "GateResult": ...

# 15 replay (edge → pure)
def replay(archive: "RawArchive", day: date, cfg: EngineConfig) -> "ReplayResult": ...

# 16 analytics (pure)
def scoreboard(signals: Sequence[Signal], outcomes: Sequence["Outcome"], cfg: EngineConfig) -> "Scoreboard": ...

# 17 api — GET only, mounted like dashboard/api/mcx.py
router = APIRouter(prefix="/api/engine")
```

`MarketSnapshot`, `ChainSnapshot`, `ContractChoice`, `SizedPlan`, `PaperFill` and the other quoted names
are defined in the phase that builds them. Their shape is reviewed at that phase, but the
function signatures above are the contract.

---

## 6. Process model

| Process | Schedule | Notes |
|---|---|---|
| Token refresh | existing `com.clade.kite-refresh` (08:00) | Reused as-is. Failure mode seen 2026-11-05: Mac asleep → no token (Q-OPS-3) |
| Instrument master | new launchd job, 08:30 IST (F-INST-3) | Writes a dated snapshot; recorder refuses to start without today's master |
| Recorder | new launchd job, 09:00–15:35 IST, one long-running process | ≤3 WebSocket connections × ≤3000 tokens (F-WS-2); writes the raw archive + `recorder_session` |
| Ingest / derive | inside the recorder process or a follower, batched | Pure functions; no network |
| API | router inside the existing `com.clade.dashboard-server` | Read-only, `127.0.0.1` only, token never returned |
| EOD analytics / replay | new launchd job after close | Deterministic; same code as live |

Operating risk: the recorder needs the Mac awake and on AC for whole sessions. The existing
`com.clade.market-awake` (`caffeinate -s`) only holds on AC. Phases 1–3 cannot be validated otherwise.

---

## 7. Configuration and time

- `config/engine/<version>.yaml`. The version string and SHA-256 are recorded in `config_version`, and the version is stamped on every observation and signal.
- Values from open questions have **no default**. Loading fails if one is unset.
- Time: `IST = ZoneInfo("Asia/Kolkata")`. Pure functions take `now`. Only edge processes call the clock.

---

## 8. Phase 1 as built (2026-11-05) — deviations from §4/§5, for owner review

The Phase 1 text (per-date partitioning, raw fields, EOD Parquet, a replaceable SubscriptionProvider)
supersedes parts of the Phase 0 plan. These deviations are **flagged, not silently adopted**:

| Phase 0 plan | Built in Phase 1 | Why |
|---|---|---|
| one `data/engine/engine.db` with an `observation` table (REAL prices, parsed fields) | one directory per IST trading date: `buffer.sqlite` (WAL, INSERT-only: `ticks`, `depth`, `oi_changes`, `events`, `gaps`, `meta`) + `frames.bin` (raw frames + receive_ns) + `instruments.csv.gz` + `status.json` | Phase 1: "append-only, partitioned by trading date"; raw payload fields kept as exchange integers. The `observation` table (parsed `Maybe` fields) is Phase 2 ingest |
| `Recorder(broker, archive, cfg, clock).run(universe, until)` | `Recorder(cfg, store, consumers, clock_ns, disk_free, alert, symbols)` + `engine.recorder.main`; the universe comes from `SubscriptionProvider.subscriptions() -> {token: mode}` | Phase 1 step 2 (provider) and step 3 (queue, gaps, disk guard). The clock is still injected |
| `replay(archive, day, cfg) -> ReplayResult` | `day_events(day_dir, source)` / `load_events(root, start, end)` + `replay(events, consumers, speed, clock, store)`; `ReplayClock`, `AsOfStore.get_latest(token, field, as_of)` | Phase 1 step 4 |

Data contract:
- `receive_ns` int64 ns since the epoch (UTC). `exchange_ts`/`last_trade_ts` are epoch seconds as sent; in Parquet they are int64 ns (`*_ns`).
- Prices are the exchange integers (paise for NSE/NFO, F-WS-9). `seq` is per connection, per packet, assigned at receive. Ordering key: `(exchange_ts, receive_ns, conn, seq, kind)`.
- Change-only (step 9): a tick row is skipped when every field except `last_trade_ts`/`exchange_ts` equals the token's last written row. Depth is written on change, at most once per `depth_min_interval_s`. The frames log keeps everything (Q-STORE-2).
- OI log: one row per change in OI by token (`prev_oi` NULL = the day's first observation, a baseline).
- Gaps (`gaps` table): `disconnect` (close/error → next connect, or session end), `queue_drop` (count of packets), `disk_depth`/`disk_ticks` (count of skipped items). Connection events are kept in an unbounded side deque, so they are never dropped.
- EOD `engine.compact`: Parquet zstd `<date>/parquet/<table>/family=<master segment>/` (format A) + `frames.bin.zst` (format B). The buffer is deleted only after replay(parquet) is byte-identical to replay(buffer). **Format decision: pending the first full session (Q-STORE-1).**
- `engine.retention`: archives raw files (`frames.bin.zst`, `parquet/ticks`, `parquet/depth`) of sessions older than N, verifies sha256 at the target, records it in `archived.json`, and only then deletes. Derived data is never deleted.

## 9. Phase 2 as built (2026-11-05)

| Piece | Where |
|---|---|
| NSE fetch + parsers (constituents, ban list) | `engine/sources.py` |
| Registry, universe, restrictions, API, refresh CLI | `engine/universe.py` → `<root>/universe.sqlite` (WAL); raw NSE files in `<root>/<date>/reference/`; master stays `<root>/<date>/instruments.csv.gz` |
| Provider | `engine/provider.UniverseSubscriptionProvider` (recorder uses it; `ConfigSubscriptionProvider` kept, unused) |
| Config | `config/engine/v2.yaml` (default). v1.yaml is kept unchanged as the record of Phase 1 runs; it no longer passes the v2 required-key list |
| Job | `scripts/launchd/com.clade.engine-universe.plist`, weekdays 08:35; the recorder also calls `refresh()` (idempotent) at start |

Registry tables: `master_dates`, `contracts` (one row per `(token, first_seen_date)`, attributes as the master's
strings, `last_seen_date` extended while unchanged), `master_diff` (added / removed / `<field>_change` / rollover),
`fetches` (every attempt, ok or not, with URL and IST time), `constituents`, `ban_dates` + `bans`.

API on `Registry(cfg)`: `get_universe(d)`, `get_contracts(underlying, d)`, `get_contract(token, d)`,
`is_tradable(token, d) -> (bool, reasons)`, plus pure `strike_intervals(contracts, expiry)`. The names are as the
phase text gave them, as methods instead of module functions, because they need the DB handle.
A date with no applied master answers nothing (`NO_MASTER` / `None`), never a guess.

`is_tradable` reasons: `NO_MASTER`, `NOT_IN_MASTER`, `EXPIRED`, `NOT_IN_UNIVERSE`, `BLOCKED_NO_CONSTITUENTS`,
`BLOCKED_STALE_CONSTITUENTS`, `HOLIDAY`, `BANNED` (NFO contracts only), `RESTRICTION_UNVERIFIED:<source> (detail)`.
Only `STALE_CONSTITUENTS` is a warning that leaves the answer True.
Constituent flags (`STALE_*`, `BLOCKED_*_CONSTITUENTS`) apply to STOCK contracts only; INDEX contracts ignore them (owner, Q-UNI-2).

## 10. Phase 3 as built (2026-11-05/06): live data engine

| Piece | Where |
|---|---|
| Tier allocator (pure `allocate`, `assign`), `TierBook.promote/demote` (TTL), tier A from the registry | `engine/tiers.py` |
| Executor on live connections + stall watchdog | `engine/recorder.py` (`TierExecutor`, `Recorder.check_stall`) |
| Aggregation (1/3/5/15-min + day candles, OI at close, combined OI, Tier B depth, DataQuality, late ticks) | `engine/candles.py` (`Aggregator`, `aggregate`) |
| Live store + pipeline + EOD snapshot archive | `engine/snapshots.py` → `<date>/snapshots.sqlite`, EOD `<date>/parquet/snapshots/` |
| Backfill + baselines | `engine/backfill.py` → `<root>/history.sqlite` (`source='HISTORICAL_API'`), `engine/baselines.py` |
| Feed report | `engine/feed_report.py` → EOD `<date>/feed_report.json` |
| Config | `config/engine/v3.yaml` (default): `tiers`, `sessions`, `candles`, `quality`, `baselines`, `historical`, `ws.stall_after_s` |

Deviations from earlier interfaces, all flagged for review:

| Earlier | Now | Why |
|---|---|---|
| Phase 0 `build_candles(obs: Sequence[Observation], interval, session)` and its `Candle` shape | `Aggregator.on_event(Event)` / `advance(now)`, plus `aggregate(events, cfg, day)` for replay. `Candle` carries the Phase 3 fields (completeness, trades, ticks, VWAP, first/last tick, OI at close + change time + age, `DataQuality`) | Phase 3: "fed only by the event stream, identical in live and replay". `Observation` was never built (Phase 1 used `Event`) |
| `Event.kind` ∈ {tick, depth} | + `conn` (an `events` row) and `gap` (a `gaps` row). Live consumers get them as they are written; `day_events(..., control=True)` loads them | owner-approved 2026-11-05 |
| replay order only `sort_key` (exchange ts first) | + `store.arrival_key` (receive_ns, conn, conn<gap<tick<depth, seq) = the recorder's real delivery order; aggregators use it | live == replay |
| recorder subscribes via `UniverseSubscriptionProvider`, once on connect | `TierExecutor.step()` every `tiers.executor_interval_s`: plan → `tier_plan` / `tier_drop` / `tier_ops` events → subscribe/unsubscribe/set_mode on the reactor thread, only on connected slots | Phase 3 tiers; promotions at runtime |
| no liveness check | `ws.stall_after_s`: no frame (heartbeats count) on a `connected` socket ⇒ `stall` event + gap, phone alert, `dropConnection(abort=True)` → library reconnect | owner decision 2026-11-06 after F-WS-15 |

Determinism rules (why live == replay):
1. A tick is accepted iff `receive_ns < minute end + candles.out_of_order_window_s`. That is a property of the tick alone.
2. A minute is final at `end + candles.finalize_delay_s`. That delay exceeds watchdog + executor + writer intervals, so a stall gap is always delivered before the minutes it covers are final. Queue-drop gaps are flushed more often than the window.
3. Only tick/depth events move the stream clock. An idle recorder moves it to `wall − candles.idle_clock_margin_s`, never backwards and never past a delivered frame.
4. Every output is stamped with a deterministic time (minute end + delay; due time of a status change; the tick's own receive time).
5. Candle quality is measured as of the candle's close (`end_ns`); `processing_ts` is the finalization time.

The EOD archive of snapshots is a **full replay** of the day, not a copy of the live store. Every live row that
differs is counted in `snapshots_diff.json`, so live == replay is checked on real data every day.

## 11. Phase 4 as built (2026-11-06): futures positioning hypotheses

| Piece | Where |
|---|---|
| Features, classification, noise filters, events (pure) | `engine/positioning.py`: `evaluate_day`, `classify`, `track_events` |
| History profile (percentile distributions, beta seed, volume baseline, ATR seed, previous close) | `engine/positioning.profile` over history.sqlite minute rows (HISTORICAL_API) |
| Combined-OI cadence | `engine/oi_cadence.py`: + `COMBINED:<underlying>` rows (union of the futures' OI change times) |
| Event store | `<date>/positioning.sqlite`, table `positioning_events` (INSERT OR IGNORE on event_id + state + config version; no UPDATE/DELETE) |
| Config | `config/engine/v5.yaml` = v4 + `positioning` (loaded by `engine.positioning`; the global default is still v4, Q-CFG-2) |
| CLI | `python3 -m engine.positioning DATE... [--report PATH] [--dry-run]` |

Deviations from earlier interfaces, all owner-approved on 2026-11-06 or flagged:

| Earlier | Now | Why |
|---|---|---|
| Phase 0 `PositioningState(token, window, price_chg_pct, oi_chg_pct, quadrant=PRICE_UP_OI_UP…, roll_window)` and `classify_positioning(prev, cur, cfg, now)` | `PositioningState(underlying, ts_ns, near…, primary/raw/near_month: View, flags, features)`; `evaluate_day(data, master, history, cadence, cfg, day)`; values `LONG_BUILDUP / SHORT_BUILDUP / SHORT_COVERING / LONG_UNWINDING / NEUTRAL_OR_MIXED` | Phase 4 text; the owner chose its names over the Phase 0 labels. Field names say `positioning_hypothesis`; `DISCLAIMER` states what the labels are not |
| Phase 4 text "inputs: Phase 3 snapshots only" | today's snapshots + the Phase 3 history store (`HISTORICAL_API`) for distributions, beta seed, RVOL baseline, ATR seed and previous close; the source is named in every feature's `DataQuality.source` | owner decision (1 recorded session exists) |
| `docs/measured-oi-cadence.md` had per-token rows only | + `COMBINED:<underlying>` rows, token column `combined` | owner decision: gating combined OI on its slowest component disabled most windows |
| Phase 3 `baselines.oi_change_windows_min: [5, 15, 60]` | Phase 4 computes its own distributions for 1/5/15/30 min with `engine.baselines.oi_change_distribution` (not the stored baselines) | the phase needs 30 min and 1 min (jump check) and combined OI |

Rules (pure, config-versioned):
1. Evaluation at every 1-minute combined-OI close of an underlying. Price contract = near-month future (earliest expiry ≥ day).
2. A feature is UNAVAILABLE if any input is not OK: candle `quality.status == OK` and, for prices, `COMPLETE`; combined OI `status == OK`.
   The Unavailable reason starts with its code (OI_STALE, LOW_SAMPLE, OI_WINDOW_DISABLED, INSUFFICIENT_DATA…).
3. Quadrant per OI window w (5/15/30): price change over w and OI change over w, each significant only when its
   percentile against the contract's own last-20-session distribution is ≥ 0.80 / ≤ 0.20 **and** it is beyond the floor.
   One quadrant across the significant windows ⇒ that hypothesis; two different ones ⇒ CONFLICTING_WINDOWS.
4. Filters: EXPIRY_DAY and ILLIQUID_FUTURE suppress every view; ROLLOVER_WINDOW suppresses the near-month view and
   is a flag on the combined views; INDEX_DRIVEN replaces NOT_SIGNIFICANT on the primary view when the raw view has a quadrant
   and the residual price is not significant in those windows; OI_JUMP_INVALID removes a window with an implausible 1-minute step.
5. Events: CONFIRMED after 3 consecutive identical non-neutral primary hypotheses; INVALIDATED (a new row) on the opposite
   price direction or on a close back through first_observed ± 0.5 ATR (level fixed at confirmation).

## 12. Phase 5 as built (2026-11-06): price action, structure, liquidity and VWAP

| Piece | Where |
|---|---|
| Detectors (pure, one streaming `Detector` per timeframe), history levels, opening range, `detect`, `evaluate_day` | `engine/structure.py` |
| LevelMap (nearest obstacle above / below at any `as_of`) | `engine.structure.level_map`, `levels_at` |
| Store | `<date>/structure.sqlite`, table `structure_detections` (INSERT OR IGNORE on id + config version; no UPDATE/DELETE) |
| Config | `config/engine/v6.yaml` = v5 + `structure` (loaded by `engine.structure`; the global default is still v4, Q-CFG-2) |
| CLI | `python3 -m engine.structure DATE... [--report PATH] [--dry-run]` |

Deviations from earlier interfaces (owner-approved 2026-11-06):

| Earlier | Now | Why |
|---|---|---|
| Phase 0 `swing_levels(candles, cfg) -> StructureLevels`, `sweep_events(candles, levels, cfg) -> list[SweepEvent]` | `detect(underlying, token, candles_by_interval, history_rows, cfg, day) -> list[Detection]` (append-only objects: id, type, level, created_ts, confirmed_ts, source candles, attrs, label, config_version) and `level_map(underlying, token, detections, candles_1m, as_of) -> LevelMap` | Phase 5 text: every detector returns objects with confirmed_ts; LevelMap per underlying at any as_of. Owner chose "replace", no wrappers |
| build-plan: "reuses structure_exit.py / liquidity_sweep.py semantics by import" | not imported; the Phase 5 text defines the rules | build-plan was a proposal; the phase text supersedes it |

Rules (pure, config-versioned):
1. Instrument = the near-month future (earliest expiry >= day), as in Phase 4 (owner decision). Timeframes 3/5/15 min from Phase 3 candles.
2. A bar is usable iff COMPLETE and quality OK. A missing/PARTIAL/EMPTY/non-OK bar breaks every window: pivot windows,
   consolidation, pending breakout attempts, pending sweeps (level dropped) and zone reactions. Nothing is bridged.
3. Each detection is stamped confirmed_ts = close of the bar at which it became knowable, and never changes. Hence
   detections(prefix up to t) == detections(full day) with confirmed_ts <= t; tested on fixtures and on real 2026-11-06 data.
4. ATR per timeframe = mean true range of the last 14 contiguous pairs, seeded from history minutes rolled up to the same
   buckets (the last bucket cut at 15:40). RVOL = bar volume / median volume of the same slot over the last 20 history sessions.
5. LevelMap obstacles: PDH/PDL/PDC/PWH/PWL/ORH/ORL, swing highs/lows (all timeframes, swept or not), equal-highs/lows
   clusters, consolidation box edges, zone edges (until invalidated), the latest VWAP per timeframe. Above = nearest level >= price,
   below = nearest level < price; price = last usable 1m close at or before as_of; distance in each timeframe's ATR.

## 13. Phase 6 as built (2026-11-06): opportunity age, timing and exhaustion

| Piece | Where |
|---|---|
| Setups from Phase 5 detections and Phase 4 events, `opportunity_age`, `exhaustion`, `retest_plan`, `track` (pure) | `engine/opportunity.py` |
| Timing recorder (MFE/MAE per anchor × horizon, time to target / invalidation), pure in `as_of` | `engine.opportunity.timing_rows`, `anchors` |
| Per-underlying snapshots from Phase 5 detections + 1m candles + Phase 4 states | `engine.opportunity.Context` (reuses `structure.level_map`, Phase 5 VWAP/ATR) |
| Store | `<date>/opportunity.sqlite`: `setups`, `evaluations`, `timing` (INSERT OR IGNORE on natural key + config version) |
| Config | `config/engine/v8.yaml` (default of `engine.opportunity`) = v7 + `opportunity.exhaustion.vwap_atr_timeframe_min: 15` (owner, Q-OPP-1). `v7.yaml` = v6 + `opportunity`, kept unchanged as the record of the first 2026-11-06 run; it no longer passes the v8 required-key list. Global default still v4 (Q-CFG-2) |
| CLI | `python3 -m engine.opportunity DATE... [--report PATH] [--dry-run]`; recomputes Phase 5 and Phase 4 for the date (pure, ~2 min) |

No earlier interface changed. Phase 4 `run_day`, Phase 5 `detect` / `level_map` / `near_candles` are used as they are.

Rules (owner decisions 2026-11-06):
1. Setups = Phase 5 accepted breakouts/breakdowns, sweeps, defended zones, and Phase 4 CONFIRMED events. Direction, first detection,
   confirmation and the structural stop are fixed when the setup is built ("far side" stop: opposite box edge, wick extreme,
   zone far edge, Phase 4 PRICE_THROUGH_FIRST_OBSERVED level). A setup built from a prefix of the day equals the full-day one.
2. Evaluated at every 1m close from confirmation to 15:40 or its end: INVALIDATED (1m close at or through the stop, or the Phase 4
   INVALIDATED row) or RETEST_EXPIRED. Price = last usable 1m close; ATR / VWAP = the Phase 5 values of the setup's timeframe (positioning: 5m).
   Exception (Q-OPP-1, v8): the VWAP_EXTENSION flag measures (price − VWAP) in the 15m ATR.
6. EOD (Q-OPP-6): `engine.eod` runs `engine.opportunity.eod` after the OI cadence doc and before retention. It handles every recorded day
   without a `runs` row for the current opportunity config (catch-up); per-day errors are recorded and fail the job's exit code.
3. Classification precedence: UNKNOWN > EXHAUSTED > TIMELY / VALID_BUT_LATE. No LevelMap or no obstacle in the trade direction ⇒ UNKNOWN.
4. VALID_BUT_LATE without an active plan creates one retest plan (the nearer valid level among the broken level and VWAP; zone width
   in ATR; R:R at the zone's worse edge; expiry). A close inside the zone with every rule passing ⇒ TIMELY, reason RETEST.
5. Timing rows exist only once knowable at `as_of`: MFE/MAE after anchor + horizon (every 1m bar in the horizon usable, else UNAVAILABLE);
   time to target (obstacle at confirmation, fixed) / invalidation when hit, or NOT_REACHED_BY_CLOSE at the close. Anchors: first detection,
   confirmation, first TIMELY evaluation (owner decision).

## 14. Phase 7 as built (2026-11-06): contract selector V1 and centralized risk engine

| Piece | Where |
|---|---|
| Cost model (versioned Zerodha NSE F&O charges, round trip, UNVERIFIED flag) and slippage (walk the 5-level book; ESTIMATED without depth) | `engine/costs.py` (pure) |
| Selector V1: `TradeSetup`, `Quote`, `Candidate`, `Selection`, `premium_model` (empirical delta), `limit_reasons`, `select_contracts` | `engine/contracts.py` (pure) |
| Risk engine: `PortfolioState`, `risk_check` → `RiskDecision`, `ApprovalToken` (only risk_check mints), `Recommendation` (needs the token) | `engine/risk.py` (pure) |
| Report on recorded setups (edge: read-only buffer / registry / Phase 6 store) | `engine/contract_report.py`, `python3 -m engine.contract_report DATE [--n 10] [--report P] [--json P]` |
| Config | `config/engine/v9.yaml` = v8 + `costs`, `contracts`, `risk` (default of the three modules; global default still v4, Q-CFG-2) |

Interfaces: the Phase 0 plan's `select_contract` / `size_position` were never built; the Phase 7 text's shapes replace them (Q-CON-3). No built interface changed.

Rules:
1. Candidates: near-month future (next month inside `positioning.rollover_days`); long CE (bullish) or long PE (bearish), ATM (nearest to spot, a tie goes ITM) and one strike ITM, on the nearest expiry with DTE ≥ `contracts.min_dte_days` and the next one. Strikes and expiries come only from the registry. No short option can be built (`Candidate.__post_init__` raises).
2. Entry = the walked fill on the executable side (ask side for a buy). Exit slippage at stop / T1 = the same book's other side (ESTIMATED). Costs = round trip at the stop and at T1, on the setup's trade date.
3. Contract levels: futures = mid + (level − entry), with a constant basis assumed for another month. Options = mid + empirical delta × (level − entry), labelled APPROXIMATE; no fit ⇒ NO_TRADE NO_PREMIUM_MODEL.
4. Size = the most lots whose planned risk (net of costs and exit slippage) is ≤ `risk.max_risk_per_trade_inr`. Capital = premium (options), margin quote (MARGIN_API), or `fraction × notional` (MARGIN_ESTIMATED).
5. `limit_reasons` (spread, spread vs move, volume / OI / visible depth, capital) is one function, used for selector exclusion and risk rejection. `risk_check` runs every check and names each failure; any failure ⇒ REJECTED, no token.
6. Ranking: net R:R × liquidity score (visible depth vs `liquidity_depth_target` × qty, times spread headroom), ties by lower capital. Premium level is not a factor.

## 15. Phase 8 as built (2026-11-06): signal engine, gates, evidence scoring, lifecycle

| Piece | Where |
|---|---|
| Families A–F (`match`), G (`exhaustion_observation`), `accumulation`, `market_context`, `score`, `gates`, `recommend`, lifecycle (`start`, `advance`, `drive`), `promotions` / `promote` (pure) | `engine/signals.py` |
| Edge: recompute Phases 4–6 for a date, recorded quotes (`QuoteBook`, one scan per underlying), store, `replay_check`, report, CLI | `engine/signal_report.py`, `python3 -m engine.signal_report DATE... [--report P] [--dry-run]` |
| Store | `<date>/signals.sqlite`: `recommendations` (JSON payload + zlib/pickle `SignalInputs`), `lifecycle` (one row per transition), `observations`, `runs` (INSERT OR IGNORE; no UPDATE/DELETE) |
| Config | `config/engine/v10.yaml` = v9 + `signals` (default of engine.signals; global default still v4, Q-CFG-2) |

No earlier interface changed. `engine.contract_report` gained `quote_from_rows` (its `quotes_at` now calls it; same output).
Phase 6 `Setup` / `Evaluation`, Phase 7 `select_contracts` / `risk_check` / `Recommendation`, and Phase 3 `TierBook.promote` are used as they are.

Rules (owner-accepted assumptions Q-8-2..9; build-time assumptions Q-8-10..17 in docs/questions-ledger.md):
1. One lifecycle per Phase 6 setup whose source can carry a family (BREAKOUT/BREAKDOWN_ACCEPTED, SWEEP_LOW/HIGH): DETECTED at first
   detection, WATCHING at confirmation, CONFIRMED at the first evaluation where a family matches, then the gates decide ENTRY_ELIGIBLE /
   WAIT_FOR_RETEST / REJECTED (terminal). The driver never enters TRIGGERED / ACTIVE / WEAKENING / EXIT_REQUIRED (paper fills, Phase 11).
2. Gates run on the Phase 7 candidate that risk_check approved first in ranking order (else the top-ranked one). Scores are stored for
   every recommendation, REJECTED included. ENTRY_ELIGIBLE also carries the Phase 7 token-backed `Recommendation`.
3. Scores are raw points out of 100 with the available maximum reported; options are always UNAVAILABLE (max 80), and so is the volume profile.
4. Every recommendation's inputs are stored; `replay_check` regenerates each one and compares the JSON byte for byte.

## 16. Phase 9 as built (2026-11-07): paper trading, actual-trade tracking, live monitoring and exits

| Piece | Where |
|---|---|
| Paper broker `paper_fill`, `Monitor` (streaming, pure), `run_trades` driver, `risk_both`, `Trade` / `Decision` / `Alert` / `Feedback` / `ReviewInputs`, `AlertSink` + `deliver` | `engine/paper.py` (pure) |
| Ledgers (SIMULATED `sim_*`, ACTUAL `actual_*`, shared `monitor_decisions` / `alerts` / `lifecycle` / `feedback` with a ledger column), `InAppSink`, `portfolio_state`, actual-trade journal (`record_taken` / `record_skipped` / `record_exit`), `record_feedback`, replay over recorded sessions (`run_day`, `day_events`), CLI | `engine/ledger.py` (edge) → `<storage.root>/ledger.sqlite` |
| Config | `config/engine/v11.yaml` = v10 + `monitor` + `paper` (default of engine.paper; global default still v4, Q-CFG-2) |
| CLI | `python3 -m engine.ledger run|take|skip|exit|feedback|show` |

No earlier interface changed. Phase 7 `quote_problem`, `costs.fill` / `round_trip`, `risk_check`, Phase 8 `recommend`, `ALLOWED`,
`signal_report.QuoteBook` / `read`, `contract_report.quote_from_rows` and `store` event builders are used as they are.

Rules (owner Q-9-2 … Q-9-4; assumptions Q-9-5 … Q-9-25 in questions-ledger.md):
1. A SIMULATED trade opens only for a stored ENTRY_ELIGIBLE recommendation, only if `risk_check` approves on the SIMULATED and on the ACTUAL
   PortfolioState separately, and only if the recorded book at the decision time fills it (whole lots the visible book holds; no quote ⇒ no fill).
   Every fill stores the quote snapshot used.
2. Monitor: tick rules (hard stop, futures contract stop, T1) act on the tick that triggers them; cutoff 15:10, staleness, gaps / disconnects,
   per-trade max loss on estimated net P&L and the ledger's daily loss act on every event and on exact-time timers; the thesis review runs every
   `monitor.review_interval_s` and on each fresh OI change. Warnings never exit. EXIT_REQUIRED is terminal.
3. Every decision carries its triggering observations (value, exchange and receive time), rule id, stop, gross and estimated net P&L (UNAVAILABLE
   when the data is) and the config version. Alerts = decision changes (and every TIGHTEN / PARTIAL / EXIT), stored in-app.
4. The two ledgers are never summed: separate tables, per-ledger reads that validate the ledger name, per-ledger daily loss and portfolio state.

## 17. Phase 10 as built (2026-11-07): React dashboard (read-only over backend state)

| Piece | Where |
|---|---|
| Read model: Phase 4 states (primary/raw) and market context at every `dashboard.scrub_step_min` mark, near-month 1m candles as published | `engine/dashboard_export.py` (edge CLI) → `<date>/dashboard.sqlite` |
| Envelopes (provenance, age, OK/STALE/UNAVAILABLE, look-ahead guard), radar rows, positioning cells, timeliness map, per-ledger performance, health summary (pure) | `engine/dashboard.py` |
| Router `/api/engine/*` (loopback + same-origin, Q-10-3): GET sessions / overview / radar / positioning / signal / trades / performance / health / health/stream (SSE); POST journal take / skip / exit, feedback | `engine/api.py`, mounted in `dashboard/api_server.py` (one `include_router`, same try/except as MCX) |
| Config | `config/engine/v12.yaml` = v11 + `dashboard` |
| Frontend module (own design system, lazy chunk) | `dashboard/web/fo-engine/` — see [design-system.md](design-system.md) |

No earlier interface changed. Phase 3–9 functions are called as they are (`structure.load_day / near_candles / evaluate_day`,
`positioning.run_day`, `signals.market_context`, `signal_report.read`, `ledger.*`, `costs.round_trip`).

Follow-up (owner request 2026-11-07, Q-10-22): `engine.eod` runs `dashboard_chain` (Phase 8 signal_report → Phase 9 ledger run →
dashboard_export, one subprocess each, catch-up per day, skipped when done for the step's config version) **before** compaction,
because signal_report and the paper run read `buffer.sqlite`. `engine.eod.run(..., before_compaction=None)` keeps library callers and
tests unchanged; the CLI passes the chain. Config v13 = v12 + `dashboard.eod_step_timeout_s` (default of engine.dashboard_export / api).

## 18. Phase 11 as built (2026-11-07): option chain, IV/Greeks, event gates, selector V2 (owner-approved D-52; all additive)

- New pure module `engine/options.py`: `trading_years`, `risk_free`, `black76`, `implied_vol`, `greeks`, `analyze(contract, quote, future_quote, has_future, as_of, cfg) -> ContractAnalytics`, `hypothesis`, `chain_snapshot(...) -> ChainSnapshot`, `atm_iv`, `iv_percentile`, `options_factor`, `OptionContext`, `quote_from_rest`, `plan_tier_c(...) -> (list[tiers.Request], dropped)`.
- New `engine/events.py`: pure `parse`, `window_end`, `gate`; edge `fetch` (NSE event calendar, F-EVT-1) and `status_at` (latest fetch at or before as_of).
- New edge `engine/chain_report.py` (CLI + `<date>/options.sqlite`) and `TierCPlanner` / `previous_session` in `engine/recorder.py` (live tier C, D-51).
- `tiers.allocate(..., *, caps=None)`: per-tier cap (`tiers.<T>.max_tokens`); configs without the key behave as before.
- `contracts.select_contracts(..., *, chain=None, events=None)`; `Candidate` gains `role, iv, greeks, iv_percentile, premium_method, theta_cost_inr, expiry_sensitivity` (defaults None).
- `signals.SignalInputs` gains `options=None, events=None`; `signals.score(..., options=None)`. `opportunity.Evaluation.option_premium_change / option_iv_change` are typed `float | Unavailable` and filled in Phase 8.
- `KiteSession.quote(keys, batch, rate_per_s)`: read-only GET `/quote`, paced at F-RATE-1.

## 19. Phase 12 as built (2026-11-07): event-driven backtesting, timing studies, walk-forward (owner D-54..D-57)

- New pure module `engine/backtest.py`: `session_quality`, `stage`, `split`, `holdout_read_allowed`, `walk` (price path with gap-through
  stops), `r_multiple`, `excursions`, `segment`, `outcome`, `age_entries`, `class_entries`, `metrics` / `bootstrap` (day-clustered),
  `verdict`, `half_life`, `tod_bucket`, `regime`, `expiry_label`, `windows` / `month_windows` / `walk_forward`, `oi_views`
  (LOOK_AHEAD_DIAGNOSTIC), `historical_day` (Phase 5 `Detector` + Phase 6 `setups_from_structure` / `track`, unchanged, on lab index bars).
- New edge `engine/backtest_report.py` (CLI): RECORDED sessions through the unchanged Phase 9 `ledger.run_day` into a per-run backtest
  ledger (never `ledger.sqlite`), Parquet → buffer rebuild with the Phase 1 replay readers for compacted days, holdout read log,
  HISTORICAL_CANDLES runner, results `<storage.root>/backtest/<run>/results.json` + `report.md`, half-life file `config/engine/half_life/v<N>.json`.
- Phase 6 change (additive, D-56): `Evaluation.age_vs_half_life: float | Unavailable`; `opportunity_age(..., *, half_life=None)`,
  `track(..., *, half_life=None)`; `half_lives(cfg)`; `run_setups` passes each setup type's value. Rule AGE_VS_HALF_LIFE fails TIMELY when age
  since confirmation > `opportunity.half_life_multiple` × half-life. Only RECORDED + MEASURED + stage TENTATIVE/FINAL entries enable it;
  configs before v16 have no file key (rule disabled, outputs unchanged).
- Config v16 = v15 + `opportunity.half_life_file` / `half_life_multiple` + `backtest.*` (holdout rule fixed before any recorded data was read).

## 20. Phase 13 as built (2026-11-07): volume profile and order-book behaviour (owner D-58..D-60)

- New pure module `engine/profile.py`: `bin_size`, `levels` (POC / VAH / VAL / HVN / LVN), `profile_at(...) -> Profile | Unavailable`,
  `profile_detections` (profile snapshots every `profile.snapshot_interval_min` + HVZ_REJECTION per 1m bar), `depth_behaviour` /
  `depth_detections` (Tier B DepthSnapshots only), Phase 8 parts `profile_part` / `depth_part`; edge `load_ticks` (buffer.sqlite, else
  Parquet) and `add_profile(dets, near, master, rows, day_dir, cfg, day)` (identity for configs without `profile`).
- TICK_BASED = Phase 3 cumulative-volume deltas attributed at the packet's last price, used only in minutes that reconcile with their
  COMPLETE+OK 1m candle (2026-11-06: 22,328 / 22,328 near-future minutes reconcile). No ticks => candle-based APPROXIMATE (label in the
  detection label, `attrs.method`, `attrs.note` and the score-part detail). Coverage < `profile.min_coverage` => PROFILE_UNAVAILABLE.
- Phase 5 change (additive, D-59): `structure.PROFILE_LEVELS`; `levels_at` adds the levels of the latest profile snapshot only (none when it is
  PROFILE_UNAVAILABLE). No signature change; with no profile detections (configs before v17) the output is unchanged.
- Phase 6 change: `exhaustion` raises HIGH_VOLUME_ZONE_REJECTION (a HVZ_REJECTION against the trade within
  `profile.rejection.flag_window_min`) under configs with `profile`; earlier configs keep the old "skipped" note. `run_date` calls `add_profile`.
- Phase 8 change: `_factor(..., shares=None)`; under `signals.part_shares.profile_depth` (v17) the factor has parts volume_profile /
  depth_behaviour (weight 0) / visible_depth (5 points), so scores equal v16's. `signal_report.run_date` calls `add_profile`.
- Phase 12 change: `backtest.factor_study`; `backtest_report.recorded_events` adds per-anchor part values under v17; results gain
  `profile_depth_study` (recorded and PIPELINE_CHECK); HISTORICAL_CANDLES lists the profile as not representable (F-WS-7).
- Config v17 = v16 + `profile.*`, `depth.*`, `signals.part_shares`. Not the live / EOD default (Q-13-9): no v17 rows are written.
