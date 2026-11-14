# Phase 7 report: contract selector V1 and centralized risk engine

Date: built 2026-11-06 (IST, evening). Branch `stack/4-setup-radar`, base `defa774`. Nothing committed.
Read first: architecture.md, verified-facts.md, open-questions.md, phase-0…6 reports. Phases 5 and 6 still await your review.
Advisory and paper-trading only: no order placement, modification or cancellation exists. `test_no_order_methods_in_repo_code` and
`test_engine_never_uses_kiteconnect_rest_class` pass.

## 0. Headline

On the 10 recorded setups of 2026-11-06, **every one of the 50 candidates is REJECTED. The selector returns NO_TRADE for all 10.** This is the
correct output for the inputs, not a tuning result. There are three causes, each fixable only by a decision of yours:
1. **Options: no option was ever recorded** (0 CE/PE tokens in the 2026-11-06 buffer). All 40 option candidates are NO_TRADE (NO_PREMIUM_MODEL + NO_QUOTE). Q-CON-1.
2. **Futures: margin is estimated at full notional.** The Kite margin API is a POST, and the engine adapter is GET-only. So no future fits the ₹1,00,000 per-trade capital limit (₹4.5 L–₹16 L). Q-RISK-1.
3. **Costs are large for tight setups.** One NIFTY lot pays ₹962 round trip (STT alone ~₹809 at the new 0.05 %). That took a Phase 6 TIMELY setup to **0.07 net R:R**. Q-CON-4.

Every risk value in v9 is **PROPOSED**, not yours (Q-RISK-2).

## 1. Interpretations (rule 16: the more conservative reading), flagged

- **Cost source.** The backtest-expert model is *not* reused, because it is wrong for 2026. Its F&O STT is 0.0125 %; the verified rate is 0.05 % for futures and 0.15 % for options from 2026-04-01. Its options exchange rate is 0.05 %; the verified rate is 0.03553 %. The lab schedule is stale too. A new versioned schedule is in `config/engine/v9.yaml` `costs.entries`.
- **Effective dates.** Only STT has an official start date (2026-04-01). The other five components were read as current on 2026-11-06, and the page states no effective date. So their `effective_from` is the read date, and any earlier trade date is costed **UNVERIFIED** (Q-COST-1). The phase asks for an effective-from date on every charge, so this requirement is marked PARTIAL.
- **IPFT** is included (₹0.01 / crore + GST, as the page states). Exercise STT is not modelled: V1 candidates exit before expiry.
- **Slippage.** Entry = the walked fill on the executable side, so it already includes the half-spread and the depth impact. Exit slippage at the stop and at T1 = the same book's other side, because the exit-time book is unknown (ESTIMATED). If the 5 visible levels do not hold the order, the candidate is ILLIQUID:DEPTH; nothing beyond level 5 is guessed. Without depth, slippage per side = `no_depth_spread_multiple` (1.0) × the full spread.
- **Margin.** The Kite margin API is documented (F-MARGIN-1), but it is a JSON POST that lives only on the banned `KiteConnect` class. Adding a POST to the read-only adapter is your call (Q-RISK-1). Until then futures are MARGIN_ESTIMATED at `fraction: 1.0` × notional: no SPAN source is verified, so full notional is the conservative choice. The selector already accepts margin quotes (`margins`, MARGIN_API, tested).
- **Premium model.** EMPIRICAL_DELTA_OLS: OLS through the origin of the option's 1m close changes on the setup instrument's (the near-month future). It uses the last 30 usable bars at or before the decision time and needs ≥ 20 contiguous pairs, R² ≥ 0.5, and a delta in (0, 1] for calls or [−1, 0) for puts. It is linear (no gamma, theta or IV) and labelled APPROXIMATE. A premium below zero at the stop is floored at 0 and labelled. No Black-Scholes delta, since IV is not reliably computable (no recorded option data, no verified rate or dividend inputs).
- **ATM** = the strike nearest to the **spot** last price; a tie goes to the ITM side. One strike ITM = the next strike below (calls) or above (puts). Spot older than `quality.stale_price_s` ⇒ options are not evaluated (a note).
- **Rollover.** Reuses Phase 4's `positioning.rollover_days` (3): near-month DTE ≤ 3 ⇒ the next month, labelled BASIS_ASSUMED_CONSTANT.
- **Sizing.** Lots = the most whose planned risk is ≤ `max_risk_per_trade_inr`, net of round-trip costs and exit slippage, with the fill re-walked at each size. If one lot is already over ⇒ RISK_PER_LOT_ABOVE_MAX, and the 1-lot numbers are shown.
- **Capital for options.** The candidate's `required_capital_inr` is premium × qty, as the selector spec says. The capital *checks*, in the selector and in risk_check, use the full premium + costs, as the risk spec says.
- **Shared limits.** Spread, spread vs move, volume / OI / visible depth and capital are one function (`limit_reasons`), used by the selector to exclude and by risk_check to reject. risk_check is the authority and re-runs it.
- **Unverified costs.** risk_check rejects with NET_RR_VERIFIED: a net R:R built on an unverified rate cannot pass the min-net-R:R check. This also does what the phase text says Phase 8's gate will do. Phase 8 itself is not built.
- **Daily loss latch.** `PortfolioState.worst_day_pnl_inr` is the lowest realized + unrealized seen today, tracked by the caller. A breach stays for the rest of the day even if P&L recovers. A new day means a new state.
- **Event days** are a config list (empty). Sourcing a calendar is Phase 8 (Q-RISK-3).
- **Liquidity score** = min(1, executable-side visible depth / (5 × qty)) × max(0, 1 − spread % / max spread %). Volume and OI thresholds are in lots: feed units ÷ lot size (F-QTY-1).
- **Report portfolio state** is flat (no positions, no P&L), because no paper ledger exists (Phase 11). The decisions are per setup, not a simulated day.
- **Tests first (guardrail 14): not followed to the letter.** I wrote `costs.py` / `contracts.py` / `risk.py` first and the 17 tests right after, then proved the tests bite with 6 mutations (§5). I say so here rather than claim otherwise.

