# Spec — Commodity Setup Radar (MCX idea generation, "C6")

Status: **DRAFT for review** · Builds on the MCX module (C0–C5). Gives commodities a
first-class *idea generator* — the equivalent of the equity Radar/Swing boards — that the
current MCX tab lacks (today it validates/monitors/manages a name you bring; it does not
surface directional setups).

## Why
For stocks, Radar (ignition) and Swing (OI board) surface directional candidates with the
CE/PE side spelled out. For commodities there is no such generator: `trade_state =
ELIGIBLE_FOR_REVIEW` is only a data/liquidity gate, not a setup. The entry idea comes
entirely from the trader. This spec adds a mechanical, per-commodity setup screen.

## Principles (non-negotiable)
1. **Direction comes from PRICE STRUCTURE / trend — never from predicting an event outcome.**
   Technicals give the bias; events are a *gate*, not a forecast (do not infer bullish/bearish
   from an inventory/CPI print without separately validated logic).
2. **Observation / condition / review — never an auto or blind buy/sell.** Output is a ranked
   screen with an explicit "why"; the trader decides and sizes. Same stance as every MCX surface.
3. **Few rules.** A small set of robust detectors, not an indicator zoo (the equity radar's
   over-fitting lesson applies harder to a ~5-name universe).
4. **Gated by the existing safety layer** — data-quality, liquidity grade, roll state, event
   guard. A setup is only surfaced as eligible when it also passes those.
5. **Backtested before trusted.** The setup's directional edge is validated on the roll-stitched
   MCX history (C5 harness) per root/regime before any "eligible" label is believed — until
   then it is labelled a *screen*, not an edge.
6. **Small ranked universe, not a 180-name scan.** It evaluates each liquid commodity and ranks
   them; there is no breadth sweep.

## What is a "setup" (detectors on the FUTURE's candles)
Computed on the contractual front future (daily for positional/swing; an intraday evening lane
comes later). Three mechanical detectors, each producing a direction + strength:

- **Trend continuation** — price above/below EMA(20) with the fast/slow (9/20) aligned and a
  higher-high/higher-low (or mirror) structure intact; strength from ATR-normalized distance
  and slope. Direction = trend direction.
