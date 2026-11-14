# Phase 12 backtest run 2026-11-07T17:35:14.448276+05:30 (config v16)

## HISTORICAL_CANDLES

HISTORICAL_CANDLES: NIFTY 50 index 5m/15m (lab CSV, sha256 verified), 1375 usable days 2021-01-01..2026-07-31, 8 excluded; price path only: no fills, no costs, gross R

Not representable: VWAP families (no volume); Phase 8 families A-D (no futures OI); Phase 8 families E/F (rejection RVOL needs volume); stocks (survivorship: no historical constituent lists); rupee expectancy, slippage share (no fills)

Setups by type: {'SWEEP_HIGH': 6115, 'SWEEP_LOW': 6316, 'ZONE_DEFENDED': 982, 'BREAKDOWN_ACCEPTED': 23, 'BREAKOUT_ACCEPTED': 33}. Excluded days: 8.

### H1. Families, entry at FIRST_EXECUTABLE (first TIMELY evaluation), unit R

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED | 1 | 0.348 | 0.000 | — | -1.000 | -1.000 | 0.000 | 1.000 | **INSUFFICIENT_SAMPLE** |
| BREAKOUT_ACCEPTED | 0 | 0.303 | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| SWEEP_HIGH | 2361 | 0.464 | 0.200 | 3.316 | -1.072 | -0.193 [-0.302, -0.078] | 0.775 [0.661, 0.906] | 509.765 | yes |
| SWEEP_LOW | 2029 | 0.507 | 0.237 | 3.229 | -1.005 | -0.003 [-0.122, 0.126] | 0.996 [0.844, 1.167] | 119.266 | yes |
| ZONE_DEFENDED | 133 | 0.626 | 0.241 | 4.097 | -1.026 | 0.206 [-0.248, 0.755] | 1.265 [0.708, 2.065] | 22.433 | yes |

### H2. Event study: segments, pre-signal move, time to exit

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family @ anchor | n | n anchor unavailable | IMMEDIATE_1_5 | CONTINUATION_5_30 | MID_30_90 | MULTI_SESSION | FAILED | INCONCLUSIVE | moved before signal | median pre-signal ATR | median min to target | median min to stop |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED @ FIRST_DETECTION | 23 | 0 | 5 | 2 | 1 | 4 | 7 | 4 | 0.957 | 1.459 | 7.5 | 25.0 |
| BREAKDOWN_ACCEPTED @ CONFIRMATION | 23 | 0 | 3 | 1 | 3 | 5 | 8 | 3 | 0.957 | 1.459 | 27.5 | 20.0 |
| BREAKDOWN_ACCEPTED @ FIRST_EXECUTABLE | 1 | 22 | 0 | 0 | 0 | 0 | 1 | 0 | 1.000 | 2.095 | — | 10.0 |
| BREAKOUT_ACCEPTED @ FIRST_DETECTION | 33 | 0 | 6 | 2 | 1 | 3 | 18 | 3 | 1.000 | 1.558 | 5.0 | 110.0 |
| BREAKOUT_ACCEPTED @ CONFIRMATION | 33 | 0 | 8 | 0 | 1 | 3 | 18 | 3 | 1.000 | 1.558 | 5.0 | 105.0 |
| BREAKOUT_ACCEPTED @ FIRST_EXECUTABLE | 0 | 33 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | — | — |
| SWEEP_HIGH @ FIRST_DETECTION | 6115 | 0 | 1619 | 730 | 76 | 7 | 3204 | 479 | 0.084 | -0.883 | 5.0 | 5.0 |
| SWEEP_HIGH @ CONFIRMATION | 6115 | 0 | 2055 | 682 | 89 | 7 | 2759 | 523 | 0.084 | -0.883 | 5.0 | 5.0 |
| SWEEP_HIGH @ FIRST_EXECUTABLE | 2515 | 3600 | 219 | 245 | 45 | 1 | 1835 | 170 | 0.061 | -0.872 | 10.0 | 5.0 |
| SWEEP_LOW @ FIRST_DETECTION | 6316 | 0 | 1757 | 826 | 102 | 14 | 3067 | 550 | 0.088 | -0.965 | 5.0 | 5.0 |
| SWEEP_LOW @ CONFIRMATION | 6316 | 0 | 2272 | 811 | 110 | 13 | 2507 | 603 | 0.088 | -0.965 | 5.0 | 5.0 |
| SWEEP_LOW @ FIRST_EXECUTABLE | 2179 | 4137 | 184 | 262 | 56 | 4 | 1515 | 158 | 0.065 | -0.919 | 10.0 | 5.0 |
| ZONE_DEFENDED @ FIRST_DETECTION | 982 | 0 | 392 | 286 | 54 | 11 | 171 | 68 | 0.335 | -0.635 | 5.0 | 10.0 |
| ZONE_DEFENDED @ CONFIRMATION | 982 | 0 | 429 | 141 | 39 | 7 | 241 | 125 | 0.335 | -0.635 | 5.0 | 10.0 |
| ZONE_DEFENDED @ FIRST_EXECUTABLE | 156 | 826 | 11 | 18 | 2 | 3 | 99 | 23 | 0.320 | -0.743 | 10.0 | 5.0 |

