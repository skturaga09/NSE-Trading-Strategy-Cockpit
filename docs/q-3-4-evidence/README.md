# Q-3-4 evidence (2026-11-07)

`q34_measure.py` compares every COMPLETE tick-built 1m candle in `data/engine/2026-11-06/parquet/snapshots` with Kite historical
`minute` candles for the same token and minute (384 tokens, read-only GETs through `engine.broker.KiteSession`, rate-limited by
`engine.backfill.TokenBucket`). Run from the repo root: `python3 docs/q-3-4-evidence/q34_measure.py docs/q-3-4-evidence/measurement.txt`.
`measurement.txt` is the raw output; `measurement.json` holds both volume series.

Result:
- **Futures** (full mode, exchange-time buckets): 26,070 of 26,133 COMPLETE+OK minutes are exactly equal (99.8 %); day-sum ratio 1.0000.
  The 63 that differ come in adjacent-minute pairs that cancel (e.g. POWERGRID 12:30/12:31 swapped), i.e. a trade near the minute boundary.
- **Spot** (quote mode, receive-time buckets, no exchange timestamp per F-WS-6): 79.5 % exact, 89 % within 1 %, ratio p05–p95 0.988–1.013,
  day-sum ratio 1.0005. Prints near a boundary land in the next minute. Worst case: PFC block of 276,089 shares received 11:35:00.036,
  Kite puts it in 11:34, so the tick 11:35 candle is 287,469 vs 11,380 (25×).
- Shifting either series by ±1 minute destroys the match (futures exact 7.5 %), so the minute alignment is right.
- BOSCHLTD (the "implausible 60× RVOL" of Q-STR-2): tick volume equals Kite's in every minute 14:30–14:40 (NOV fut 14:35 = 5,100 vs ≤ 250
  before). The spike is real volume, not a unit mismatch.

Scope: one session, 11:26–15:30 only (outage 09:03–11:26).
