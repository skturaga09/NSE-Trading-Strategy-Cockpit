# F&O engine runbook

Advisory and paper-trading only. Nothing in this system places, changes or cancels an order. Every "trade" you see in the
F&O Engine tab is SIMULATED (arithmetic on a recorded quote) unless you entered it yourself as ACTUAL in the Journal.

## 1. What runs, and when (weekdays, IST)

| time | launchd job | what it does | log (`dashboard/logs/`) |
|---|---|---|---|
| 08:00 | `com.clade.kite-refresh` | refreshes the Kite access token (expires 06:00 daily, F-AUTH-6) | `kite_refresh.log` |
| 08:35 | `com.clade.engine-universe` | instrument master, NIFTY 50/100 constituents, F&O ban list, holiday check, then the NSE event calendar (options are rejected without a calendar fetched that day) | `engine_universe.*.log` |
| 09:00–15:45 | `com.clade.engine-recorder` | records futures, spot, index and up to 400 option tokens over the WebSocket | `engine_recorder.*.log` |
| 09:20–15:35, every 5 min | `com.clade.engine-intraday` | **today's signals**: option chain → signals → dashboard export on the live recording | `engine_intraday.*.log` |
| 08:15, 16:15 | `com.clade.engine-sync` | auto-setup: reload changed jobs, rebuild dashboard, restart server (never in session) | `engine_sync.*.log` |
| 15:50 | `com.clade.engine-eod` | finishes today's signals, runs the **paper ledger**, writes the **trader's test** (`data/engine/<date>/trader_test.md`: every signal taken on the real order book, ₹ after charges, plus what fitted your account), compaction, OI cadence doc, archive to Drive | `engine_eod.*.log`, `data/engine/eod_last.json` |

During the session a new recommendation appears in the Radar **within about 5–10 minutes** of its decision time: one
5-minute tick plus a 3–6 minute run. Paper trades (Trades, Performance) appear only after the 15:50 job.

## 2. Setup is automatic

`com.clade.engine-sync` (`scripts/sync_launchd.py`, D-66) runs daily at 08:15 and 16:15, and at login. It:
- installs or reloads any engine job whose plist in `scripts/launchd/` changed (a job that is running is deferred to the next run);
- rebuilds the dashboard bundle when its source changed;
- restarts the dashboard server when Python code changed.

It never acts on a weekday between 08:55 and 15:55. A failure sends a phone alert, and the log is `dashboard/logs/engine_sync.out.log`. To apply a change right away: `python3 scripts/sync_launchd.py` (add `--dry-run` to preview).

Done once on 2026-11-07 and not needed again: the intraday job installed; `sudo pmset -c sleep 0` (no sleep on the charger; a weekday 08:45 wake was already set); the sync job installed. A closed lid still sleeps the Mac.

### Setup from a clean machine
1. Python 3.13 (`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`), then `pip install kiteconnect==5.2.2 pyarrow==26.0.1 boto3==1.43.124 pyyaml fastapi uvicorn requests beautifulsoup4 pypdf`.
2. Clone the repo to `~/Clade-NSE-Skills`. Copy `dashboard/kite_config.example.json` to `dashboard/kite_config.json` and fill in your API key. Store the API secret in the Keychain the way `dashboard/scripts/kite_secrets.py` expects. Run `python3 dashboard/scripts/refresh_kite_token.py` once.
3. Frontend: `cd dashboard/web && npm ci && npm run build`.
4. Copy every `scripts/launchd/com.clade.engine-*.plist` and `~/Library/LaunchAgents/com.clade.dashboard-server.plist`, then `launchctl load` each one (paths inside assume `~/Clade-NSE-Skills`).
5. Check it works: `python3 -m unittest discover -s tests/engine_tests -t .` should pass, and `curl -s http://127.0.0.1:8080/api/engine/sessions` should list sessions.

## 3. Daily checklist

**Before 09:15**
- Token: `tail -3 dashboard/logs/kite_refresh.log` shows a refresh after 08:00 today.
- Universe: `tail -5 dashboard/logs/engine_universe.out.log` shows today's master, constituents and ban list. If the ban list failed, every stock contract is `RESTRICTION_UNVERIFIED`, which means no stock signal can pass.
- Disk: `df -h ~` shows at least 5 GB free. Below 3 GB the recorder stops depth; below 2 GB it stops ticks (D-4).
- Mac on the charger, lid open.