### H3. Event study: median MFE / MAE in R (and ATR) per horizon after the anchor

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family @ anchor | 1 min | 3 min | 5 min | 10 min | 15 min | 30 min | 60 min |
|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.15 / 0.09 R (0.36 / 0.25 ATR) | 0.17 / 0.11 R (0.52 / 0.34 ATR) | 0.22 / 0.13 R (0.60 / 0.39 ATR) | 0.28 / 0.17 R (0.76 / 0.52 ATR) | 0.41 / 0.32 R (1.24 / 0.94 ATR) |
| BREAKDOWN_ACCEPTED @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.09 / 0.14 R (0.32 / 0.56 ATR) | 0.11 / 0.16 R (0.33 / 0.61 ATR) | 0.14 / 0.23 R (0.42 / 0.79 ATR) | 0.18 / 0.27 R (0.55 / 0.94 ATR) | 0.31 / 0.29 R (0.87 / 1.01 ATR) |
| BREAKDOWN_ACCEPTED @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.05 / 0.77 R (0.04 / 0.60 ATR) | 0.05 / 1.10 R (0.04 / 0.85 ATR) | 0.05 / 1.42 R (0.04 / 1.10 ATR) | 1.40 / 1.42 R (1.09 / 1.10 ATR) | 1.62 / 1.42 R (1.26 / 1.10 ATR) |
| BREAKOUT_ACCEPTED @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.12 / 0.08 R (0.44 / 0.22 ATR) | 0.15 / 0.11 R (0.61 / 0.36 ATR) | 0.22 / 0.13 R (0.86 / 0.37 ATR) | 0.31 / 0.19 R (1.10 / 0.71 ATR) | 0.42 / 0.28 R (1.28 / 1.05 ATR) |
| BREAKOUT_ACCEPTED @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.07 / 0.10 R (0.35 / 0.34 ATR) | 0.12 / 0.13 R (0.46 / 0.53 ATR) | 0.15 / 0.13 R (0.66 / 0.66 ATR) | 0.22 / 0.20 R (0.84 / 0.84 ATR) | 0.25 / 0.36 R (0.97 / 1.23 ATR) |
| SWEEP_HIGH @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.99 / 0.75 R (0.43 / 0.28 ATR) | 1.44 / 1.00 R (0.62 / 0.40 ATR) | 1.78 / 1.00 R (0.75 / 0.48 ATR) | 2.53 / 1.62 R (1.07 / 0.73 ATR) | 3.61 / 2.52 R (1.45 / 1.07 ATR) |
| SWEEP_HIGH @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.62 / 0.59 R (0.35 / 0.34 ATR) | 0.87 / 0.83 R (0.50 / 0.50 ATR) | 1.08 / 1.01 R (0.62 / 0.60 ATR) | 1.57 / 1.57 R (0.90 / 0.86 ATR) | 2.29 / 2.24 R (1.30 / 1.25 ATR) |
| SWEEP_HIGH @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 1.21 / 1.24 R (0.35 / 0.36 ATR) | 1.78 / 1.83 R (0.49 / 0.51 ATR) | 2.14 / 2.24 R (0.61 / 0.62 ATR) | 3.16 / 3.17 R (0.88 / 0.90 ATR) | 4.36 / 4.56 R (1.21 / 1.29 ATR) |
| SWEEP_LOW @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.90 / 0.68 R (0.48 / 0.31 ATR) | 1.26 / 0.93 R (0.69 / 0.43 ATR) | 1.54 / 1.00 R (0.83 / 0.52 ATR) | 2.21 / 1.35 R (1.13 / 0.79 ATR) | 2.99 / 2.24 R (1.49 / 1.19 ATR) |
| SWEEP_LOW @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.52 / 0.50 R (0.37 / 0.36 ATR) | 0.74 / 0.71 R (0.53 / 0.52 ATR) | 0.91 / 0.85 R (0.66 / 0.64 ATR) | 1.34 / 1.34 R (0.93 / 0.93 ATR) | 1.86 / 2.06 R (1.28 / 1.35 ATR) |
| SWEEP_LOW @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 1.17 / 1.17 R (0.38 / 0.38 ATR) | 1.74 / 1.78 R (0.56 / 0.53 ATR) | 2.15 / 2.20 R (0.70 / 0.67 ATR) | 2.96 / 3.15 R (0.98 / 0.98 ATR) | 3.92 / 4.31 R (1.30 / 1.41 ATR) |
| ZONE_DEFENDED @ FIRST_DETECTION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.38 / 0.26 R (0.45 / 0.30 ATR) | 0.58 / 0.33 R (0.68 / 0.38 ATR) | 0.73 / 0.39 R (0.82 / 0.44 ATR) | 1.07 / 0.60 R (1.21 / 0.69 ATR) | 1.45 / 0.88 R (1.67 / 0.98 ATR) |
| ZONE_DEFENDED @ CONFIRMATION | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 0.24 / 0.23 R (0.35 / 0.35 ATR) | 0.35 / 0.33 R (0.53 / 0.50 ATR) | 0.44 / 0.40 R (0.68 / 0.61 ATR) | 0.68 / 0.61 R (1.04 / 0.91 ATR) | 0.93 / 0.88 R (1.36 / 1.27 ATR) |
| ZONE_DEFENDED @ FIRST_EXECUTABLE | n/a: BELOW_DATA_RESOLUTION | n/a: BELOW_DATA_RESOLUTION | 2.18 / 1.57 R (0.39 / 0.28 ATR) | 3.05 / 2.33 R (0.53 / 0.40 ATR) | 4.12 / 3.00 R (0.66 / 0.51 ATR) | 6.86 / 3.99 R (1.12 / 0.75 ATR) | 8.13 / 5.50 R (1.42 / 1.09 ATR) |

