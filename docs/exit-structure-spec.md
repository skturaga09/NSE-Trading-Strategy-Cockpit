# Spec — Underlying-Structure Exits (Exit engine, Phase 2-proper)

Status: **DRAFT for review** · Author: cockpit · Scope: `dashboard/exit_monitor.py` + a new
`dashboard/structure_exit.py` + backtest. Prereq context: Phase 1 (breakeven lock) and the
regime-aware arm are already live.

---

## 1. Why

Every exit rule today acts on the **option premium's** P&L% (`exit_monitor.evaluate` →
`_exit_signal`: stop / target / ratchet / breakeven). Premium is a noisy proxy for the
thing we actually care about — the **underlying's trend**:

- **Theta** bleeds the premium daily even when the underlying is fine → a premium give-back
  can trigger an exit that the stock never justified.
- **IV** crush/expansion moves the premium independently of direction.
- A real **structure break** on the stock (the seasoned-trader signal: *failed continuation
  → break of the last higher-low*) may be muddied in the premium.

So the premium floors are the right **hard safety net**, but the **smart trail** should be
driven by the underlying's price structure, then translated to an option action. This spec
covers that layer.

## 2. Principles (distilled from the brainstorm, deliberately minimal)

1. **Structure > indicator.** The primary trigger is a market-structure break (close beyond
   the last confirmed swing), not RSI/MACD. Indicators only *confirm*.
2. **Multi-signal, but few.** Require the price trigger; use at most one or two confirmations.
   No full exit on a single oscillator (a strong name stays overbought for weeks).
3. **Close-based, not touch-based.** Act on candle *closes* to avoid intrabar whipsaw.
4. **Progressive, not binary.** Tighten → partial → full, mirroring the ratchet philosophy.
5. **One parametrized engine**, three timeframes (intraday / swing / positional) — only the
   candle interval and ATR/EMA constants change. Not three engines.
6. **Everything backtested per regime before it goes live** (anti-overfitting rule).

## 3. Architecture

New module `dashboard/structure_exit.py` — pure indicator helpers + one signal function.
`exit_monitor.evaluate()` calls it as an **additional, composable** layer:

```
per position p (option):
    underlying = parse(p.symbol)            # reuse position_prob._SYM
    tf         = timeframe_for(p)           # intraday | swing | positional (§6)
    candles    = candles_for(underlying, tf)# daily = warm cache; intraday = new seam (§5)
    struct_sig = structure_exit.signal(candles, side, cfg, tf)   # {action, reason, level}
    prem_sig   = _exit_signal(pnl_pct, peak, cfg, hhmm, be_arm)  # existing premium floors
    final      = combine(prem_sig, struct_sig)                    # §7 precedence
```

`structure_exit.signal()` is **pure over an OHLC list** (same discipline as
`trailing_backtest.trail_exit`) so it is unit-testable and backtestable with zero live deps.

## 4. Indicators (all on the UNDERLYING)

| Indicator | Have it? | Source / work |
|---|---|---|
| Swing low / higher-low (fractal pivots) | ✅ `swing_scan._structure_levels` | extend to return the *price* of the last confirmed pivot + a "close broke it" boolean |
| SMA (200/50-DMA) | ✅ `live_market._dma` | reuse for context/regime only |
| **EMA(9/20)** | ❌ | new `_ema(series, n)` (recursive) |
| **ATR(14)** | ❌ | new `_atr(candles, n)` (Wilder) → chandelier trail |
| VWAP (intraday) | ⚠️ partial | Kite `/quote` `average_price` is session VWAP; fine for intraday side |
| Relative volume | ✅ (via futures candles, `intraday_ignite`) | reuse for the volume-climax confirmation |
| RSI(14) / Supertrend | ❌ | new; **confirmations only**, lowest priority |

## 5. Data & timeframes

- **Daily** (swing / positional): `swing_scan._daily_candles(token)` — already cached once/day,
  warm. **Zero new cost.** This is why Phase 2a starts here.
- **Intraday** (5- or 15-min): **new data seam.** Options:
  - (a) Kite historical `.../{token}/{interval}` (`5minute`/`15minute`) — clean OHLC, rate-limited.
  - (b) Build bars from the `/quote` snapshots the exit job already polls — no extra calls but
    coarser and only from when the job started.
  - **Decision:** start with (a) behind a `fetch_intraday(token, interval)` seam mirroring
    `trailing_backtest.fetch_window`, cached per (token, interval, day-slice). Deferred to Phase 2b.
- Token: options are on stocks → use the **futures token** from `swing_scan._futures_map`
  (already used for candles), or the cash token. Keep consistent with how `_daily_candles` is keyed.

## 6. Timeframe selection per position

```
positional : product == "CNC" / holding > ~5 sessions   → daily candles,  ATR×2.5–3, EMA20 trail
swing      : product == "NRML", overnight F&O            → daily candles,  ATR×1.5–2, EMA9→20
intraday   : product == "MIS" / same-day                 → 15-min candles, ATR×0.75–1, EMA9 + VWAP
```
Config-driven map `structure_tf_by_product`. Default swing (matches the current book).

## 7. Exit signal hierarchy (what `structure_exit.signal` returns)

Evaluated on the underlying, **close-based**, for a LONG option (mirror for PUT/short):

1. **FULL EXIT — structure break (primary):** underlying **closes below the last confirmed
   higher-low** (from `_structure_levels`), OR closes below **EMA20** with above-average volume.
2. **TIGHTEN / PARTIAL — failed continuation:** made a new high then **closed below EMA9**
   after an extended move (≥ ~2 ATR above EMA20), or printed a lower-high. → book 25–33%, tighten.