## 2. Files

| File | Purpose |
|---|---|
| `engine/costs.py` | `round_trip`, `leg_costs` (versioned schedule, UNVERIFIED flag), `fill` (walk the book / ESTIMATED), `require` |
| `engine/contracts.py` | `TradeSetup`, `Quote`, `PremiumModel`, `Candidate` (no short options), `Selection`, `premium_model`, `quote_problem`, `limit_reasons`, `select_contracts`, `load` |
| `engine/risk.py` | `PortfolioState`, `Check`, `ApprovalToken`, `RiskDecision`, `Recommendation`, `risk_check` |
| `engine/contract_report.py` | edge CLI: recorded setups → selector → risk_check → markdown / JSON |
| `config/engine/v9.yaml` | v8 unchanged + `costs`, `contracts`, `risk` (sha256 `bd93ad66`) |
| `tests/engine_tests/test_contracts_risk.py` | 17 tests, synthetic fixtures |
| docs | verified-facts §13 (F-COST-1..6, F-MARGIN-1, F-QTY-1), open-questions (Q-COST-1..3, Q-RISK-1..4, Q-CON-1..4), architecture §14, this report, `phase-7-evidence/` |

No earlier module, interface or config changed. Outside the engine paths, `git diff --stat defa774` shows only Phase 1's `.gitignore`.
The Phase 0 *planned* `select_contract` / `size_position` signatures were never built. The phase text's shapes replace them (Q-CON-3, as in Phases 4 and 5).

## 3. Requirement status