### H4. Edge half-life (fresh entry expectancy by age since confirmation)

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| setup type | status | half-life | age 0 min: n / E[R] | age 5 min: n / E[R] | age 15 min: n / E[R] | age 30 min: n / E[R] | age 60 min: n / E[R] | age 120 min: n / E[R] |
|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED | INSUFFICIENT_SAMPLE | — | 21 / -0.014 | 17 / 0.110 | 15 / 0.092 | 13 / 0.188 | 11 / 0.074 | 8 / -0.245 |
| BREAKOUT_ACCEPTED | INSUFFICIENT_SAMPLE | — | 19 / -0.017 | 12 / -0.031 | 12 / 0.035 | 12 / -0.011 | 11 / 0.000 | 8 / -0.130 |
| SWEEP_HIGH | NO_POSITIVE_EDGE | — | 5627 / -0.112 | 1794 / -0.070 | 643 / -0.083 | 235 / 0.032 | 56 / 0.035 | 18 / -0.003 |
| SWEEP_LOW | NO_POSITIVE_EDGE | — | 5658 / -0.066 | 1874 / 0.008 | 639 / 0.048 | 243 / -0.012 | 69 / 0.023 | 11 / 0.480 |
| ZONE_DEFENDED | NO_POSITIVE_EDGE | — | 860 / -0.040 | 325 / 0.015 | 177 / 0.031 | 97 / -0.011 | 35 / 0.001 | 11 / 0.285 |

