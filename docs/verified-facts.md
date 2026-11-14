# Verified facts — single source of truth for external facts

Rule: code may rely on an external fact only if it is listed here with a source, or was
**measured** from this account's own data (evidence file linked). Anything else lives in
[open-questions.md](open-questions.md) and must be a config parameter with **no default**.

Each entry: ID · fact · source (URL or evidence file) · accessed/measured · short quote.
"DOC" = official documentation. "MEASURED" = observed on this account (read-only calls).

Evidence files: [phase-0-evidence/measured-kite.txt](phase-0-evidence/measured-kite.txt)
(run 2026-11-05 19:51–19:52 IST, market closed, read-only `/instruments`, `/quote`, `/instruments/historical`).

---

## 1. Authentication and session

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-AUTH-1 | API root is `https://api.kite.trade` | DOC https://kite.trade/docs/connect/v3/user/ | 2026-11-05 | "https://api.kite.trade" |
| F-AUTH-2 | Requests are signed with header `Authorization: token api_key:access_token` and `X-Kite-Version: 3` | DOC https://kite.trade/docs/connect/v3/user/ | 2026-11-05 | "Authorization: token api_key:access_token" |
| F-AUTH-3 | Login flow: login page with api_key → `request_token` to redirect URL → POST `request_token` + checksum to `/session/token` → `access_token` | DOC https://kite.trade/docs/connect/v3/user/ | 2026-11-05 | "POST the request_token and checksum … to /session/token" |
| F-AUTH-4 | Checksum = SHA-256 of `api_key + request_token + api_secret` | DOC https://kite.trade/docs/connect/v3/user/ | 2026-11-05 | "SHA-256 hash of (api_key + request_token + api_secret)" |
| F-AUTH-5 | `request_token` lives only a few minutes and is single-use | DOC https://kite.trade/docs/connect/v3/user/ | 2026-11-05 | "This token's lifetime is only a few minutes" |
| F-AUTH-6 | `access_token` expires at 06:00 the next day unless invalidated earlier (API logout or master logout from Kite Web) | DOC https://kite.trade/docs/connect/v3/user/ | 2026-11-05 | "it'll expire at 6 AM on the next day (regulatory requirement)" |
| F-AUTH-7 | An expired/invalidated session returns HTTP 403 with `TokenException`; the app should clear the session and log in again | DOC https://kite.trade/docs/connect/v3/exceptions/ | 2026-11-05 | "Preceded by a 403 header, this indicates the expiry or invalidation of an authenticated session" |
| F-AUTH-8 | On this account an expired token returns `TokenException: Incorrect \`api_key\` or \`access_token\`.` | MEASURED `dashboard/logs/kite_refresh.log` + live probe 2026-11-05 11:55 IST | 2026-11-05 | "Incorrect `api_key` or `access_token`." |

Note: `dashboard/scripts/refresh_kite_token.py` docstring says the token expires "~7:30 AM"; the official
doc (F-AUTH-6) says 06:00 next day. The doc wins; the docstring is a protected asset and was not edited.

## 2. Rate limits

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-RATE-1 | Quote endpoint: 1 request/second | DOC https://kite.trade/docs/connect/v3/exceptions/ | 2026-11-05 | "Quote" — "1req/second" |
| F-RATE-2 | Historical candle endpoint: 3 requests/second | DOC https://kite.trade/docs/connect/v3/exceptions/ | 2026-11-05 | "Historical candle" — "3req/second" |
| F-RATE-3 | All other endpoints: 10 requests/second | DOC https://kite.trade/docs/connect/v3/exceptions/ | 2026-11-05 | "All other endpoints" — "10req/second" |
| F-RATE-4 | (Context only — no order code will exist) order placement 10 req/s, 400 orders/min, 5000 orders/day per user/API key | DOC https://kite.trade/docs/connect/v3/exceptions/ | 2026-11-05 | "400 orders per minute and 10 orders per second" |

The docs list per-second limits only; no per-minute/per-day limits for data endpoints are stated.