| # | Requirement | Status | Proof |
|---|---|---|---|
| C1 | Reuse backtest-expert costs if correct, else build | DONE (built: backtest-expert is stale, F-COST-2/3) | `test_round_trip_matches_hand_computation_from_verified_rates` |
| C1a | Every charge a versioned config entry with effective-from + source URL in verified-facts; futures / options, buy / sell separate; no hardcoded rates | PARTIAL: all 7 components are entries with a fact ID and URL, but 5 have the read date as effective-from (no official date found, Q-COST-1) | `config/engine/v9.yaml`, verified-facts §13, `test_pure_modules_do_no_io_and_read_no_clock` |
| C1b | Unverified rate ⇒ cost estimate UNVERIFIED | DONE (also: no rate in force on the date) | `test_unverified_rate_or_no_rate_in_force_sets_unverified` |
| C2 | Slippage = half-spread + depth impact for the size; no depth ⇒ config multiple of spread, ESTIMATED | DONE | `test_slippage_walks_depth_or_is_estimated_without_depth` |
| S0 | Selector is a pure function of explicit inputs | DONE | `test_pure_modules_do_no_io_and_read_no_clock` (no clock / open / sqlite / requests); `quote_problem` refuses quotes after `as_of` |
| S1 | Futures: near month, next month in the rollover window | DONE | `test_strikes_expiries_and_rollover_come_from_the_registry` |
| S2 | Long call (bull) / long put (bear), ATM + 1 ITM, nearest expiry ≥ min DTE, next as alternative, strikes from the registry | DONE | same test (ITM put above ATM, tie ⇒ ITM, DTE 1 < 2 excluded) |
| S3 | Per candidate: lot, qty, executable entry, spread %, spread % of move to T1, top / depth qty, capital, stop / targets on contract, net R:R | DONE | `test_risk_measures_options_full_premium_futures_gap`; real tables §4 |
| S4 | Margin via Kite API if verified available, else MARGIN_ESTIMATED with a conservative config method | PARTIAL: API documented (F-MARGIN-1) but not wired (POST, banned class, Q-RISK-1); MARGIN_ESTIMATED and the MARGIN_API input path are both tested | `test_exclusions_are_named`, `test_missing_premium_model_…` (MARGIN_API) |
| S5 | Option premium at stop / target labelled; no defensible estimate ⇒ NO_TRADE NO_PREMIUM_MODEL; never invent a delta | DONE | `test_empirical_delta_recovered_and_rejected_when_not_defensible` (recovers 0.5; rejects too few bars, wrong sign, R² too low, bars after the decision) |
| S6 | Exclusions with reasons: illiquid, spread, spread vs move, data not OK, restricted, capital, expiry too close | DONE | `test_exclusions_are_named`, `test_wide_spread_option_excluded`, expiry: `test_strikes_…` |
| S7 | Rank by net R:R × liquidity, ties by lower capital; cheap premium never a factor | DONE | `test_ranking_is_net_rr_times_liquidity_never_cheap_premium` |
| S8 | Short options not supported (explicit test) | DONE | `test_no_short_option_candidate_is_ever_generated` |
| R0 | Single entry point `risk_check(candidate, portfolio_state, config)` → APPROVED / REJECTED with reasons | DONE | `engine/risk.py`; all Risk tests |
| R1 | Capital, risk per trade, daily loss, open positions, daily trades, consecutive losses + cooldown, spread, net R:R, slippage, option volume / depth, expiry / event day, cutoff, reserve, one position per underlying | DONE (event days from config only, Q-RISK-3) | `test_every_check_is_named`, `test_capital_above_limit_rejected`, `test_daily_loss_breach_…` |
| R2 | Long options: planned_risk sizes; full_premium_at_risk reported; capital check uses full premium | DONE | `test_risk_measures_…`, `test_capital_above_limit_rejected` (limit between premium and premium + costs ⇒ REJECTED) |
| R3 | Futures: planned_risk and gap risk (ATR multiple beyond the stop), both reported | DONE | `test_risk_measures_…` |
| R4 | Every check returns a named reason; config version recorded | DONE | `test_every_check_is_named` (+ CONFIG_VERSION check) |
| R5 | No recommendation without risk_check APPROVED (token only risk_check can create) | DONE (paper trades do not exist yet, Phase 11) | `test_recommendation_requires_an_approval_token_from_risk_check` |
| AT1 | Contract needing more capital than permitted ⇒ REJECTED | DONE | `test_capital_above_limit_rejected` |
| AT2 | Wide-spread option ⇒ excluded SPREAD_TOO_WIDE | DONE | `test_wide_spread_option_excluded` |
| AT3 | Daily loss limit breached ⇒ every later candidate REJECTED for the day | DONE (incl. after P&L recovers) | `test_daily_loss_breach_rejects_every_candidate_for_the_day` |
| AT4 | Missing premium model ⇒ option NO_TRADE, futures still evaluated | DONE | `test_missing_premium_model_option_no_trade_futures_still_evaluated` |
| AT5 | Cost model with an unverified rate ⇒ UNVERIFIED flag | DONE | `test_unverified_rate_or_no_rate_in_force_sets_unverified` |
| AT6 | Recommendation without approval token raises | DONE | `test_recommendation_requires_an_approval_token_from_risk_check` |
| AT7 | No short-option candidate ever generated | DONE | `test_no_short_option_candidate_is_ever_generated` |
| RPT | 10 recorded setups: full candidate table with exclusions and risk decision | DONE | §4; full columns and every risk reason: `phase-7-evidence/candidates-2026-11-06.md` / `.json` |