### H5. Opportunity Age validation: TIMELY vs VALID_BUT_LATE vs RETEST entries

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED / TIMELY | 1 | — | 0.000 | — | -1.000 | -1.000 | 0.000 | 1.000 | **INSUFFICIENT_SAMPLE** |
| BREAKDOWN_ACCEPTED / VALID_BUT_LATE | 22 | — | 0.591 | 0.429 | -0.702 | -0.034 [-0.330, 0.261] | 0.883 [0.252, 2.847] | 1.766 | **INSUFFICIENT_SAMPLE** |
| BREAKOUT_ACCEPTED / VALID_BUT_LATE | 33 | — | 0.606 | 0.382 | -0.780 | -0.076 [-0.331, 0.175] | 0.753 [0.262, 1.981] | 4.203 | **INSUFFICIENT_SAMPLE** |
| SWEEP_HIGH / RETEST | 423 | — | 0.189 | 2.742 | -0.979 | -0.275 [-0.441, -0.103] | 0.653 [0.468, 0.864] | 130.566 | yes |
| SWEEP_HIGH / TIMELY | 2164 | — | 0.197 | 3.486 | -1.081 | -0.179 [-0.300, -0.056] | 0.793 [0.669, 0.932] | 440.587 | yes |
| SWEEP_HIGH / VALID_BUT_LATE | 4917 | — | 0.571 | 0.492 | -0.937 | -0.121 [-0.149, -0.094] | 0.698 [0.641, 0.760] | 601.363 | yes |
| SWEEP_LOW / RETEST | 382 | — | 0.199 | 2.905 | -0.991 | -0.216 [-0.409, -0.002] | 0.728 [0.509, 0.997] | 94.781 | yes |
| SWEEP_LOW / TIMELY | 1846 | — | 0.238 | 3.233 | -1.014 | -0.002 [-0.127, 0.140] | 0.998 [0.840, 1.185] | 119.605 | yes |
| SWEEP_LOW / VALID_BUT_LATE | 5235 | — | 0.595 | 0.459 | -0.913 | -0.097 [-0.122, -0.071] | 0.738 [0.681, 0.801] | 507.855 | yes |
| ZONE_DEFENDED / RETEST | 5 | — | 0.400 | 2.563 | -1.000 | 0.425 [-1.000, 1.960] | 1.708 [0.000, 10.251] | 3.000 | **INSUFFICIENT_SAMPLE** |
| ZONE_DEFENDED / TIMELY | 128 | — | 0.234 | 4.200 | -1.027 | 0.198 [-0.277, 0.753] | 1.251 [0.674, 2.044] | 21.433 | yes |
| ZONE_DEFENDED / VALID_BUT_LATE | 851 | — | 0.716 | 0.265 | -0.859 | -0.055 [-0.098, -0.011] | 0.776 [0.639, 0.948] | 46.723 | yes |

### H6. Segment: timeframe (min), entry at FIRST_EXECUTABLE, all setup types

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| timeframe (min) | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| 15 | 433 | 0.040 | 0.196 | 2.858 | -1.052 | -0.284 [-0.465, -0.100] | 0.664 [0.492, 0.872] | 142.875 | yes |
| 5 | 4091 | 0.086 | 0.220 | 3.341 | -1.040 | -0.076 [-0.159, 0.011] | 0.906 [0.808, 1.013] | 371.282 | yes |