## 3. Market quotes (REST)

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-QUOTE-1 | `/quote` returns the full snapshot for up to 500 instruments per request | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "complete market data snapshot of up to 500 instruments in one go" |
| F-QUOTE-2 | `/quote/ohlc` up to 1000 instruments; `/quote/ltp` up to 1000 instruments | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "OHLC + LTP snapshots of up to 1000 instruments"; "LTPs of up to 1000 instruments" |
| F-QUOTE-3 | `/quote` documented fields: `instrument_token, timestamp, last_trade_time, last_price, volume, average_price, buy_quantity, sell_quantity, last_quantity, ohlc{open,high,low,close}, net_change, lower_circuit_limit, upper_circuit_limit, oi, oi_day_high, oi_day_low, depth.buy[]/depth.sell[] {price, orders, quantity}` | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | field table |
| F-QUOTE-4 | `timestamp` = exchange timestamp of the quote packet; `last_trade_time` = last trade timestamp | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "The exchange timestamp of the quote packet" |
| F-QUOTE-5 | `buy_quantity` / `sell_quantity` are **pending** order quantities, not traded volume | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "Total quantity of buy orders pending at the exchange" |
| F-QUOTE-6 | `average_price` is the day VWAP | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "The volume weighted average price of a stock at a given time during the day" |
| F-QUOTE-7 | `depth` quantity is net quantity of **pending** orders at that price | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "Net quantity from the pending orders" |
| F-QUOTE-8 | Futures and options quotes return 5 buy + 5 sell depth levels | MEASURED measured-kite.txt (NIFTY26NOVFUT, NIFTY26N0924400CE) | 2026-11-05 | `depth levels: {'buy': 5, 'sell': 5}` |
| F-QUOTE-9 | Index quote (`NSE:NIFTY 50`) has only `indicative_close_price, instrument_token, last_price, net_change, ohlc, timestamp, tradingsymbol` — **no** `last_trade_time`, volume, OI or depth | MEASURED measured-kite.txt | 2026-11-05 | `keys=['indicative_close_price', … 'tradingsymbol']` |
| F-QUOTE-10 | F&O quotes also return undocumented keys: `high_limit_price_protection, low_limit_price_protection, reference_limit_price, total_imbalance_qty, indicative_close_price` (meaning not documented — do not use without verification) | MEASURED measured-kite.txt | 2026-11-05 | key list |

## 4. Instrument master

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-INST-1 | `GET /instruments` (all) or `/instruments/:exchange` returns a gzipped CSV | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "returns a gzipped CSV dump of instruments across all exchanges" |
| F-INST-2 | Columns: `instrument_token, exchange_token, tradingsymbol, name, last_price, expiry, strike, tick_size, lot_size, instrument_type, segment, exchange` | DOC https://kite.trade/docs/connect/v3/market-quotes/; MEASURED `/instruments/NFO` columns identical | 2026-11-05 | column list |
| F-INST-3 | The dump is generated once a day; `last_price` in it is not real-time; recommended fetch once a day (~08:30) | DOC https://kite.trade/docs/connect/v3/market-quotes/ | 2026-11-05 | "The dump is generated once everyday and hence last_price is not real time" |

Lot sizes, expiries, strikes and tokens therefore come from this dump, fetched daily — never hardcoded.

## 5. WebSocket (KiteTicker)

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-WS-1 | URL `wss://ws.kite.trade` with query params `api_key` and `access_token` | DOC https://kite.trade/docs/connect/v3/websocket/ | 2026-11-05 | "wss://ws.kite.trade" |
| F-WS-2 | Up to 3000 instruments per connection; up to 3 connections per API key | DOC https://kite.trade/docs/connect/v3/websocket/ | 2026-11-05 | "up to 3000 instruments on a single WebSocket connection"; "Single API key can have upto 3 websocket connections." |
| F-WS-3 | Modes: `ltp` (8 bytes, LTP only), `quote` (44 bytes, no depth), `full` (184 bytes, with depth) | DOC https://kite.trade/docs/connect/v3/websocket/ | 2026-11-05 | "Packet contains several fields including market depth (184 bytes)" |
| F-WS-4 | `quote` packet: token, LTP, last traded qty, average traded price, volume, total buy qty, total sell qty, open, high, low, close (bytes 0–44) | DOC https://kite.trade/docs/connect/v3/websocket/ | 2026-11-05 | byte table |
| F-WS-5 | `full` adds: last traded timestamp (44–48), OI (48–52), OI day high (52–56), OI day low (56–60), exchange timestamp (60–64), depth 5 bids (64–124) + 5 offers (124–184), 12 bytes per entry incl. 2 padding | DOC https://kite.trade/docs/connect/v3/websocket/ | 2026-11-05 | byte table |
| F-WS-6 | **OI, OI day high/low and exchange timestamp are only in `full` mode** (not in `quote`) | DOC https://kite.trade/docs/connect/v3/websocket/ (follows from F-WS-4/5) | 2026-11-05 | — |
| F-WS-7 | Index packets: token, LTP, high, low, open, close, price change (quote, 28 bytes); `full` adds exchange timestamp (28–32). No volume, OI, depth | DOC https://kite.trade/docs/connect/v3/websocket/ | 2026-11-05 | "have fewer fields" |