- **Breakout / ignition** — close beyond the last confirmed structure pivot (reuse
  `structure_exit.last_confirmed_pivot`) WITH ATR expansion (today's range / ATR ≥ k) and
  above-average volume. Direction = breakout direction. This is the commodity analogue of the
  equity ignition radar.
- **Pullback-to-structure** — in an established trend, a pullback to EMA20 / a prior swing that
  holds. Direction = trend direction (a continuation entry, not a reversal call).

Each detector returns `{direction: LONG|SHORT|NONE, kind, strength 0..1, levels}`. A commodity
with no detector firing → `NONE` (watch only).

## Direction → CE/PE (options on futures)
LONG bias → a CALL (CE); SHORT bias → a PUT (PE) — the same explicit mapping the Swing board
uses. The radar attaches an **option leg suggestion** via the C3 analytics: suggested strike
(ATM or ~0.3–0.4Δ OTM, configurable), expected ±1SD move, breakeven, and P(profit)/P(ITM)
bands — published only when the option quote is two-sided (else the setup shows but the option
leg is "quote too thin to size").

## Composite score + eligibility
`setup_score (0..100)` = weighted blend of: trend alignment, breakout/ATR expansion, volume,
and **context alignment** (from `mcx_context` — is the MCX move backed by the benchmark×USDINR,
or a low-alignment basis dislocation?). Thresholded (`MIN_SCORE`) to surface. The score is a
*screen rank*, explicitly not a probability or an edge until C6c validates it.

`trade_state` (reuse the existing taxonomy) is the go/no-go and always wins over the score:
`NO_DATA / STALE_DATA / ILLIQUID (grade C/D) / ROLL_GUARD (expiry_risk) / EVENT_GUARD
(high event within guard) → not eligible`; only a firing setup on fresh, liquid, non-roll,
event-clear data becomes `ELIGIBLE_FOR_REVIEW`. **Event handling:** an imminent high-severity
event does NOT set a direction — it *blocks/flags* new entries (and blocks new naked short
premium outright), exactly as C4 already does.

## Reuse map (no new engines)
| Need | Reuse |
|---|---|
| Future candles / ATR / pivots | `mcx._daily_candles`, `structure_exit._atr` / `chandelier` / `last_confirmed_pivot` |
| EMA | small `_ema` helper (add) |
| Context alignment | `mcx_context.mcx_global_attribution` |
| Event gate | `mcx_events.new_entry_blocked`, `within_guard` |
| Liquidity / data-quality / roll | `mcx.liquidity_grade`, `mcx.data_quality`, `mcx.roll_state` |
| Option leg (strike/EM/prob) | `mcx_analytics.option_analytics` (C3) |
| trade_state taxonomy | `mcx._trade_state` (extend) |

New module `dashboard/mcx_setups.py`; endpoint `GET /api/mcx/setups`; a "Setups" section at
the top of the Commodities tab (ranked cards). Pure detectors take a candle list (fixture-testable).

## VALIDATION STATUS (C6c, 2026-09-08)
- **trend+breakout: NO edge on daily** — underperformed momentum on all four roots and the
  score was *inverted* (higher score → worse). Buying daily breakout strength mean-reverts.
- **pullback: promising** — a mean-reversion-in-trend entry beats trend+breakout and has far
  lower drawdown (CRUDEOIL +6.35%/77.8% win/maxDD −3.8% vs momentum +2.3%/−35%; positive on
  3/4 roots; SILVER still negative on a tiny sample). So the **live detector is now `pullback`**;
  trend/breakout are kept but off.
- **INTRADAY validation (mcx_intraday_backtest, 15-min roll-stitched): NO edge.** The daily
  pullback edge did NOT translate to the live 15-min lane — CRUDEOIL pullback 0.0%/29.5% win
  (vs momentum 0.01%/42%), NATGAS +0.05% (marginal, 33.7% win), GOLD no intraday history from
  Kite, SILVER too thin. The daily edge was multi-day swing mean-reversion; at 15-min it's
  flat and cost-dominated. Score buckets don't discriminate.
- **Gate STAYS off** (`mcx_setups_validated=false`) → WATCH-only, never ELIGIBLE. The live
  (intraday) lane has no demonstrated edge, so it must not surface a tradeable signal.
  **The edge lives on the DAILY (swing/positional) timeframe, not intraday.**
- **DAILY positional lane — BUILT & gated per-root (OOS split).** `setups(lane="daily")` runs the
  pullback on daily bars. Per-root out-of-sample check (both history halves positive): only
  **CRUDEOIL** held (H1 +8.2% / H2 +5.3% / 77.8% win / R 1.15); NATGAS/GOLD/SILVER failed the
  split. So `mcx_setup_daily_validated_roots=["CRUDEOIL"]` — CRUDEOIL daily pullbacks may surface
  **ELIGIBLE_FOR_REVIEW** (still gated by liquidity/roll/event); every other root and the whole
  intraday lane stay **WATCH-only**. Endpoint: `/api/mcx/setups?lane=daily|intraday`. Even CRUDEOIL
  is ~18 trades — treat as a reviewed screen, re-validate as samples grow.

## Backtest / validation (C6c — before "eligible" is trusted)
Extend `mcx_backtest.py`: replace the momentum-proxy entry with the **setup signal** entry
(enter on a firing setup in its direction, exit via the C2 chandelier), and compare to the
momentum baseline, per root and per regime, with walk-forward. Report win%, avg R, MAE, and
whether the setup adds edge over "always momentum." Ship the detector thresholds only where
robust across roots/regimes. Small samples (shallow MCX history) → treat as directional
mechanism validation, not proof.

## Config (isolated, defaults not validated values)
```jsonc
"mcx_setups_enabled": true,
"mcx_setup_min_score": 55,
"mcx_setup_detectors": ["trend", "breakout", "pullback"],
"mcx_setup_ema_fast": 9, "mcx_setup_ema_slow": 20,
"mcx_setup_breakout_atr_mult": 1.0,     // today's range / ATR to count as expansion
"mcx_setup_volume_mult": 1.3,
"mcx_setup_min_liquidity_grade": "B",
"mcx_setup_suggested_delta": 0.35,      // OTM strike target for the option leg
"mcx_setup_block_new_naked_short_before_high_event": true
```

## Phased rollout
- **C6a** — daily detectors (trend / breakout / pullback) + score + gates (data/liquidity/roll/
  event) + CE/PE + C3 option leg; `/api/mcx/setups`; ranked cards on the tab. Labelled a screen.
- **C6b** — intraday evening lane (15-min) for event-driven momentum during the US overlap.
- **C6c** — setup-entry backtest validation (extend C5); enable "eligible" confidence only where it validates.
- **C6d** — context/event scoring refinements; optional per-commodity ATR-trend regime.

## Safety & honest limits
- Never auto-executes; direction is a technical read, not an event-outcome forecast; every card
  carries its "why", data freshness, liquidity grade, roll and event state.
- Not an edge until C6c; thresholds are starting points.
- Daily bars → no intraday session detail in C6a (C6b lane); ~5-name universe (small samples);
  base-metal options thin → screen-only, not entry-eligible by default.
- Inherits the MCX production gates: contract profiles / broker cutoffs unverified → expiry-
  sensitive names stay in manual review regardless of a firing setup.

## Open decisions (before C6a build)
1. **Positional (daily) first, or the intraday evening lane first** (that's where crude/natgas
   event-momentum lives)?
2. **Suggested option leg**: ATM, or ~0.35Δ OTM (cheaper, more leverage, lower P-profit)? Or
   just surface the future direction and let the trader pick the strike?
3. **Pullback detector** in C6a, or start with just trend + breakout (fewer rules) and add
   pullback after validation?
```