### H6. Segment: NIFTY 15m TREND regime, entry at FIRST_EXECUTABLE, all setup types

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| NIFTY 15m TREND regime | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| DOWN | 276 | 0.034 | 0.207 | 3.150 | -1.003 | -0.146 [-0.431, 0.173] | 0.817 [0.486, 1.228] | 56.279 | yes |
| RANGE | 337 | 0.032 | 0.187 | 3.607 | -1.306 | -0.388 [-0.817, 0.020] | 0.635 [0.376, 1.023] | 132.953 | yes |
| UNAVAILABLE | 3623 | 0.105 | 0.224 | 3.263 | -1.022 | -0.062 [-0.147, 0.028] | 0.922 [0.819, 1.036] | 314.638 | yes |
| UP | 288 | 0.032 | 0.184 | 3.644 | -1.000 | -0.145 [-0.436, 0.207] | 0.822 [0.487, 1.265] | 69.079 | yes |

### H6. Segment: time of day (confirmation), entry at FIRST_EXECUTABLE, all setup types

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| time of day (confirmation) | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|
| 09:15-10:15 | 242 | 0.164 | 0.215 | 3.893 | -1.002 | 0.050 [-0.245, 0.367] | 1.064 [0.706, 1.499] | 39.362 | yes |
| 10:15-11:30 | 1077 | 0.149 | 0.227 | 3.174 | -0.992 | -0.049 [-0.183, 0.095] | 0.937 [0.769, 1.128] | 126.220 | yes |
| 11:30-13:30 | 1891 | 0.099 | 0.225 | 3.437 | -1.029 | -0.023 [-0.155, 0.124] | 0.971 [0.810, 1.159] | 169.320 | yes |
| 13:30-14:30 | 852 | 0.056 | 0.189 | 3.038 | -1.162 | -0.368 [-0.564, -0.189] | 0.609 [0.466, 0.781] | 324.612 | yes |
| 14:30-15:40 | 462 | 0.022 | 0.221 | 3.132 | -0.995 | -0.084 [-0.327, 0.196] | 0.892 [0.595, 1.261] | 91.488 | yes |

### H7. Walk-forward (train 12 m / test 3 m / step 3 m), out-of-sample test windows only

**SIMULATED / HYPOTHETICAL · HISTORICAL_CANDLES (NIFTY 50 index, lab CSV) · no recorded-session stage applies · 0 recorded good sessions · 1375 usable index days · price path, no fills, no costs, gross R**

| family | windows | windows with a choice | choices | n | precision | win rate | avg win | avg loss | expectancy [95% CI] | profit factor [95% CI] | max DD | n >= 100 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BREAKDOWN_ACCEPTED | 18 | 0 | {} | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| BREAKOUT_ACCEPTED | 18 | 0 | {} | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |
| SWEEP_HIGH | 18 | 18 | {'{"structure.acceptance.closes": 2, "structure.consolidation.max_width_atr": 1.0}': 14, '{"structure.acceptance.closes": 2, "structure.consolidation.max_width_atr": 1.5}': 4} | 1908 | 0.204 | 0.200 | 3.336 | -1.084 | -0.202 [-0.327, -0.066] | 0.767 [0.639, 0.919] | 410.242 | yes |
| SWEEP_LOW | 18 | 18 | {'{"structure.acceptance.closes": 2, "structure.consolidation.max_width_atr": 1.0}': 18} | 1632 | 0.232 | 0.232 | 3.308 | -0.999 | 0.001 [-0.134, 0.154] | 1.002 [0.828, 1.206] | 119.266 | yes |
| ZONE_DEFENDED | 18 | 0 | {} | 0 | — | — | — | — | — | — | 0.000 | **INSUFFICIENT_SAMPLE** |

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

Half-life file: `config/engine/half_life/v1.json`. Runtime 167.3 s.