Not yet measured on this account (no subscription made in Phase 0): see open questions Q-WS-*.

## 6. Historical candles

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-HIST-1 | Intervals: `minute, day, 3minute, 5minute, 10minute, 15minute, 30minute, 60minute` | DOC https://kite.trade/docs/connect/v3/historical/ | 2026-11-05 | interval list |
| F-HIST-2 | Record = `[timestamp, open, high, low, close, volume]`; with `oi=1` a 7th value (OI) is appended | DOC https://kite.trade/docs/connect/v3/historical/ (format + OI example) | 2026-11-05 | "[timestamp, open, high, low, close, volume]" |
| F-HIST-3 | `oi=1` returns OI for NFO futures **and options** on `minute`, `5minute`, `day` | MEASURED measured-kite.txt (NIFTY26NOVFUT, NIFTY26N0924400CE) | 2026-11-05 | 7-element candles |
| F-HIST-4 | `continuous=1` works for NFO and MCX futures, `day` candles only, stitching expired contracts | DOC https://kite.trade/docs/connect/v3/historical/ | 2026-11-05 | "works for NFO and MCX futures contracts" |
| F-HIST-5 | Max range per request (from Kite's own error message): `minute` 60 days; `3minute` 100; `5minute` 100; `60minute` 400; `day` 2000. `15minute` accepted 188 days (exact cap not reached) | MEASURED measured-kite.txt: `InputException: interval exceeds max limit: 60 days` / `100 days` / `400 days` / `2000 days` | 2026-11-05 | error text |
| F-HIST-6 | Continuous daily futures with OI: NIFTY from 2016 (OI = 0 in early 2016 rows), RELIANCE back to 2021; a name only from its F&O inclusion (POLICYBZR from 2024-11-29) | MEASURED measured-kite.txt | 2026-11-05 | candle counts |
| F-HIST-7 | Intraday history for a live contract starts at that contract's listing (NIFTY26NOVFUT: 2026-08-26); there is no intraday continuous series | MEASURED measured-kite.txt; DOC F-HIST-4 (day only) | 2026-11-05 | first candle 2026-08-26 |
| F-HIST-8 | In `minute` candles, futures OI changes almost every minute (NIFTY fut: 369/375 minutes; RELIANCE fut: 348/375; max gap 3 min on 2026-11-05) | MEASURED measured-kite.txt (third batch) | 2026-11-05 | cadence counts |
| F-HIST-11 | Historical `minute` volume is the same quantity, in the same units, as tick-delta 1m candle volume. Futures (exchange-time buckets): 26,070 / 26,133 COMPLETE+OK minutes exactly equal, day-sum ratio 1.0000. Spot (quote mode, receive-time buckets): 79.5 % exact, day-sum ratio 1.0005, boundary prints shift to the next minute (PFC 11:35 block: 287,469 vs 11,380). One session, 2026-11-06 11:26–15:30, 384 tokens | MEASURED docs/q-3-4-evidence/ (`q34_measure.py`, `measurement.txt`) | 2026-11-07 | `NFO-FUT: minutes=26133 … exact_equal=26070 (99.8%)` |

## 7. Account capability (this account)

| ID | Fact | Source | Measured |
|---|---|---|---|
| F-ACCT-1 | REST `/quote`, `/instruments`, `/instruments/historical` (incl. `oi=1`, `continuous=1`) all succeed on this API key | MEASURED measured-kite.txt | 2026-11-05 |
| F-ORD-1 | Regular orders: place `POST /orders/regular` -> `{"status":"success","data":{"order_id":…}}`; modify `PUT /orders/regular/:order_id` (order_type, quantity, price, trigger_price, disclosed_quantity, validity); cancel `DELETE /orders/regular/:order_id` | DOC https://kite.trade/docs/connect/v3/orders/ | 2026-11-13 | endpoint table, "the API returns an order_id" |
| F-ORD-2 | Order `tag`: alphanumeric, max 20 chars (REST); max **8** chars in a Kite Publisher basket | DOC https://kite.trade/docs/connect/v3/orders/ ; https://kite.trade/docs/connect/v3/publisher/ | 2026-11-13 | "alphanumeric, max 20 chars" / "max 8 chars" |
| F-ORD-3 | Order statuses: OPEN, COMPLETE, CANCELLED, REJECTED common; interim incl. TRIGGER PENDING, PUT ORDER REQ RECEIVED, VALIDATION PENDING, OPEN PENDING, MODIFY VALIDATION PENDING, MODIFY PENDING, CANCEL PENDING, AMO REQ RECEIVED ("There may be other values") | DOC https://kite.trade/docs/connect/v3/orders/ | 2026-11-13 | status list |
| F-ORD-4 | `market_protection` applies only to MARKET and SL-M orders | DOC https://kite.trade/docs/connect/v3/orders/ | 2026-11-13 | "only applicable for MARKET and SL-M order types" |
| F-ORD-5 | `/orders` rows carry `tag`, `tags`, `order_timestamp`, `status`, `filled_quantity`, `pending_quantity`, `order_type`, `trigger_price`; Kite itself puts `tags` like `mktp:5.00`, `switch_to_amo` on some orders | MEASURED live `/orders` read 2026-11-13 (13 orders) | 2026-11-13 | key list |

WebSocket entitlement and the subscription plan name are **not** verified — see Q-ACCT-1.

## 8. Regulatory context (advisory-only project; recorded as context, drives no code)

| ID | Fact | Source | Accessed |
|---|---|---|---|
| F-REG-1 | SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (4 Feb 2025), "Safer participation of retail investors in Algorithmic trading": brokers are principals, algo orders via broker APIs carry an exchange-provided identifier | https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html | 2026-11-05 |
| F-REG-2 | Implementation extended; SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132 (30 Sep 2025) set a glide path of milestones | https://www.sebi.gov.in/legal/circulars/sep-2025/extension-of-timeline-for-implementation-of-sebi-circular-dated-february-04-2025-on-safer-participation-of-retail-investors-in-algorithmic-trading-_96979.html | 2026-11-05 |

Whether anything changed after April 2026 was **not** verified (Q-REG-1). This project places no orders, so the framework constrains nothing here.

## 9. Added in Phase 1 (2026-11-05)

| ID | Fact | Source | Accessed/measured | Quote |
|---|---|---|---|---|
| F-NSE-1 | Equity-derivatives normal market 09:15–15:40 IST (close moved from 15:30), pre-open 09:00–09:08, effective 2026-08-03 | NSE circular NSE/FAOP/74467 (Ref 74/2026, May 29 2026): https://nsearchives.nseindia.com/content/circulars/FAOP74467.pdf (read from the broker-hosted copy https://flattrade.in/kosh/wp-content/uploads/2026/05/FAOP74467.pdf) | 2026-11-05 | "Normal Market Close Time 15:40 hrs Change in time" |
| F-WS-8 | `kiteconnect` 5.2.2 `KiteTicker`: auto-reconnect with exponential back-off (min 2 s, `reconnect_max_delay` default 60 s, floor 5 s; `reconnect_max_tries` default 50, cap 300); on reconnect `_on_open` calls `resubscribe()` with the stored modes; ping every `PING_INTERVAL`, connection dropped if no pong for 2 intervals; `on_message(ws, payload, is_binary)` receives the raw frame before parsing | LIBRARY SOURCE `site-packages/kiteconnect/ticker.py` (5.2.2), lines 138–200, 340–356, 379–402, 631–691 | 2026-11-05 | "Resubscribe if its reconnect" |
| F-WS-9 | Library parser divisor: price ints ÷100 for NSE/NFO/indices (÷10^7 CDS, ÷10^4 BCD/NCO); `segment = instrument_token & 0xff`; exchange/last-trade times are epoch seconds | LIBRARY SOURCE ticker.py `_parse_binary` (5.2.2) | 2026-11-05 | "segment = instrument_token & 0xff" |
| F-WS-10 | This API key **can** open the WebSocket and receives `full` packets (answers Q-ACCT-1 for streaming) | MEASURED [phase-1-evidence/live-smoke.txt](phase-1-evidence/live-smoke.txt) | 2026-11-05 21:41 IST | 12 packets, mode full |
| F-WS-11 | The index token (NSE:NIFTY 50) sends the 32-byte `full` packet with an exchange timestamp; no OI/volume/depth (answers Q-WS-2) | MEASURED live-smoke.txt | 2026-11-05 | `(256265, 'full', 1793880305, 2453660, None, None)` |
| F-WS-12 | After subscribe, the server sends a text frame `{"type": "instruments_meta", "data": {"count": …, "etag": …}}`; after hours each subscribed token sends one snapshot packet | MEASURED live-smoke.txt | 2026-11-05 | `instruments_meta` |
| F-INST-4 | Full `/instruments` dump on 2026-11-05: 1,658,982 bytes gzipped | MEASURED live-smoke.txt | 2026-11-05 | — |

## 10. Added in Phase 2 (2026-11-05)

Evidence: [phase-2-evidence/nse-sources.txt](phase-2-evidence/nse-sources.txt) (checksums, sizes, raw bytes), [phase-2-evidence/live-universe.txt](phase-2-evidence/live-universe.txt).

| ID | Fact | Source | Accessed/measured | Quote |
|---|---|---|---|---|
| F-NSE-2 | NIFTY 50 constituents: CSV at https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv (same bytes at https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv), columns `Company Name,Industry,Symbol,Series,ISIN Code`, 50 rows. The file carries no "as of" date, so the fetch time is the list's date | OFFICIAL FILE (NSE / NSE Indices) + MEASURED nse-sources.txt | 2026-11-05 | `Company Name,Industry,Symbol,Series,ISIN Code` |
| F-NSE-3 | NIFTY 100 constituents: https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv (same bytes on niftyindices.com), same columns, 100 rows. On 2026-11-05 every NIFTY 50 symbol is also in NIFTY 100 | OFFICIAL FILE + MEASURED | 2026-11-05 | — |
| F-NSE-4 | F&O ban list: https://nsearchives.nseindia.com/content/fo/fo_secban.csv. Line 1 `Securities in Ban For Trade Date DD-MON-YYYY:`, then `n,SYMBOL` lines. The file fetched on the evening of 2026-11-05 was already for the **next** trade date (06-NOV-2026: KAYNES) | OFFICIAL FILE + MEASURED nse-sources.txt | 2026-11-05 ~22:00 IST | `Securities in Ban For Trade Date 06-NOV-2026:` |
| F-NSE-5 | F&O trading holidays 2026: NSE/FAOP/71777 (12 Dec 2025, "Trading holidays for the calendar year 2026", Department FUTURES & OPTIONS): 15 weekday holidays + 4 on Sat/Sun; Muhurat trading Sun 2026-11-08, timings "shall be notified subsequently". Amended by NSE/FAOP/72262 (12 Jan 2026): Thu 2026-01-15 is a trading holiday in F&O. Dates copied into config v2 `restrictions.holidays`; PDF sha256 `5a2079cd…96ea` / `f98ae37c…8f0f` | https://nsearchives.nseindia.com/content/circulars/FAOP71777.pdf, https://nsearchives.nseindia.com/content/circulars/FAOP72262.pdf | 2026-11-05 | "notifies Thursday, January 15, 2026 as a trading holiday in Futures & Options segment" |
| F-NSE-6 | NSE static hosts (nsearchives.nseindia.com, www.niftyindices.com) time out (20 s) for the default `python-requests` User-Agent and answer HTTP 200 to a self-identifying one (`clade-fno-engine/2`). No cookies, no browser impersonation | MEASURED nse-sources.txt | 2026-11-05 | ReadTimeout vs 200 |
| F-INST-5 | In the master, a stock future's `name` equals that stock's NSE `tradingsymbol` (218 of 224 NFO names; e.g. `M&M`, `BAJAJ-AUTO`). The other 6 are indices (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, NIFTYFPI), whose spot `tradingsymbol` differs (NIFTY → `NIFTY 50`, INDICES segment), so that link is config (`universe.index_spots`). Tokens are unique within one dump | MEASURED master 2026-11-05 | 2026-11-05 | — |
| F-INST-6 | The 2026-11-05 master lists NIFTY monthly futures expiring 2026-11-23, 2026-12-29, 2027-01-25 (2026-11-24 is a holiday, F-NSE-5), NIFTY lot 65, and NIFTY options with 18 expiries | MEASURED live-api.txt | 2026-11-05 | — |

The CM-segment circulars NSE/CMTR/71775 and NSE/CMTR/72260 (cited by the lab calendar) list the same dates, but they are for the cash segment. The engine uses the FAOP ones.

## 11. Added in Phase 3 (2026-11-06, first market-hours session)

Evidence: [phase-3-evidence/](phase-3-evidence/) (`feed-report-midday.json`, `live-vs-replay-midday.txt`,
`live-backfill*.txt`), `data/engine/2026-11-06/` and `pmset -g log`.

| ID | Fact | Source | Measured | Note |
|---|---|---|---|---|
| F-WS-13 | Longest gap between frames (1-byte heartbeats included) on a healthy `connected` socket: 1.227 s (connection 2, 11:34–11:40 IST; re-measured at EOD in `feed_report.json` `max_frame_gap_s`) | MEASURED status.json | 2026-11-06 | basis for `ws.stall_after_s: 10` |
| F-WS-14 | Packets sent right after a subscribe (and in pre-open) carry an old exchange timestamp: all 2,525 packets with receive − exchange > 5 s arrived 09:00:45–09:03:05 or at the subscribe instants 11:26:44 and 11:34:16 | MEASURED frames.bin | 2026-11-06 | they inflate latency p99; late-tick rule drops them from candles |
| F-WS-15 | After macOS slept on battery (09:00–09:57), the KiteTicker socket stayed `connected` with **no frames and no close callback** from 09:03:08 until the process was killed at 11:26:38 (2 h 23 min): a half-open socket that kiteconnect 5.2.2 did not detect | MEASURED buffer.sqlite (last tick 09:03:08, no close event) + pmset log | 2026-11-06 | led to the stall watchdog (owner decision) |
| F-HIST-9 | Kite `minute` candles for NSE **cash** tokens end at 15:14 (360 per session, 09:15–15:14) for 95 of the 96 tier A spots on every session 2026-09-29 … 2026-11-05. One exception: ENRIN on 2026-09-29, 375 candles to 15:29. All 290 futures with history end at 15:39 | MEASURED history.sqlite + a direct 15:00–15:40 request | 2026-11-06 | conflicts with config `sessions.cash.close: "15:30"`, see Q-NSE-7 |
| F-HIST-10 | `historical` minute requests for the tier A set: ~0.5 s each at the 3 req/s bucket; 38-day minute windows are accepted (cap 60, F-HIST-5) | MEASURED live-backfill.txt | 2026-11-06 | — |

## 12. Market hours after the Closing Auction Session (verified 2026-11-06)

Evidence: [phase-3-evidence/market-hours-sources.txt](phase-3-evidence/market-hours-sources.txt) (URLs, sha256, verbatim excerpts).

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-NSE-7 | From **2026-08-03**, cash-segment stocks **with derivative contracts** get their closing price from a Closing Auction Session (CAS). Their continuous trading (CTS) ends at **15:15**, then CAS runs 15:15–15:35: transition 15:15, order entry 15:20–15:30 (random close 15:28–15:30), order matching from 15:30. Equity derivatives trade to 15:40; cash post-close 15:50–16:00. Other cash stocks keep the 30-minute VWAP close (CTS to 15:30) | SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/2765/2026, 16 Jan 2026 (para 4.1, 4.2, 6.1); NSE/CMTR/73362, 18 Mar 2026 (para 1.1, 3.2.1.1) | 2026-11-06 | "a separate session of 20 minutes from 3:15 pm to 3:35 pm"; "last half hour of CTS, i.e. 02:45 pm to 03:15 pm" |
| F-NSE-8 | From **2026-09-07** the pre-open session is 09:00–09:15: order entry 09:00–09:10 (random close 09:08–09:10), matching 09:10, transition to CTS 09:12–09:15 | SEBI 16 Jan 2026 (para 5 / 17.1.2, 6.2) | 2026-11-06 | "15 minutes from 9:00 a.m. to 9:15 a.m." |
| F-NSE-9 | From **2026-12-07**: CAS moves to **15:30–15:40** (transition 15:30, order entry 15:31–15:40, random close 15:38–15:40), so CTS for CAS stocks runs to 15:30. **Index and stock derivatives trade to 15:45**, except that on expiry days **expiring index** derivatives stop at 15:30. Cash post-close stays 15:50–16:00. Carrying CTS limit/iceberg orders into CAS starts 2027-02-08 | SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/23843/2026, 15 Oct 2026 (para 4.2, 6.1, 6.2) | 2026-11-06 | "Trading in index derivatives contracts shall continue until 3:45 p.m." |
| F-NSE-10 | Diwali Muhurat trading, F&O, Sun 2026-11-08 (NSE/FAOP/76940, Circular 142/2026, 2026-10-19, continuing NSE/FAOP/71777): pre-open order entry 14:05–14:15, matching 14:15–14:17, buffer 14:17–14:20; continuous trading 14:20–15:40; trade modification to 15:50; trades carry settlement obligations. PDF sha256 `78d97b9c…78ff`. Used by dashboard/special_sessions.json (cockpit). Engine config `restrictions.special_sessions` still treats the day as RESTRICTION_UNVERIFIED (Q-2-2) | https://nsearchives.nseindia.com/content/circulars/FAOP76940.pdf | 2026-11-07 | "Normal Market (Continuous Trading Session - CTS) 14:20 15:40" |

F-NSE-7 explains F-HIST-9: every tier A spot is an F&O stock, so its continuous trading ends at 15:15 and Kite's last minute candle is 15:14.
**F-NSE-1 (F&O close 15:40) is valid only until 2026-12-06.** No NSE implementation circular for F-NSE-9 was found yet (searched 2026-11-06); SEBI gave the exchanges 7 days to update their SOPs.

## 13. Added in Phase 7 (2026-11-06): charges, margin API, feed quantity units

Evidence: [phase-7-evidence/cost-sources.txt](phase-7-evidence/cost-sources.txt) (charges page sha256 `5f425e2e…bae5`, verbatim cell text, kiteconnect source lines).
Charges are Zerodha's (the broker this account uses). Rates go into `config/engine/v9.yaml` → `costs.entries`, one versioned entry each.

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-COST-1 | Brokerage: F&O futures 0.03 % or ₹20 per executed order, whichever is lower; F&O options flat ₹20 per executed order. **No effective date on the page** (Q-COST-1) | https://zerodha.com/charges/ | 2026-11-06 | "0.03% or Rs. 20/executed order whichever is lower"; "Flat Rs. 20 per executed order" |
| F-COST-2 | STT from **2026-04-01**: futures 0.05 % on the sell side (was 0.02 %); options 0.15 % on the sell side, on premium (was 0.1 %); options bought and exercised 0.15 % of intrinsic value (was 0.125 %) | https://zerodha.com/marketintel/bulletin/445377/revision-in-stt-securities-transaction-tax-from-1st-april-2026 ; same rates on https://zerodha.com/charges/ | 2026-11-06 | "Securities Transaction Tax (STT) has been revised from April 1, 2026." |
| F-COST-3 | NSE transaction charges: futures 0.00183 %; options 0.03553 % on premium. **No effective date or NSE circular found** (Q-COST-1) | https://zerodha.com/charges/ ; https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges | 2026-11-06 | "NSE: 0.00183%"; "NSE: 0.03553% (on premium)" |
| F-COST-4 | SEBI charges ₹10 / crore (futures and options). Stamp: futures 0.002 % on the buy side, options 0.003 % on the buy side. The page adds a pending SEBI change with no date (Q-COST-2) | https://zerodha.com/charges/ | 2026-11-06 | "₹10 / crore"; "0.002% or ₹200 / crore on buy side"; "0.003% or ₹300 / crore on buy side" |
| F-COST-5 | GST 18 % on (brokerage + SEBI charges + transaction charges), futures and options | https://zerodha.com/charges/ | 2026-11-06 | "18% on (brokerage + SEBI charges + transaction charges)" |
| F-COST-6 | NSE IPFT: futures ₹0.01 per crore + GST of traded value; options ₹0.01 per crore + GST of premium value | https://zerodha.com/charges/ | 2026-11-06 | "Equity and Futures - ₹0.01 per crore + GST of the traded value." |
| F-MARGIN-1 | Kite Connect margin endpoints are JSON **POST**: `/margins/orders` (per-order margins incl. positions and open orders), `/margins/basket` (`consider_positions`, `mode`), `/charges/orders` (virtual contract note). Response fields `total`, `span`, `exposure`, `charges`. In kiteconnect 5.2.2 they exist only on the `KiteConnect` REST class (`connect.py` lines 166, 168, 824–850), which the engine does not use. **Not called; not measured on this account** (Q-RISK-1) | https://kite.trade/docs/connect/v3/margins/ ; library source | 2026-11-06 | "Requests to the above endpoints are JSON POST" |
| F-QTY-1 | Recorded NFO **futures** feed quantities are in **units, not lots**: every depth level quantity (3,829,572 samples, 291 futures) and every tick `volume` and last-traded quantity (1,723,700 rows) is a whole multiple of the contract's lot size. OI: 982 of 1,723,700 rows are not a multiple (unexplained, not relied on). **Options not measured** (none recorded) | MEASURED `data/engine/2026-11-06/buffer.sqlite` × `universe.sqlite` | 2026-11-06 | — |

Superseded as a cost source: `skills/backtest-expert/scripts/evaluate_backtest.calculate_india_costs` (F&O STT 0.0125 %, options exchange 0.05 %) and
the lab `zerodha_charges_2021_2026.yaml` (futures STT 0.02 % "from 2024-10-01", no 2026 period). Both disagree with F-COST-2/3. Neither was edited (protected).

## 14. Added in Phase 11 (2026-11-07): option exercise style, risk-free rate, event calendar

Evidence: [phase-11-evidence/sources-2026-11-07.txt](phase-11-evidence/sources-2026-11-07.txt) (HTTP status, sha256, verbatim excerpts). Fetched with the F-NSE-6 self-identifying User-Agent, no cookies.

| ID | Fact | Source | Accessed | Quote |
|---|---|---|---|---|
| F-OPT-1 | NSE index options are European: exercisable only on the expiration date | DOC https://www.nseindia.com/static/products-services/equity-derivatives-bank-nifty-option-contract-specification-monthly | 2026-11-07 | "The options contracts shall be European styled which can be exercised only on the expiration date" |
| F-OPT-2 | NSE stock options are European and physically settled (CE = Call European, PE = Put European) | DOC https://www.nseindia.com/static/products-services/equity-derivatives-individual-securities | 2026-11-07 | "Options contracts are European style and physically settled" |
| F-RATE-RBI-1 | 91-day T-bill auction of 2026-11-04: cut-off price ₹98.5511, YTM 5.8970 % (simple annualised: (100 − P)/P × 365/91 reproduces it) | RBI Press Release 2026-2027/1440, https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63918 | 2026-11-07 | "98.5511 … (YTM: 5.8970%)" |
| F-EVT-1 | NSE event calendar (listed companies' board meetings): `GET https://www.nseindia.com/api/event-calendar` returns JSON rows `{symbol, company, purpose, bm_desc, date "DD-Mon-YYYY"}`; with no parameters it listed 607 meetings dated 2026-11-09 … 2026-12-05; answers without cookies | OFFICIAL NSE endpoint + MEASURED (phase-11-evidence) | 2026-11-07 | `"purpose":"Financial Results"` |

Not verified: the regulatory minimum notice a company must give before a board meeting (so absence from the calendar proves nothing beyond that notice; see Q-EVT-1). Black-76 reference values are textbook values (Hull; Haug), cited in the Phase 11 report and tests, not market facts.
