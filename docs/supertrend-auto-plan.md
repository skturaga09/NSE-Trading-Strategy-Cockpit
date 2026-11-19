# Supertrend automatic orders — plan and status (updated 2026-11-13)

**Goal (owner's original ask):** Supertrend signals turn into Zerodha orders automatically.
**Rule from here:** the strategy rules are frozen until paper trading has data. Work goes into the order pipeline.

## Status

| Stage | What | Status |
|---|---|---|
| 0 | Talk to Zerodha | Done. Login works (account QIA511, NFO enabled). Kite traffic pinned to IPv4 so it leaves from the whitelisted 106.51.226.2 (`KITE` session, `dashboard/supertrend_trades.py`). Whitelist for *orders* not yet proven: the first real order is the proof. |
| 1 | Live paper trading | Built. Starts Mon 16 Nov 09:15. `dashboard/supertrend_paper.py`, panel on the Supertrend tab. ₹1,00,000, 1 lot per signal, plus a candle-close shadow book. From 19 Nov a second ₹1,00,000 **strong-candle book** buys only flips whose candle body is ≥ 1.9× ATR(14) (replay 28 Oct–17 Nov: better in both halves); live rules unchanged until paper shows it. |
| 2 | Automatic **exits** | Built, switched **OFF**. `dashboard/supertrend_auto.py`, "Auto exits" panel. Owner switches it on after watching the dry-run log. |
| 3 | Automatic **entries** | Built 2026-11-16, switched **OFF** (owner asked to go live 17 Nov, after 1 paper day instead of the planned 10). `supertrend_auto.enter()`, "Auto entries" switch in the Auto exits panel. 1 lot per TAKE, LIMIT at the ask, tag `STREND`, cancelled if unfilled in 5 min, one pending buy at a time, needs auto exits ON too, a failed send switches it off. |

## The rules all stages share (frozen)

`dashboard/supertrend_trades.view()` decides; paper, tickets and auto exits all call it.

- **Entry:** 5-minute Supertrend(10,3) flip on the stock, candle closed before 14:00, 15-minute trend agreeing, signal ≤ 15 min old. UP → 1-strike-OTM CE, DOWN → 1-strike-OTM PE (owner changed from 1-strike ITM on 17 Nov, without a backtest; the 10-week test and the 25 % premium stop were measured on ITM), nearest expiry after today, product NRML.
- **Buy price:** best ask from Kite depth (D-79). Skip if no seller, bid-ask gap > 3 %, or < 1 lot offered at the ask.
- **Size:** paper 1 lot per signal (D-80). Tickets: as many lots as fit cash and the day budget (D-78).
- **Day loss budget:** balance − 90 % of the morning balance − 30 % of what open options cost (D-78). Max 4 open, 20 filled orders a day counting buys and sells, cancelled/rejected not counted (owner 18 Nov; was 7 buys, 5 before 17 Nov). A buy is skipped unless it, its sell and the sell still due on every held option fit in the 20, one position per stock; paper also stops after 2 losses in a row.
- **Exit (first that applies):** option 25 % below its highest price since the buy (trailing premium stop, D-81) · 5-minute trend turned against the position · stock touches the Supertrend line · 15:15 with 5m and 15m not both agreeing (else hold overnight) · expiry day from 15:00.

## Stage 2 — automatic exits (built)

Runs inside the existing per-minute job (`com.clade.supertrend` → `POST /api/supertrend/check`), market hours only.

| Guard | How |
|---|---|
| Which positions | Only options bought with the Supertrend "Buy in Kite" button: Kite order tag `STREND` (Publisher tag ≤ 8 chars, F-ORD-2). Remembered across nights in `data/engine/supertrend_auto_positions.json`. Any other held option only if you hand it over with the **Auto-manage** button (and take it back the same way); a two-leg GTT you placed is never modified, only deleted right before an auto sell. Anything else is never touched. |
| Switch | `data/engine/supertrend_auto.json`, default off. Off = writes "WOULD SELL / WOULD PLACE STOP-LOSS" to `data/engine/supertrend_auto_log.jsonl`, sends nothing. The switch endpoint refuses browser requests from any site but the dashboard. |
| Sell | Delete every active SELL GTT on the option (yours too) and cancel any pending stop-loss order first, then LIMIT SELL of the whole position at the best bid, tag `STRENDX`. If the cancel fails: no sell (a leftover stop-loss could sell short later), phone alert. |
| No duplicates | Order book read before every send; a live SELL for the option = already selling. A failed or timed-out send is not repeated for 3 minutes (it may have reached Kite). |
| Unfilled sell | Re-priced to the new bid after 60 s, at most 3 times, then a phone alert to sell by hand. |
| Holding | Keeps a single-leg GTT SELL in Zerodha (trigger 25 % under the high since the buy, LIMIT 5 % under the trigger). It lives until the contract expires, so it covers overnight and a sleeping Mac. Trigger raised as the high rises (steps >= 2 %), never lowered, never set where it fires at once (D-81). |
| Blank Kite read | No action, nothing forgotten. |
| Alerts | Every order sent, failed or stuck goes to the phone. |

Tests: `tests/test_supertrend_auto.py` (simulated Kite). Live dry run 2026-11-13 read 13 real orders, sent nothing.

### Before switching stage 2 on
1. Buy at least one option through the "Buy in Kite" button and confirm it shows under "Managing" with tag `STREND`.
2. Watch the dry-run log for a few sessions: each WOULD SELL should match what you would have done.
3. Mac on the charger in market hours (`com.clade.market-awake` keeps it awake only on AC).

## Stage 3 — automatic entries (next)
Same guards, plus: POST the BUY that `view()` marks TAKE (LIMIT at the ask, tag `STREND`), cancel it if unfilled after 5 minutes, place the stop-loss only after the fill shows in positions, kill switch on Kite errors or outside 09:15–15:30. Starts only after ≥ 10 trading days of paper data.

## Open risks
- **Capital vs the rules:** the 10-week backtest (2 Sep–12 Nov) lost money at ₹1,00,000 (≈ 1 open trade at a time under the day budget) and made money at ₹2,00,000 with 1 lot. The profit came from overnight holds; same-day trades lost.
- **Fills:** a LIMIT at the bid / ask can still miss in a fast market; paper sells assume last price − 1 %.
- **Overnight gaps** can jump past the 25 % stop-loss.
- **SEBI retail-algo rules** (static IP done; order-rate thresholds, algo registration) — re-read Zerodha's current notice before stage 3.