**During the session**
- F&O Engine tab → **System**: the stream chip is on, there are no open gaps, and the allocator is within limits.
- `tail -2 dashboard/logs/engine_intraday.out.log` should show a JSON line every 5 minutes with `"signals": "ok"`.

**After 15:50**
- `data/engine/eod_last.json`: every step for today is `ok`/`done`, and `verified` is true for compaction.
- **Trades** / **Performance** show the day's SIMULATED trades, if any.

## 4. How to read the F&O Engine tab

Open `http://localhost:8080` → **F&O Engine**. Pick the day from the **session** dropdown at the top. Today is LIVE; any past day opens as a REPLAY at its close, and the replay-time control lets you scrub through it. Every panel shows its data **age**. A hatched STALE badge means the data is older than that panel's limit, so don't act on it. "—" with a reason means the value is UNAVAILABLE; it is never filled in or guessed.

| section | what it shows | how to use it |
|---|---|---|
| **Market** | NIFTY trend (latest 15m BOS/CHOCH), breadth (share of F&O stocks above VWAP), index futures positioning. India VIX is not recorded (UNAVAILABLE) | Context. A long signal against a falling NIFTY scores lower |
| **Radar** (start here) | One row per recommendation: Symbol, Direction, Signal, OI % / Price % / RVOL over the last 15 min on the near-month future, Score, Timeliness, Entry, SL, Target, Status | By default only non-rejected rows show. Tick **show rejected (n)** to see everything the engine found and why it said no. Click a row to open it in **Signal** |
| **Positioning** | Each underlying's quadrant: long buildup, short buildup, short covering, long unwinding, or neutral/not evaluated; plus a history scrubber | These are **hypotheses from public price/OI data**. Rising OI is not proof of institutional buying |
| **Option chain** | Strikes, IV (Black-76 from a fresh two-sided book only), Greeks | Empty after hours (empty books). IV percentile is UNAVAILABLE until 20 option sessions are recorded (D-64) |
| **Signal** | The chosen recommendation: chart with VWAP, levels, zones and sweeps; confirmation timeline (detected → confirmed → first TIMELY → entry-eligible); entry trigger, stop, T1/T2; expected net R:R after costs; evidence score by factor; contradictions and warnings; every gate with pass/fail | Read **Contradictions and warnings** before anything else. Every failed gate is listed with its number |
| **Trades** | Open SIMULATED (and your ACTUAL) trades: contract, qty/lots, entry, current bid/ask, the monitor's decision (HOLD · TIGHTEN_STOP · PARTIAL_EXIT_CANDIDATE · EXIT_REQUIRED · DATA_UNAVAILABLE) | Filled after 15:50 for paper trades |
| **Performance** | Win rate, expectancy (₹), profit factor per ledger. SIMULATED and ACTUAL are never added together | Not meaningful until there are many sessions; Phase 12 needs 20 GOOD sessions before any conclusion |
| **Journal** | "I took this trade" (price, qty, time) / "I skipped it" (reason) against a recommendation | Your real trades become the ACTUAL ledger, kept separate from SIMULATED |
| **System** | Feed health: gaps, subscription allocator usage, exchange→receive latency | If gaps are open, signals for that period are missing, not wrong |

**Status column (Radar)**

| status | meaning | what you do |
|---|---|---|
| **ENTRY_ELIGIBLE** | Every gate passed: timely, data fresh, contract liquid, spread OK, costs verified, risk check approved under your limits | This is "a signal". Read the Signal page; the entry trigger, stop and T1 are there. Act only if you agree; the engine places nothing |
| **WAIT_FOR_RETEST** | Valid setup, but price has moved away. It waits for a pullback into the retest zone | Watch; it becomes ENTRY_ELIGIBLE only if price comes back while the setup is still valid |
| **REJECTED** | At least one gate failed. The reasons are on the row and on the Signal page | Nothing. Useful to see what almost qualified |