3. **CHANDELIER TRAIL — ATR give-back:** exit if close falls **N×ATR below the highest close**
   since entry (N by timeframe, §6). This is the structure analogue of the premium ratchet.
4. **CONFIRMATIONS (never standalone):** bearish RSI divergence, volume climax at resistance,
   loss of VWAP (intraday). Only *upgrade* a tighten→full or size a partial; never fire alone.

Return shape: `{ "action": "EXIT"|"TRIM"|"HOLD", "size_pct": int, "reason": str, "level": float }`.

## 8. Underlying → option translation

- A structure **EXIT/TRIM** on the stock maps to an option action. Surface as a new signal
  label **`STRUCT`** (add to `SIG_COLOR`/`SIG_EMOJI` and the `evaluate` sort map) so it reads
  distinctly from the premium `STOP/TARGET/TRAIL`. Alert copy names the stock level ("NIFTY
  closed below 24,180 higher-low"), which is far more actionable than a premium %.
- **Partial scaling** (`TRIM size_pct`): the monitor is signal-only today (no orders), so a
  TRIM is an alert to book N%. If/when GTT actuation lands, size maps to lots.

## 9. R-multiples (unlock the brainstorm's 1R/2R rules)

`journal.py` **already persists `planned_stop`** at entry (schema line 80). So:

- Join the live Kite position to its journal row by symbol → `R = |entry − planned_stop|`.
- Then the brainstorm's ladder becomes real: **+1R → move premium floor to breakeven**
  (already done via the breakeven lock, but make its arm optionally R-based, not %-based);
  **+2R → TRIM 50%**; beyond → structure/ATR trail.
- Gap: exit_monitor reads Kite portfolio, not the journal. Add a `planned_stop` lookup
  (symbol → journal). Fallback to %-based when no journal row exists (manual trades).

## 10. Composition with the existing premium floors (§7 vs `_exit_signal`)

The structure layer is **additive**, not a replacement. Final action = **first/strongest** of:

```
premium STOP (hard −stop%)              # non-negotiable safety net, always wins
structure EXIT (close below higher-low) # smart exit
premium TARGET / ratchet / breakeven    # existing profit protection
structure TRIM / chandelier             # smart trail
TIME / PULLBACK                         # heads-up
```
Precedence: **capital-preservation exits outrank profit-taking**; within a tier, structure
and premium are OR'd (whichever fires). De-dupe so one position raises one alert per cycle.

## 11. Config (new keys, all defaulted + tunable in the Exits tab)

```jsonc
"structure_exits": true,
"structure_tf_by_product": { "MIS": "intraday", "NRML": "swing", "CNC": "positional" },
"structure_ema_fast": 9, "structure_ema_slow": 20,
"structure_atr_mult": { "intraday": 1.0, "swing": 1.75, "positional": 2.75 },
"structure_confirmations": ["volume_climax"],   // subset of rsi_div|volume_climax|vwap_loss
"structure_partial_pct": 33,
"r_multiple_exits": false                        // Phase 2c; needs journal planned_stop join
```

## 12. Backtest plan (before any of this goes live)

Big advantage: the **trigger lives on the underlying**, which we already have candles for —
so the structure layer is directly backtestable with **no synthetic option layer** for the
signal (the P&L can still be priced through `breakeven_backtest`'s BS layer for realism).

- Extend `trailing_backtest` / `breakeven_backtest`: add a `structure_exit` policy alongside
  `hold` / `trail width` / `breakeven`, run over the same CHOP / TREND / CRASH windows.
- Metrics: avg P&L%, win%, **rescued vs whipsaw** (same framing as the breakeven backtest),
  and **avg bars held** (structure trails should exit trends later, chop earlier).
- Compare structure-exit vs the current premium-only floors. Ship only the timeframe/ATR
  constants that are robust across all three regimes.

## 13. Phased rollout

- **2a — daily structure, swing/positional (low risk, zero new data):** `_ema`, `_atr`,
  extend `_structure_levels`; `structure_exit.signal` on daily candles; wire into
  `evaluate` behind `structure_exits`; `STRUCT` signal label; backtest on daily. ← start here
- **2b — intraday timeframe:** `fetch_intraday` seam + 15-min structure for MIS trades.
- **2c — R-multiples + partial scaling:** journal `planned_stop` join; +1R/+2R ladder; TRIM.
- **2d — confirmations:** RSI/Supertrend/volume-climax/VWAP as upgraders, backtested for lift.

## 14. Risks & limits

- **Intraday data cost / rate limits** (2b) — cache hard, fetch per candle-close only.
- **Alert cadence** — structure signals are close-based; fire on the *5/15-min or daily close*,
  not every 3-min poll, or they'll spam. Gate the alert to one per new closed bar.
- **Look-ahead** — pivots need `k` bars each side to confirm; only use *confirmed* pivots
  (same conservative rule as `_structure_levels`), never the forming bar.
- **Holidays** — none of the candle logic assumes a holiday calendar; a missing session just
  means fewer bars. Acceptable.
- **Options liquidity** — a structure exit on the stock still needs a fillable option; keep
  the premium hard-stop as the ultimate backstop.
- **Overfitting** — cap active confirmations; prefer robustness across regimes over peak
  backtest P&L; re-validate on journal history.

## 15. Open decisions (need your call before 2a)

1. **Timeframe default** — is the book mostly swing (daily structure) as it looks, so 2a
   covers most positions? Or is intraday (2b) the priority?
2. **Full vs partial** — do you want TRIM alerts (book 25–33%) now, or full EXIT only until
   GTT actuation exists?
3. **EMA20-with-volume vs pure higher-low break** as the primary full-exit — or require both?
4. **R-multiples** — worth the journal-join now (2c), or defer until manual trades are also
   journaled with a planned stop?
```
