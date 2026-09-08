# Spec — MCX / Commodities support (options on futures)

Status: **DRAFT for review** · Scope: a new isolated **Commodities tab** + reuse of the
instrument-agnostic engine, parameterised for MCX. Companion to `docs/exit-structure-spec.md`.

## Decisions locked (from review)
- **Instrument:** options on MCX futures (CE/PE on the commodity future).
- **Universe:** Energy (Crude, NatGas) + Bullion (Gold, Silver) + Base metals (Copper, Zinc,
  Lead, Aluminium, Nickel). Options liquidity is concentrated in **Crude, NatGas, Gold,
  Silver** (+ minis GOLDM/SILVERM/CRUDEOILM/NATGASMINI); base-metal options are thin.
- **Isolation:** a separate tab; never mixed with the stock boards.
- **Sequencing:** foundation first. **C0 is DONE** (segment-aware session/hours).

## Why commodities are not "equities with different symbols"
See the analysis in chat; the essentials the design must honour:
1. The tradeable underlying is a **future** (no cash leg). An MCX option's underlying is the
   commodity's future — and the option expires **before** its future (live check: COPPER opt
   2026-09-23 vs ALUMINI fut 2026-09-30). T must use the **option** expiry.
2. **Hours** run to ~23:55 IST (evening session for global cues) — handled in C0.
3. **Drivers are global**, not domestic breadth: DXY, US real yields, COMEX/NYMEX/LME, and
   USDINR (MCX price ≈ international × USDINR). The equity HEALTH/regime is meaningless here.
4. **Small, event-driven universe** (~4–6 liquid names), each moved by scheduled prints
   (EIA, OPEC, FOMC), not a 180-name breadth scan.
5. **Large notional, fast moves** (Crude/NatGas 3–5% in minutes on inventory data) → ATR-first
   sizing and risk discipline matter more.

## Live ground-truth (probed from the Kite MCX master)
- `https://api.kite.trade/instruments/MCX` → 15,625 rows; segments `MCX-FUT` (154),
  `MCX-OPT` (15,460), `INDICES` (11, e.g. MCXBULLDEX).
- **Symbol formats are the SAME shape as NSE monthly options:** future `ALUMINI26SEPFUT`
  (`<NAME><YY><MMM>FUT`), option `COPPER26SEP1330CE` (`<NAME><YY><MMM><STRIKE><CE|PE>`). So
  `structure_exit._SYM` / `position_prob._SYM` already match MCX options — the discriminator
  between an NSE and an MCX instrument is the **position's `exchange` field** (`MCX` vs `NFO`),
  not the symbol shape.
- Underlyings present: CRUDEOIL, CRUDEOILM, NATURALGAS, NATGASMINI, GOLD, GOLDM, GOLDGUINEA,
  SILVER, SILVERM, SILVERMIC, COPPER, ZINC(MINI), LEAD(MINI), ALUMINI(UM), NICKEL, …
- Lot sizes/tick vary per instrument (from the master, never assumed).

## Architecture

