# Phase 12 backtest run 2026-11-07T19:44:07.472802+05:30 (config v17)

## RECORDED

Split: {'development': 0, 'holdout': 0, 'post_window': 0, 'development_days': []}. Holdout: HOLDOUT_EMPTY: fewer good sessions.

### R1. Session quality

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

| session | GOOD | coverage | max edge gap s | reasons |
|---|---|---|---|---|
| 2026-11-06 | False | 65.8% | 1800.0 | COVERAGE 65.8% < 95%; EDGE_GAP 1800 s > 30 s in the first/last 30 min |

### R2. Families (paper-broker trades, net of Phase 7 costs), unit INR

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No trades.

### R3. Families, unit net R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No trades.

### R4. Slippage share of gross P&L, OI publication delay

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

Slippage: {'slippage_inr': 0, 'gross_inr': 0, 'share_of_gross': None}

OI delay: {'label': 'LOOK_AHEAD_DIAGNOSTIC (never a decision input)', 'positioning_decisions': 0, 'oi_unavailable_at_decision': 0, 'differs': 0, 'median_abs_diff_pct': None}

### R7. Segment: underlying, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

### R7. Segment: tod, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

### R7. Segment: score_band, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

### R7. Segment: instrument, unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

### R7. Segment: expiry (events @ FIRST_EXECUTABLE, gross R), unit R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

No rows.

### R6. Walk-forward (train 40 / test 10 / step 10 good sessions), out-of-sample only

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

NOT_RUN: 0 development sessions < train 40 + test 10

### R5. Event study, half-life, Opportunity Age (recorded)

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

0 family x anchor rows; half-life no entries

### R8. Phase 13 profile / depth parts, events at FIRST_EXECUTABLE, gross R

**SIMULATED / HYPOTHETICAL · RECORDED sessions · stage BELOW_SYSTEM_CHECK · 0 good sessions**

**volume_profile**: verdict INSUFFICIENT_SAMPLE (stage BELOW_SYSTEM_CHECK: no conclusion before FINAL); weight unchanged (0 in v17)

No rows.

**depth_behaviour**: verdict INSUFFICIENT_SAMPLE (stage BELOW_SYSTEM_CHECK: no conclusion before FINAL); weight unchanged (0 in v17)

No rows.


## Verdicts

**SIMULATED / HYPOTHETICAL · stage BELOW_SYSTEM_CHECK · 0 good sessions**

| Phase 8 family | verdict | reason |
|---|---|---|
| A | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| B | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| C | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| D | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| E | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |
| F | INSUFFICIENT_SAMPLE | 0 trades < minimum 100 |

## PIPELINE_CHECK 2026-11-06 (EXCLUDED session; not part of any result)

run_day: {'day': '2026-11-06', 'eligible': 0, 'opened': 0, 'not_opened': 0, 'actual': 0}; trades: 0; event rows: 2964; age entries: 783; class entries: 861; OI delay: {'label': 'LOOK_AHEAD_DIAGNOSTIC (never a decision input)', 'positioning_decisions': 20, 'oi_unavailable_at_decision': 0, 'differs': 1, 'median_abs_diff_pct': 0.1582}

| family @ anchor | n | n anchor unavailable | IMMEDIATE_1_5 | CONTINUATION_5_30 | MID_30_90 | MULTI_SESSION | FAILED | INCONCLUSIVE |
|---|---|---|---|---|---|---|---|---|
| BREAKOUT_ACCEPTED @ FIRST_DETECTION | 2 | 0 | 1 | 1 | 0 | 0 | 0 | 0 |
| BREAKOUT_ACCEPTED @ CONFIRMATION | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| BREAKOUT_ACCEPTED @ FIRST_EXECUTABLE | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| LONG_BUILDUP @ FIRST_DETECTION | 13 | 4 | 2 | 1 | 0 | 0 | 3 | 7 |
| LONG_BUILDUP @ CONFIRMATION | 13 | 4 | 2 | 2 | 0 | 0 | 2 | 7 |
| LONG_BUILDUP @ FIRST_EXECUTABLE | 3 | 14 | 0 | 1 | 0 | 0 | 1 | 1 |
| SHORT_BUILDUP @ FIRST_DETECTION | 4 | 3 | 2 | 0 | 0 | 0 | 1 | 1 |
| SHORT_BUILDUP @ CONFIRMATION | 4 | 3 | 2 | 0 | 0 | 0 | 1 | 1 |
| SHORT_BUILDUP @ FIRST_EXECUTABLE | 2 | 5 | 0 | 0 | 0 | 0 | 1 | 1 |
| SHORT_COVERING @ FIRST_DETECTION | 3 | 0 | 0 | 1 | 0 | 0 | 1 | 1 |
| SHORT_COVERING @ CONFIRMATION | 3 | 0 | 0 | 1 | 0 | 0 | 1 | 1 |
| SHORT_COVERING @ FIRST_EXECUTABLE | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| SWEEP_HIGH @ FIRST_DETECTION | 570 | 0 | 103 | 26 | 0 | 0 | 262 | 179 |
| SWEEP_HIGH @ CONFIRMATION | 570 | 0 | 128 | 22 | 0 | 0 | 226 | 194 |
| SWEEP_HIGH @ FIRST_EXECUTABLE | 333 | 237 | 26 | 7 | 0 | 0 | 179 | 121 |
| SWEEP_LOW @ FIRST_DETECTION | 293 | 0 | 101 | 24 | 0 | 0 | 87 | 81 |
| SWEEP_LOW @ CONFIRMATION | 293 | 0 | 114 | 25 | 0 | 0 | 72 | 82 |
| SWEEP_LOW @ FIRST_EXECUTABLE | 85 | 208 | 16 | 5 | 0 | 0 | 37 | 27 |
| ZONE_DEFENDED @ FIRST_DETECTION | 96 | 0 | 33 | 15 | 3 | 0 | 10 | 35 |
| ZONE_DEFENDED @ CONFIRMATION | 96 | 0 | 32 | 8 | 3 | 0 | 16 | 37 |
| ZONE_DEFENDED @ FIRST_EXECUTABLE | 14 | 82 | 2 | 1 | 0 | 0 | 9 | 2 |

### Phase 13 profile / depth parts (PIPELINE_CHECK)

**volume_profile**: verdict INSUFFICIENT_SAMPLE (stage PIPELINE_CHECK: no conclusion before FINAL); weight unchanged (0 in v17)

| volume_profile | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| UNAVAILABLE | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| UNAVAILABLE INSUFFICIENT_COVERAGE | 289 | 0.133 | 0.176 | 3.514 | -1.221 | -0.386 | 0.617 | 116.366 | yes |

**depth_behaviour**: verdict INSUFFICIENT_SAMPLE (stage PIPELINE_CHECK: no conclusion before FINAL); weight unchanged (0 in v17)

| depth_behaviour | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| UNAVAILABLE | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| UNAVAILABLE NOT_TIER_B | 289 | 0.133 | 0.176 | 3.514 | -1.221 | -0.386 | 0.617 | 116.366 | yes |


Half-life file: `config/engine/half_life/v1.json`. Runtime 17.9 s.