**Score** is a research priority shown as points out of the maximum available from the inputs present (e.g. 38/67). It is **not a probability**.
**Timeliness**: TIMELY (fresh) · VALID_BUT_LATE (move already used up) · EXHAUSTED · UNKNOWN. Only TIMELY can become ENTRY_ELIGIBLE.
**Prices** are per unit in ₹. Futures signals are 1+ lots, sized so the stop-out loss is at most ₹10,000 (D-61). Capital per trade is at most ₹1,00,000, with margin estimated at 25% of notional (D-62, an estimate, not Zerodha's real margin).

**Why you may still see few or no ENTRY_ELIGIBLE rows.** On 2026-11-06 under your settings all 86 were rejected. Every one failed TIMELINESS; 81 failed capital (one lot of a ₹5–10 lakh future needs ₹1.25–2.5 lakh at 25% margin, above your ₹1 lakh per-trade cap); 80 had net R:R below 1.5. Options cannot pass until about 20 sessions of IV history exist. These are your limits and the engine's filters, not faults. Your ₹6,000 daily-loss exit (D-44) also closes a paper trade before its ₹10,000 stop.

## 5. Troubleshooting (each behaviour is proven by the named test; the live drills in Phase 15 step 4 are not done yet)

| symptom | what the system does | proving test | what you do |
|---|---|---|---|
| WebSocket drops mid-session | gap recorded; no synthetic ticks; panels go STALE; KiteTicker reconnects; a half-open socket becomes a `stall` gap after 10 s | `test_disconnect_produces_gap_and_no_synthetic_ticks`, `test_half_open_socket_becomes_a_stall_gap_once_and_clears_on_reconnect` | nothing; check System for the gap. If the recorder died, it is retried every 15 min |
| Access token expired / invalid | clean `TokenException`, token never logged | `test_expired_token_fails_cleanly_without_leaking_token` | `python3 dashboard/scripts/refresh_kite_token.py`, then wait for the next 15-min recorder retry |
| Disk low | < 5 GB alert; < 3 GB depth stops; < 2 GB ticks stop; each logged as a gap | `test_disk_guard_degrades_depth_then_ticks_with_gap_records` | free space; the EOD archive moves sessions older than the last 5 to Drive |
| Ban list unavailable | every stock contract `RESTRICTION_UNVERIFIED` (not tradable) | `test_missing_ban_list_is_restriction_unverified` | rerun the universe job: `launchctl kickstart gui/$(id -u)/com.clade.engine-universe` |
| Results / event calendar unavailable | every option event `UNVERIFIED` ⇒ rejected | `test_missing_or_stale_calendar_rejects_every_option_event_unverified` | nothing until it refreshes |
| OI frozen for an instrument | OI older than 300 s ⇒ that view `OI_STALE`, suppressed | `test_stale_oi_suppressed` | nothing |
| Clock skew exchange vs local | **not handled or drilled**; latency is measured (System panel) but not corrected | — | keep macOS automatic time on |
| Recorder / DB restart | restart recorded as a gap with a new connection id; SQLite stores are append-only (no Redis, D-11) | `test_restart_records_gap_and_uses_new_connection_id` | nothing |
| Radar empty during the day | recorder not running, or Mac asleep (intraday failures also send a phone alert) | `test_intraday_runs_only_during_a_live_session` | `tail dashboard/logs/engine_intraday.out.log`; §2 |
| Radar shows the wrong day | tab opened before the recorder created today's directory | — | pick today in the session dropdown |

## 6. Weekly and monthly

- **Weekly:** verify archive checksums (`engine.retention` verifies on every archive; check `eod_last.json` → `retention`). Review gaps (System panel per day). Review your Journal skips/takes.
- **Monthly:** `python3 scripts/reverify_facts.py > docs/phase-15-evidence/facts-reverify.jsonl` (every quoted fact re-opened). Re-check charges against zerodha.com/charges. Rerun Phase 12: `python3 -m engine.backtest_report recorded`.
- **Before 2026-12-07:** NSE session hours change (F-NSE-9, Q-3-1). The config has a single 15:40 close, so it needs a new version with the new hours once NSE publishes its circular.