New module `dashboard/mcx.py` — the MCX analogue of `option_chain.py` + `swing_scan`'s
instrument plumbing, plus a commodity-context builder:
- `_instruments()` → cached `instruments/MCX` master (mirrors `option_chain._instruments`).
- `futures_map()` → name → front-month future {token, tradingsymbol, lot_size, expiry, tick}.
- `option_underlying_future(name, opt_expiry)` → the future backing an option (same name,
  nearest expiry ≥ the option's).
- `chain(name)` → ATM option chain on the future (mirrors `option_chain.chain`, but MCX master
  + MCX quotes + the FUTURE's price as "spot").
- `context()` → inter-market panel (yfinance): DXY `^DXY`, USDINR `USDINR=X`, US10y `^TNX`,
  COMEX/NYMEX front-months (`GC=F`,`SI=F`,`CL=F`,`NG=F`,`HG=F`) → per-commodity "why it's moving".
- daily/intraday candle fetch for MCX futures (reuse the `trailing_backtest.fetch_window` /
  `structure_exit.fetch_intraday` seams with the MCX token).

New tab `dashboard/web/src/tabs/Commodities.tsx` + `TabId "commodities"` + `/api/mcx/*` routes.
**Reuse, parameterised by exchange/asset — no forks of the engine.**

| Existing | Reuse for MCX | Change |
|---|---|---|
| `exit_monitor` premium floors | ✅ as-is (instrument-agnostic) | already applies to MCX positions |
| session/hours | ✅ C0 done | `market_session(exchange="MCX")` |
| `structure_exit` (swing break, ATR) | ✅ logic | underlying = MCX **future** candles; route by `exchange=="MCX"` |
| `position_prob` (±1SD, P-profit) | ✅ math | needs `mcx.chain()` + future price + **option** expiry |
| backtest harness | ✅ | MCX future history; commodity regimes |
| HEALTH/regime/breadth | ❌ | replace with `mcx.context()` per commodity |

## C1 — Commodities tab + watchlist + context
- Isolated tab. A **watchlist** of the chosen liquid names: front-month future price, %chg,
  **ATR(14) & expected daily range**, day range, and the option-chain snapshot (ATM ±).
- **Inter-market context** per commodity (replaces HEALTH): DXY, USDINR, US10y, the matching
  international future, with a one-line "driver read" (e.g. "Gold: DXY −0.4%, real yields
  down → tailwind"). Honest, mechanical, not advice.
- MCX session chip (from `/api/market/session?exchange=MCX`).
- New: `dashboard/mcx.py` (master, futures_map, quotes, context) + `/api/mcx/watchlist`,
  `/api/mcx/context`. Isolated; touches no stock board.

## C2 — Structure exits for MCX (extends 2a/2b)
- `structure_exit.position_signal` becomes exchange-aware: for an MCX option, resolve the
  underlying via `mcx.option_underlying_future()` and pull the **future's** candles (daily for
  positional/NRML, intraday for MIS) instead of the NSE futures map.
- **ATR-first trail** is the natural commodity fit (they respect ATR) — promote the ATR
  chandelier (spec §7.3 in the exit doc) to the primary MCX trail, structure break as backup.
- Commodity **regime** for the breakeven arm: `_effective_be_arm` becomes exchange-aware —
  MCX positions must NOT use the equity regime. Options: (a) neutral/static arm for MCX, or
  (b) a per-commodity ATR-trend regime. Start with (a); (b) is a refinement.

## C3 — Position probability for MCX options
- `mcx.chain(name)` → future price (as "spot"), ATM strikes, IV (Black-Scholes bisection,
  reuse `option_chain._iv`/`_bs`), the **option** expiry for T.
- Feed the existing `position_prob` math (±1SD move on the future, P-profit vs breakeven,
  P-ITM). Extend the Monday push / a commodities panel to cover MCX option positions too.

## C4 — Event calendar + inventory-print guard (the differentiated value)
- A small **maintained calendar** (static JSON, refreshed monthly — no clean free API): EIA
  NatGas (Thu 20:00 IST), EIA Crude (Wed 20:00 IST, 20:30 in US DST), OPEC, FOMC, US CPI/NFP.
- Countdown + a **"holding naked into a print"** flag on any open MCX position whose commodity
  has an event inside N hours → a heads-up (never an auto-exit). This is what a commodity
  trader most needs and equities never had.

## C5 — Backtest (commodity-tuned)
- Run the trailing/structure/ATR policies on **MCX future** daily history (Kite) per commodity,
  with commodity regimes (trend vs range; note Kite intraday history is shallow, as in 2b).
- Report the same rescued/whipsaw/avg-bars framing. Validate ATR widths per commodity before
  enabling (Crude/NatGas need wider ATR than Gold).

## Config (new keys; isolated from the exit config where possible)
```jsonc
"mcx_enabled": true,
"mcx_universe": ["CRUDEOIL","NATURALGAS","GOLD","SILVER","COPPER","ZINC","LEAD","ALUMINIUM","NICKEL"],
"mcx_watch_liquid_only": true,          // prefer the options-liquid subset
"mcx_atr_mult": { "energy": 1.5, "bullion": 2.0, "metals": 1.75 },
"mcx_event_guard_hours": 6,             // warn if an event is within N hours
"breakeven_arm_by_exchange": { "MCX": 8.0 }  // MCX uses a static arm, not the equity regime
```

## Cross-cutting & risks
- **DST hours:** MCX evening close shifts 23:30↔23:55 with US DST. C0 uses 23:55 (safe
  over-cover). Refine with a DST rule if needed.
- **Holiday calendars differ** (MCX vs NSE; commodities also track US holidays for the evening
  session). Neither is modelled — a missing session just yields fewer candles.
- **Thin base-metal options:** wide spreads → position-prob IV noisy, exits may not fill.
  Watchlist can show them; treat options analysis as liquid-names-first.
- **Notional/risk:** large lots; the tab must show notional & ATR risk prominently.
- **Symbol-format drift / mini vs main:** GOLD vs GOLDM vs GOLDPETAL are different contracts —
  map carefully by exact `name`. Build the parser/map from the master, verify, never assume.
- **Regime contamination:** until C2's exchange-aware arm lands, MCX option positions use the
  equity regime for the breakeven arm — a minor arm mis-tune (not a correctness bug).

## Open decisions (before C1 build)
1. **Watchlist:** the full 9 names, or the liquid-4 (Crude/NatGas/Gold/Silver) first with
   base metals as a later add?
2. **Context depth:** full inter-market panel (DXY/USDINR/US10y/intl future) in C1, or just
   MCX price/ATR first and layer context in C4?
3. **Minis:** trade the mains (GOLD/SILVER/CRUDEOIL) or the minis (GOLDM/SILVERM/CRUDEOILM)?
   Determines which future/lot the watchlist and sizing use.
```