## 4. Real data: 10 recorded setups, 2026-11-06

`python3 -m engine.contract_report 2026-11-06 --report … --json …` (config v9 sha256 `bd93ad66`, ~80 s). A second run gave a byte-identical report.
Setups = Phase 6 (v8) first TIMELY evaluations, by rule: NIFTY's earliest, the earliest of each non-SWEEP family (ZONE; no BREAKOUT was ever TIMELY),
then the earliest of other underlyings, one each. Entry = the evaluation price, stop = structural stop, T1 = the obstacle, all on the near-month future.
Quotes = the latest recorded depth + tick row at or before the decision time (read-only). Spot = the latest spot tick. Margins: none. Portfolio: flat.
Prices INR, quantities units. Spread % = (ask − bid) / mid. "full prem / gap risk" = full premium at risk (options) or gap risk (futures).

| # | setup (decision IST) | dir | entry / stop / T1 (near fut) | contract | lots / qty | bid / ask | entry est. | spread % | capital (method) | planned risk | full prem / gap risk | costs stop / T1 | net R:R | liq. | selector | exclusions | risk | failed risk checks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | SOLARINDS SWEEP (11:54) | L | 17,900.00 / 17,882.00 / 18,046.37 | SOLARINDS26NOVFUT BUY | 1 / 25 | 17,895.00 / 17,920.00 | 17,920.00 | 0.140 | 448,000 (MARGIN_ESTIMATED) | 1,375 | 2,307 | 300 / 302 | 1.99 | 0.00 | EXCLUDED | SPREAD_TOO_WIDE (0.140 % > 0.05 %); CAPITAL_ABOVE_LIMIT (448,000 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, SPREAD_TOO_WIDE, MAX_SLIPPAGE |
| 2 | SOLARINDS SWEEP (11:54) | L | 17,900.00 / 17,882.00 / 18,046.37 | SOLARINDS26NOV18000CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 3 | SOLARINDS SWEEP (11:54) | L | 17,900.00 / 17,882.00 / 18,046.37 | SOLARINDS26NOV17750CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 4 | SOLARINDS SWEEP (11:54) | L | 17,900.00 / 17,882.00 / 18,046.37 | SOLARINDS26DEC18000CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 5 | SOLARINDS SWEEP (11:54) | L | 17,900.00 / 17,882.00 / 18,046.37 | SOLARINDS26DEC17750CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 6 | M&M SWEEP (11:57) | S | 3,237.50 / 3,242.00 / 3,227.50 | M&M26NOVFUT SELL | 1 / 200 | 3,235.20 / 3,238.30 | 3,235.20 | 0.096 | 647,040 (MARGIN_ESTIMATED) | 1,933 | 3,469 | 413 / 413 | 0.50 | 0.00 | EXCLUDED | SPREAD_TOO_WIDE (0.096 % > 0.05 %); SPREAD_VS_MOVE_TOO_WIDE (31.0 % of the move to T1 > 20 %); CAPITAL_ABOVE_LIMIT (647,040 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, SPREAD_TOO_WIDE, MIN_NET_RR |
| 7 | M&M SWEEP (11:57) | S | 3,237.50 / 3,242.00 / 3,227.50 | M&M26NOV3250PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 8 | M&M SWEEP (11:57) | S | 3,237.50 / 3,242.00 / 3,227.50 | M&M26NOV3300PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 9 | M&M SWEEP (11:57) | S | 3,237.50 / 3,242.00 / 3,227.50 | M&M26DEC3250PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 10 | M&M SWEEP (11:57) | S | 3,237.50 / 3,242.00 / 3,227.50 | M&M26DEC3300PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 11 | BSE SWEEP (11:58) | L | 3,761.30 / 3,758.00 / 3,787.30 | BSE26NOVFUT BUY | 1 / 200 | 3,761.40 / 3,762.80 | 3,762.80 | 0.037 | 752,560 (MARGIN_ESTIMATED) | 1,412 | 2,549 | 472 / 475 | 3.15 | 0.26 | EXCLUDED | CAPITAL_ABOVE_LIMIT (752,560 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE |
| 12 | BSE SWEEP (11:58) | L | 3,761.30 / 3,758.00 / 3,787.30 | BSE26NOV3750CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 13 | BSE SWEEP (11:58) | L | 3,761.30 / 3,758.00 / 3,787.30 | BSE26NOV3700CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 14 | BSE SWEEP (11:58) | L | 3,761.30 / 3,758.00 / 3,787.30 | BSE26DEC3750CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 15 | BSE SWEEP (11:58) | L | 3,761.30 / 3,758.00 / 3,787.30 | BSE26DEC3700CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 16 | ULTRACEMCO SWEEP (12:00) | S | 12,175.00 / 12,180.00 / 12,040.00 | ULTRACEMCO26NOVFUT SELL | 1 / 50 | 12,175.00 / 12,181.00 | 12,175.00 | 0.049 | 608,750 (MARGIN_ESTIMATED) | 942 | 1,688 | 392 / 391 | 6.44 | 0.01 | EXCLUDED | CAPITAL_ABOVE_LIMIT (608,750 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE |
| 17 | ULTRACEMCO SWEEP (12:00) | S | 12,175.00 / 12,180.00 / 12,040.00 | ULTRACEMCO26NOV12200PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 18 | ULTRACEMCO SWEEP (12:00) | S | 12,175.00 / 12,180.00 / 12,040.00 | ULTRACEMCO26NOV12300PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 19 | ULTRACEMCO SWEEP (12:00) | S | 12,175.00 / 12,180.00 / 12,040.00 | ULTRACEMCO26DEC12200PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 20 | ULTRACEMCO SWEEP (12:00) | S | 12,175.00 / 12,180.00 / 12,040.00 | ULTRACEMCO26DEC12300PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 21 | TRENT SWEEP (12:02) | S | 3,052.30 / 3,057.30 / 3,038.95 | TRENT26NOVFUT SELL | 1 / 225 | 3,050.00 / 3,051.40 | 3,050.00 | 0.046 | 686,250 (MARGIN_ESTIMATED) | 1,875 | 2,777 | 435 / 435 | 1.20 | 0.08 | EXCLUDED | CAPITAL_ABOVE_LIMIT (686,250 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MIN_NET_RR |
| 22 | TRENT SWEEP (12:02) | S | 3,052.30 / 3,057.30 / 3,038.95 | TRENT26NOV3050PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 23 | TRENT SWEEP (12:02) | S | 3,052.30 / 3,057.30 / 3,038.95 | TRENT26NOV3100PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 24 | TRENT SWEEP (12:02) | S | 3,052.30 / 3,057.30 / 3,038.95 | TRENT26DEC3050PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 25 | TRENT SWEEP (12:02) | S | 3,052.30 / 3,057.30 / 3,038.95 | TRENT26DEC3100PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 26 | SBIN SWEEP (12:03) | S | 999.35 / 1,000.00 / 991.00 | SBIN26NOVFUT SELL | 1 / 750 | 999.40 / 1,000.15 | 999.40 | 0.075 | 749,550 (MARGIN_ESTIMATED) | 1,521 | 2,322 | 471 / 471 | 3.44 | 0.00 | EXCLUDED | SPREAD_TOO_WIDE (0.075 % > 0.05 %); CAPITAL_ABOVE_LIMIT (749,550 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, SPREAD_TOO_WIDE |
| 27 | SBIN SWEEP (12:03) | S | 999.35 / 1,000.00 / 991.00 | SBIN26NOV1000PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 28 | SBIN SWEEP (12:03) | S | 999.35 / 1,000.00 / 991.00 | SBIN26NOV1010PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 29 | SBIN SWEEP (12:03) | S | 999.35 / 1,000.00 / 991.00 | SBIN26DEC1000PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 30 | SBIN SWEEP (12:03) | S | 999.35 / 1,000.00 / 991.00 | SBIN26DEC1010PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 31 | BAJAJFINSV SWEEP (12:03) | L | 1,833.50 / 1,833.30 / 1,838.50 | BAJAJFINSV26NOVFUT BUY | 2 / 600 | 1,833.50 / 1,833.70 | 1,834.25 | 0.011 | 1,100,550 (MARGIN_ESTIMATED) | 1,389 | 2,911 | 669 / 671 | 1.24 | 0.39 | EXCLUDED | CAPITAL_ABOVE_LIMIT (1,100,550 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MIN_NET_RR |
| 32 | BAJAJFINSV SWEEP (12:03) | L | 1,833.50 / 1,833.30 / 1,838.50 | BAJAJFINSV26NOV1820CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 33 | BAJAJFINSV SWEEP (12:03) | L | 1,833.50 / 1,833.30 / 1,838.50 | BAJAJFINSV26NOV1800CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 34 | BAJAJFINSV SWEEP (12:03) | L | 1,833.50 / 1,833.30 / 1,838.50 | BAJAJFINSV26DEC1820CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 35 | BAJAJFINSV SWEEP (12:03) | L | 1,833.50 / 1,833.30 / 1,838.50 | BAJAJFINSV26DEC1800CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 36 | TMPV SWEEP (12:03) | L | 287.25 / 287.00 / 287.95 | TMPV26NOVFUT BUY | 2 / 3200 | 287.35 / 287.45 | 287.45 | 0.035 | 919,840 (MARGIN_ESTIMATED) | 1,687 | 3,150 | 567 / 568 | 0.80 | 0.30 | EXCLUDED | CAPITAL_ABOVE_LIMIT (919,840 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MIN_NET_RR |
| 37 | TMPV SWEEP (12:03) | L | 287.25 / 287.00 / 287.95 | TMPV26NOV285CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 38 | TMPV SWEEP (12:03) | L | 287.25 / 287.00 / 287.95 | TMPV26NOV280CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 39 | TMPV SWEEP (12:03) | L | 287.25 / 287.00 / 287.95 | TMPV26DEC285CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 40 | TMPV SWEEP (12:03) | L | 287.25 / 287.00 / 287.95 | TMPV26DEC280CE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 41 | POLYCAB ZONE (12:11) | S | 7,681.00 / 7,688.00 / 7,669.50 | POLYCAB26NOVFUT SELL | 1 / 125 | 7,680.50 / 7,686.50 | 7,680.50 | 0.078 | 960,062 (MARGIN_ESTIMATED) | 2,215 | 3,358 | 590 / 590 | 0.04 | 0.00 | EXCLUDED | RISK_PER_LOT_ABOVE_MAX (2,215 > 2,000 INR for one lot); SPREAD_TOO_WIDE (0.078 % > 0.05 %); SPREAD_VS_MOVE_TOO_WIDE (52.2 % of the move to T1 > 20 %); CAPITAL_ABOVE_LIMIT (960,062 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR |
| 42 | POLYCAB ZONE (12:11) | S | 7,681.00 / 7,688.00 / 7,669.50 | POLYCAB26NOV7700PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 43 | POLYCAB ZONE (12:11) | S | 7,681.00 / 7,688.00 / 7,669.50 | POLYCAB26NOV7800PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 44 | POLYCAB ZONE (12:11) | S | 7,681.00 / 7,688.00 / 7,669.50 | POLYCAB26DEC7700PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 45 | POLYCAB ZONE (12:11) | S | 7,681.00 / 7,688.00 / 7,669.50 | POLYCAB26DEC7800PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 46 | NIFTY SWEEP (14:30) | S | 24,888.60 / 24,897.90 / 24,869.00 | NIFTY26NOVFUT SELL | 1 / 65 | 24,888.00 / 24,891.00 | 24,888.00 | 0.012 | 1,617,720 (MARGIN_ESTIMATED) | 1,762 | 3,908 | 962 / 962 | 0.07 | 0.76 | EXCLUDED | CAPITAL_ABOVE_LIMIT (1,617,720 > 100,000 INR) | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MIN_NET_RR |
| 47 | NIFTY SWEEP (14:30) | S | 24,888.60 / 24,897.90 / 24,869.00 | NIFTY26N0924850PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 48 | NIFTY SWEEP (14:30) | S | 24,888.60 / 24,897.90 / 24,869.00 | NIFTY26N0924900PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 49 | NIFTY SWEEP (14:30) | S | 24,888.60 / 24,897.90 / 24,869.00 | NIFTY26N1724850PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |
| 50 | NIFTY SWEEP (14:30) | S | 24,888.60 / 24,897.90 / 24,869.00 | NIFTY26N1724900PE BUY | — | — | — | — | — | — | — | — | — | — | NO_TRADE | NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE | REJECTED | CANDIDATE_ELIGIBLE, CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE, MAX_RISK_PER_TRADE, SPREAD_TOO_WIDE, MIN_NET_RR, NET_RR_VERIFIED, MAX_SLIPPAGE, MIN_LIQUIDITY |

| product | selector status | risk decision | candidates |
|---|---|---|---|
| FUT | EXCLUDED | REJECTED | 10 |
| OPT | NO_TRADE | REJECTED | 40 |

Reading it:
- **Futures (10).** All are EXCLUDED for CAPITAL_ABOVE_LIMIT (MARGIN_ESTIMATED full notional, ₹4.5 L–₹16.2 L > ₹1 L). Four are also SPREAD_TOO_WIDE (SOLARINDS 0.14 %, M&M 0.10 %, SBIN 0.075 %, POLYCAB 0.078 % > 0.05 %); two are SPREAD_VS_MOVE_TOO_WIDE (M&M 31 %, POLYCAB 52 % of the move to T1); POLYCAB is also RISK_PER_LOT_ABOVE_MAX (one lot = ₹2,215).
  Net R:R where computed: ULTRACEMCO 6.44, SBIN 3.44, BSE 3.15, SOLARINDS 1.99, BAJAJFINSV 1.24, TRENT 1.20, TMPV 0.80, M&M 0.50, NIFTY 0.07, POLYCAB 0.04.
  Four clear 1.5 net: ULTRACEMCO, SBIN, BSE, SOLARINDS. SBIN and SOLARINDS fail the spread. **BSE and ULTRACEMCO are rejected only on capital**
  (CAPITAL_ABOVE_LIMIT, CAPITAL_RESERVE): with a margin quote ≤ ₹1 L for ₹7.5 L / ₹6.1 L notional they would pass every other check under the proposed limits.
- **BAJAJFINSV** shows depth impact: 2 lots (600) are more than the 300 at the touch, so the walked entry is 1,834.25 against an ask of 1,833.70.
- **Options (40).** All NO_TRADE: `NO_PREMIUM_MODEL: 0 contiguous paired 1m bars < 20; DATA_NOT_OK:NO_QUOTE`. "Option tick rows recorded" is 0 for every underlying. The strikes are real registry rows (NIFTY ATM 24,850 / ITM 24,900 PE on the 2026-11-09 and 2026-11-17 expiries).
- risk_check names every failed check. For the NO_TRADE options that includes the checks with nothing to check ("capital None …"): missing never passes.
- This is one partial session. It says nothing about any edge.

## 5. Mutation checks (`phase-7-evidence/mutation-checks.txt`)

Each guard broken in turn; the suite must fail, then the original is restored:
```
MUTATION short-option guard removed: exit=1 -> 1 failing
    FAIL: test_no_short_option_candidate_is_ever_generated (tests.engine_tests.test_contracts_risk.Selector.test_no_short_option_candidate_is_ever_generated)
MUTATION daily-loss latch removed (current P&L only): exit=1 -> 1 failing
    FAIL: test_daily_loss_breach_rejects_every_candidate_for_the_day (tests.engine_tests.test_contracts_risk.Risk.test_daily_loss_breach_rejects_every_candidate_for_the_day)
MUTATION approval token mint check removed: exit=1 -> 1 failing
    FAIL: test_recommendation_requires_an_approval_token_from_risk_check (tests.engine_tests.test_contracts_risk.Risk.test_recommendation_requires_an_approval_token_from_risk_check)
MUTATION spread exclusion removed from selector: exit=1 -> 1 failing
    FAIL: test_wide_spread_option_excluded (tests.engine_tests.test_contracts_risk.Selector.test_wide_spread_option_excluded)
MUTATION unverified flag ignored: exit=1 -> 1 failing
    FAIL: test_unverified_rate_or_no_rate_in_force_sets_unverified (tests.engine_tests.test_contracts_risk.CostModel.test_unverified_rate_or_no_rate_in_force_sets_unverified)
MUTATION option capital check on premium x qty only: exit=1 -> 1 failing
    FAIL: test_capital_above_limit_rejected (tests.engine_tests.test_contracts_risk.Risk.test_capital_above_limit_rejected)
restored: OK
```

## 6. Facts used

New, with URLs (verified-facts §13): F-COST-1..6 (zerodha.com/charges, STT bulletin 445377, Zerodha support page), F-MARGIN-1 (kite.trade/docs/connect/v3/margins/, kiteconnect `connect.py` 166, 168, 824–850; not called), F-QTY-1 (measured).
Existing: F-QUOTE-5/7 and F-WS-5 (pending quantities, 5-level depth is not a full book), F-WS-9 (paise), F-INST-1..3 (lots, expiries and strikes from the master via the Phase 2 registry).
**No kiteconnect method is called in Phase 7.** The pure modules make no I/O; the report reads only local SQLite files, read-only.

## 7. Open questions

Q-COST-1 (official effective dates), Q-COST-2 (SEBI ₹15 / crore note), Q-COST-3 (virtual contract note to check costs),
**Q-RISK-1 (margin API: add a POST; blocks futures)**, **Q-RISK-2 (every risk / contract value is PROPOSED)**, Q-RISK-3 (event calendar → Phase 8),
Q-RISK-4 (portfolio state source → Phase 11), **Q-CON-1 (record options in tier C; blocks options)**, Q-CON-2 (option quantity units),
Q-CON-3 (replace the Phase 0 planned signatures), Q-CON-4 (gross R:R in Phase 6 vs net here). Still open from earlier phases: Q-EOD-1, Q-OPP-3 (now partly answered: a cost model exists), Q-NSE-3 (answered by F-COST-*; the two old schedules are stale).

## 8. Limitations

- No option has been recorded, so the option path (premium model, option depth, option ranking) is proven only on fixtures.
- Futures capital is a full-notional estimate until a margin quote is wired.
- Exit slippage uses the decision-time book. The book at the stop is unknown and is usually worse in a fast move. Gap risk covers part of that for futures only.
- The futures basis is assumed constant for a month other than the setup instrument. The option model is linear (APPROXIMATE).
- Brokerage assumes one executed order per leg (partial fills of one order are one order; several orders are not modelled). Contract-note rounding is not modelled.
- `risk.event_days` is empty, so EVENT_DAY blocks nothing yet. Holidays and bans come in through the registry (RESTRICTED).
- Batch report only; nothing runs live (as in Phases 4–6).

## 9. Raw test output

### 9.1 `python3 -m unittest discover -s tests/engine_tests -t . -v` (full file: phase-7-evidence/engine-tests.txt; Phase 7 lines, module paths trimmed, then the tail. The ResourceWarning is an earlier test's unclosed SQLite connection collected during YAML parsing, as in Phase 6's output; the test is `ok`)
```
test_pure_modules_do_no_io_and_read_no_clock ... ok
test_v9_loads_and_missing_key_fails ... /Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages/yaml/scanner.py:286: ResourceWarning: unclosed database in <sqlite3.Connection object at 0x10b6733d0>
  for level in list(self.possible_simple_keys):
ResourceWarning: Enable tracemalloc to get the object allocation traceback
ok
test_round_trip_matches_hand_computation_from_verified_rates ... ok
test_slippage_walks_depth_or_is_estimated_without_depth ... ok
test_unverified_rate_or_no_rate_in_force_sets_unverified ... ok
test_empirical_delta_recovered_and_rejected_when_not_defensible ... ok
test_capital_above_limit_rejected ... ok
test_daily_loss_breach_rejects_every_candidate_for_the_day ... ok
test_every_check_is_named ... ok
test_recommendation_requires_an_approval_token_from_risk_check ... ok
test_exclusions_are_named ... ok
test_missing_premium_model_option_no_trade_futures_still_evaluated ... ok
test_no_short_option_candidate_is_ever_generated ... ok
test_ranking_is_net_rr_times_liquidity_never_cheap_premium ... ok
test_risk_measures_options_full_premium_futures_gap ... ok
test_strikes_expiries_and_rollover_come_from_the_registry ... ok
test_wide_spread_option_excluded ... ok
Ran 136 tests in 36.713s
OK
exit=0
```

### 9.2 Whole repo `python3 -m unittest discover -s tests -v` (phase-7-evidence/full-suite.txt)
```
test_engine_never_uses_kiteconnect_rest_class (engine_tests.test_edges.TestNoOrderCode.test_engine_never_uses_kiteconnect_rest_class) ... ok
test_no_order_methods_in_repo_code (engine_tests.test_edges.TestNoOrderCode.test_no_order_methods_in_repo_code) ... ok
test_grep_logic_modules (engine_tests.test_universe.TestNoHardcodedContractFacts.test_grep_logic_modules) ... ok
Ran 199 tests in 37.040s
OK
exit=0
```
