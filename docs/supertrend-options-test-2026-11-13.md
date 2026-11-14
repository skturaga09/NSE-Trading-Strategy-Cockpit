# Supertrend(10,3) 5-minute flips on REAL option prices: 1 strike ITM, 1 lot (research)

Sessions 2026-10-28 to 2026-11-12 (11), 96 stocks. ASSUMED 1 % half-spread per side + verified charges.

| exit | holding | trades | win rate | avg net ₹ / trade | avg win / avg loss | total net ₹ | avg premium paid | median hold |
|---|---|---|---|---|---|---|---|---|
| LINE | INTRADAY | 1715 | 38% | ₹+153 | ₹+3,352 / ₹-1,839 | ₹+261,736 | ₹22,245 | 110 min |
| LINE | OVERNIGHT | 1648 | 37% | ₹+687 | ₹+5,763 / ₹-2,303 | ₹+1,132,722 | ₹22,093 | 184 min |
| CLOSE | INTRADAY | 1715 | 37% | ₹-80 | ₹+3,474 / ₹-2,154 | ₹-136,971 | ₹22,245 | 125 min |
| CLOSE | OVERNIGHT | 1666 | 33% | ₹+362 | ₹+7,298 / ₹-2,991 | ₹+603,531 | ₹22,235 | 275 min |

## How solid is it?

| exit | holding | still OPEN at the end (valued at last price) | avg net ₹ without the best day | avg net ₹ if the buy/sell gap is 2 % per side, not 1 % |
|---|---|---|---|---|
| LINE | INTRADAY | 0 | ₹+18 (best day 2026-11-04: ₹+234,094) | ₹-294 |
| LINE | OVERNIGHT | 72 | ₹+302 (best day 2026-11-04: ₹+678,909) | ₹+238 |
| CLOSE | INTRADAY | 0 | ₹-227 (best day 2026-11-04: ₹+217,843) | ₹-525 |
| CLOSE | OVERNIGHT | 91 | ₹-113 (best day 2026-11-04: ₹+774,800) | ₹-87 |

## Split (LINE stop, INTRADAY)

| group | trades | win rate | avg net ₹ | avg win / avg loss | total | premium | hold |
|---|---|---|---|---|---|---|---|
| UP flips (CE) | 870 | 44% | ₹+765 | ₹+4,111 / ₹-1,916 | ₹+665,760 | ₹23,228 | 118 min |
| DOWN flips (PE) | 845 | 32% | ₹-478 | ₹+2,268 / ₹-1,774 | ₹-404,023 | ₹21,232 | 105 min |
| flip before 14:00 | 1392 | 42% | ₹+327 | ₹+3,621 / ₹-2,053 | ₹+455,860 | ₹22,207 | 135 min |
| flip 14:00 or later | 323 | 23% | ₹-601 | ₹+1,228 / ₹-1,145 | ₹-194,123 | ₹22,408 | 40 min |

## Per day (LINE stop, INTRADAY)

| day | trades | win rate | avg net ₹ | avg win / avg loss | total | premium | hold |
|---|---|---|---|---|---|---|---|
| 2026-10-28 | 162 | 36% | ₹-701 | ₹+1,818 / ₹-2,145 | ₹-113,625 | ₹25,863 | 124 min |
| 2026-10-29 | 154 | 36% | ₹+272 | ₹+3,990 / ₹-1,794 | ₹+41,847 | ₹24,500 | 115 min |
| 2026-10-30 | 158 | 34% | ₹-379 | ₹+2,131 / ₹-1,646 | ₹-59,927 | ₹21,993 | 105 min |
| 2026-11-02 | 177 | 44% | ₹+323 | ₹+3,180 / ₹-1,877 | ₹+57,127 | ₹23,058 | 125 min |
| 2026-11-03 | 167 | 37% | ₹+79 | ₹+3,057 / ₹-1,680 | ₹+13,130 | ₹22,853 | 94 min |
| 2026-11-04 | 151 | 44% | ₹+1,550 | ₹+5,550 / ₹-1,555 | ₹+234,094 | ₹21,378 | 124 min |
| 2026-11-05 | 109 | 39% | ₹+564 | ₹+4,134 / ₹-1,763 | ₹+61,431 | ₹20,620 | 87 min |
| 2026-11-06 | 155 | 47% | ₹+747 | ₹+3,999 / ₹-2,148 | ₹+115,807 | ₹21,804 | 114 min |
| 2026-11-09 | 158 | 25% | ₹-764 | ₹+2,581 / ₹-1,897 | ₹-120,662 | ₹20,388 | 105 min |
| 2026-11-11 | 156 | 47% | ₹+518 | ₹+3,300 / ₹-1,993 | ₹+80,783 | ₹21,162 | 110 min |
| 2026-11-12 | 168 | 33% | ₹-287 | ₹+2,647 / ₹-1,755 | ₹-48,269 | ₹20,454 | 127 min |

## Not traded

- CLOSE/OVERNIGHT: NO FILL at exit: 49
- LINE/OVERNIGHT: NO FILL at exit: 67
- NO FILL at entry (option not traded within 5 min): 61
- flip after 15:10: 49

## YOUR ACCOUNT, your rules: hold overnight only when 5m and 15m agree at 15:15

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 53** (4.8 per trading day with a trade)
- **Total net: ₹+98,052** · win rate 51% · avg win ₹+7,182 · avg loss ₹-3,687 · worst drawdown ₹-20,043
- Held overnight: 10 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-28 ₹-2,129 · 10-29 ₹-14,886 · 10-30 ₹+26,966 · 11-02 ₹-760 · 11-03 ₹-7,499 · 11-04 ₹+4,260 · 11-05 ₹-1 · 11-06 ₹+13,717 · 11-09 ₹+15,470 · 11-11 ₹+57,712 · 11-12 ₹+5,201
- Skipped: 4 positions already open 262 · 5 trades already today 104 · no option trade at the exit 8 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-28 09:20 | PIDILITIND | PIDILITIND 1460 PE 2026-11-23 | ₹25,124 | 10-28 11:58 | LINE_STOP | 0 | **₹+7,868** |
| 10-28 09:20 | TORNTPHARM | TORNTPHARM 4550 PE 2026-11-23 | ₹15,895 | 10-28 11:32 | LINE_STOP | 0 | **₹-4,749** |
| 10-28 12:00 | ETERNAL | ETERNAL 325 CE 2026-11-23 | ₹30,248 | 10-28 14:01 | LINE_STOP | 0 | **₹+196** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 09:20 | MUTHOOTFIN | MUTHOOTFIN 2400 CE 2026-11-23 | ₹35,691 | 10-29 12:03 | LINE_STOP | 0 | **₹-2,798** |
| 10-29 09:20 | ADANIENSOL | ADANIENSOL 1300 CE 2026-11-23 | ₹38,178 | 10-30 09:15 | LINE_STOP | 1 | **₹+15,202** |
| 10-29 09:20 | POLYCAB | POLYCAB 7800 CE 2026-11-23 | ₹47,344 | 10-29 09:47 | LINE_STOP | 0 | **₹-9,891** |
| 10-29 09:55 | BAJFINANCE | BAJFINANCE 910 CE 2026-11-23 | ₹26,096 | 10-30 09:15 | LINE_STOP | 1 | **₹+6,229** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 11-02 09:15 | LINE_STOP | 3 | **₹-2,767** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 09:20 | MOTHERSON | MOTHERSON 160 PE 2026-11-23 | ₹36,772 | 10-30 12:55 | LINE_STOP | 0 | **₹+1,893** |
| 10-30 09:20 | JINDALSTEL | JINDALSTEL 1080 PE 2026-11-23 | ₹26,292 | 10-30 10:21 | LINE_STOP | 0 | **₹-1,455** |
| 10-30 10:45 | NTPC | NTPC 310 CE 2026-11-23 | ₹10,529 | 10-30 13:43 | LINE_STOP | 0 | **₹+2,371** |
| 11-02 09:20 | BANKBARODA | BANKBARODA 245 CE 2026-11-23 | ₹24,432 | 11-03 09:17 | LINE_STOP | 1 | **₹-7,228** |
| 11-02 09:20 | BAJAJ-AUTO | BAJAJ-AUTO 10400 CE 2026-11-23 | ₹20,748 | 11-02 09:22 | LINE_STOP | 0 | **₹-2,132** |
| 11-02 09:20 | INDIGO | INDIGO 4850 CE 2026-11-23 | ₹24,384 | 11-02 10:28 | LINE_STOP | 0 | **₹+3,507** |
| 11-02 09:20 | TATAPOWER | TATAPOWER 345 CE 2026-11-23 | ₹17,574 | 11-02 13:07 | LINE_STOP | 0 | **₹+4,571** |
| 11-02 09:25 | DRREDDY | DRREDDY 1350 CE 2026-11-23 | ₹22,536 | 11-02 12:22 | LINE_STOP | 0 | **₹-3,939** |
| 11-03 09:20 | INDIGO | INDIGO 5000 CE 2026-11-23 | ₹27,656 | 11-03 12:46 | LINE_STOP | 0 | **₹-4,770** |
| 11-03 09:20 | ASIANPAINT | ASIANPAINT 2360 CE 2026-11-23 | ₹15,756 | 11-03 12:13 | LINE_STOP | 0 | **₹+6,794** |
| 11-03 09:20 | HDFCLIFE | HDFCLIFE 520 CE 2026-11-23 | ₹17,276 | 11-03 10:08 | LINE_STOP | 0 | **₹-1,727** |
| 11-03 09:20 | SHRIRAMFIN | SHRIRAMFIN 860 CE 2026-11-23 | ₹33,622 | 11-03 11:01 | LINE_STOP | 0 | **₹-3,733** |
| 11-03 10:30 | SBILIFE | SBILIFE 1640 CE 2026-11-23 | ₹19,449 | 11-03 13:43 | LINE_STOP | 0 | **₹+3,163** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 09:20 | GAIL | GAIL 180 CE 2026-11-23 | ₹21,621 | 11-04 12:20 | LINE_STOP | 0 | **₹-670** |
| 11-04 09:20 | HDFCLIFE | HDFCLIFE 525 CE 2026-11-23 | ₹15,943 | 11-04 10:32 | LINE_STOP | 0 | **₹+41** |
| 11-04 09:20 | INDIGO | INDIGO 5000 CE 2026-11-23 | ₹25,550 | 11-06 09:15 | LINE_STOP | 2 | **₹+33,760** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-06 09:15 | LINE_STOP | 1 | **₹-5,892** |
| 11-05 09:20 | TMPV | TMPV 285 CE 2026-11-23 | ₹20,362 | 11-05 14:20 | LINE_STOP | 0 | **₹+4,233** |
| 11-05 09:20 | GODREJCP | GODREJCP 870 CE 2026-11-23 | ₹13,130 | 11-05 15:10 | LINE_STOP | 0 | **₹-4,233** |
| 11-06 09:20 | M&M | M&M 3150 CE 2026-11-23 | ₹19,412 | 11-09 09:16 | LINE_STOP | 3 | **₹+8,940** |
| 11-06 09:20 | TCS | TCS 2540 CE 2026-11-23 | ₹19,021 | 11-06 10:57 | LINE_STOP | 0 | **₹-6,538** |
| 11-06 09:20 | ENRIN | ENRIN 2800 PE 2026-11-23 | ₹24,657 | 11-06 13:56 | LINE_STOP | 0 | **₹-2,927** |
| 11-06 09:20 | ABB | ABB 6600 PE 2026-11-23 | ₹34,454 | 11-06 11:11 | LINE_STOP | 0 | **₹-1,860** |
| 11-06 12:05 | BEL | BEL 390 PE 2026-11-23 | ₹14,249 | 11-06 13:13 | LINE_STOP | 0 | **₹-2,827** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-11 12:35 | LINE_STOP | 2 | **₹+65,709** |
| 11-09 09:20 | MUTHOOTFIN | MUTHOOTFIN 2850 CE 2026-11-23 | ₹32,552 | 11-09 12:49 | LINE_STOP | 0 | **₹+971** |
| 11-09 09:20 | IOC | IOC 145 CE 2026-11-23 | ₹19,301 | 11-09 14:02 | LINE_STOP | 0 | **₹+3,042** |
| 11-09 09:20 | HCLTECH | HCLTECH 1440 PE 2026-11-23 | ₹18,988 | 11-09 13:33 | LINE_STOP | 0 | **₹+2,517** |
| 11-09 12:50 | AXISBANK | AXISBANK 1310 PE 2026-11-23 | ₹16,854 | 11-11 09:15 | LINE_STOP | 2 | **₹-7,646** |
| 11-11 09:20 | ENRIN | ENRIN 2900 CE 2026-11-23 | ₹22,474 | 11-11 14:57 | LINE_STOP | 0 | **₹-225** |
| 11-11 09:20 | KOTAKBANK | KOTAKBANK 480 CE 2026-11-23 | ₹21,210 | 11-11 12:11 | LINE_STOP | 0 | **₹+2,151** |
| 11-11 09:20 | BRITANNIA | BRITANNIA 4800 CE 2026-11-23 | ₹14,449 | 11-11 13:12 | LINE_STOP | 0 | **₹+115** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-11 13:20 | ABB | ABB 6900 CE 2026-11-23 | ₹35,981 | 11-12 11:01 | LINE_STOP | 1 | **₹+1,380** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | BAJFINANCE | BAJFINANCE 1100 CE 2026-11-23 | ₹24,467 | 11-12 13:07 | LINE_STOP | 0 | **₹-5,258** |
| 11-12 11:05 | TVSMOTOR | TVSMOTOR 4600 PE 2026-11-23 | ₹21,731 | 11-12 14:02 | LINE_STOP | 0 | **₹+5,187** |
| 11-12 11:25 | TATAPOWER | TATAPOWER 365 PE 2026-11-23 | ₹17,135 | open | OPEN | 0 | **₹+505** |

## Same picks and limits, but always out by 15:15 (for comparison)

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 54** (4.9 per trading day with a trade)
- **Total net: ₹+73,302** · win rate 52% · avg win ₹+5,232 · avg loss ₹-2,815 · worst drawdown ₹-15,117
- Held overnight: 0 trades · still OPEN at the end (valued at the last price): 0
- Net by exit day: 10-28 ₹-2,129 · 10-29 ₹+35,280 · 10-30 ₹+4,263 · 11-02 ₹-3,630 · 11-03 ₹-271 · 11-04 ₹+12,517 · 11-05 ₹+3,267 · 11-06 ₹-6,961 · 11-09 ₹+33,560 · 11-11 ₹+668 · 11-12 ₹-3,262
- Skipped: 4 positions already open 269 · 5 trades already today 104 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-28 09:20 | PIDILITIND | PIDILITIND 1460 PE 2026-11-23 | ₹25,124 | 10-28 11:58 | LINE_STOP | 0 | **₹+7,868** |
| 10-28 09:20 | TORNTPHARM | TORNTPHARM 4550 PE 2026-11-23 | ₹15,895 | 10-28 11:32 | LINE_STOP | 0 | **₹-4,749** |
| 10-28 12:00 | ETERNAL | ETERNAL 325 CE 2026-11-23 | ₹30,248 | 10-28 14:01 | LINE_STOP | 0 | **₹+196** |
| 10-29 09:20 | ADANIPORTS | ADANIPORTS 1780 CE 2026-11-23 | ₹27,274 | 10-29 15:15 | TIME_15:15 | 0 | **₹+20,667** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 09:20 | MUTHOOTFIN | MUTHOOTFIN 2400 CE 2026-11-23 | ₹35,691 | 10-29 12:03 | LINE_STOP | 0 | **₹-2,798** |
| 10-29 09:20 | ADANIENSOL | ADANIENSOL 1300 CE 2026-11-23 | ₹38,178 | 10-29 15:15 | TIME_15:15 | 0 | **₹+19,973** |
| 10-29 11:15 | HDFCLIFE | HDFCLIFE 515 CE 2026-11-23 | ₹19,720 | 10-29 15:15 | TIME_15:15 | 0 | **₹-365** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 10-30 15:15 | TIME_15:15 | 0 | **₹-1,272** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 09:20 | MOTHERSON | MOTHERSON 160 PE 2026-11-23 | ₹36,772 | 10-30 12:55 | LINE_STOP | 0 | **₹+1,893** |
| 10-30 09:20 | JINDALSTEL | JINDALSTEL 1080 PE 2026-11-23 | ₹26,292 | 10-30 10:21 | LINE_STOP | 0 | **₹-1,455** |
| 10-30 10:45 | NTPC | NTPC 310 CE 2026-11-23 | ₹10,529 | 10-30 13:43 | LINE_STOP | 0 | **₹+2,371** |
| 11-02 09:20 | BANKBARODA | BANKBARODA 245 CE 2026-11-23 | ₹24,432 | 11-02 15:15 | TIME_15:15 | 0 | **₹-5,638** |
| 11-02 09:20 | BAJAJ-AUTO | BAJAJ-AUTO 10400 CE 2026-11-23 | ₹20,748 | 11-02 09:22 | LINE_STOP | 0 | **₹-2,132** |
| 11-02 09:20 | INDIGO | INDIGO 4850 CE 2026-11-23 | ₹24,384 | 11-02 10:28 | LINE_STOP | 0 | **₹+3,507** |
| 11-02 09:20 | TATAPOWER | TATAPOWER 345 CE 2026-11-23 | ₹17,574 | 11-02 13:07 | LINE_STOP | 0 | **₹+4,571** |
| 11-02 09:25 | DRREDDY | DRREDDY 1350 CE 2026-11-23 | ₹22,536 | 11-02 12:22 | LINE_STOP | 0 | **₹-3,939** |
| 11-03 09:20 | INDIGO | INDIGO 5000 CE 2026-11-23 | ₹27,656 | 11-03 12:46 | LINE_STOP | 0 | **₹-4,770** |
| 11-03 09:20 | ASIANPAINT | ASIANPAINT 2360 CE 2026-11-23 | ₹15,756 | 11-03 12:13 | LINE_STOP | 0 | **₹+6,794** |
| 11-03 09:20 | HDFCLIFE | HDFCLIFE 520 CE 2026-11-23 | ₹17,276 | 11-03 10:08 | LINE_STOP | 0 | **₹-1,727** |
| 11-03 09:20 | SHRIRAMFIN | SHRIRAMFIN 860 CE 2026-11-23 | ₹33,622 | 11-03 11:01 | LINE_STOP | 0 | **₹-3,733** |
| 11-03 10:30 | SBILIFE | SBILIFE 1640 CE 2026-11-23 | ₹19,449 | 11-03 13:43 | LINE_STOP | 0 | **₹+3,163** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 09:20 | GAIL | GAIL 180 CE 2026-11-23 | ₹21,621 | 11-04 12:20 | LINE_STOP | 0 | **₹-670** |
| 11-04 09:20 | HDFCLIFE | HDFCLIFE 525 CE 2026-11-23 | ₹15,943 | 11-04 10:32 | LINE_STOP | 0 | **₹+41** |
| 11-04 09:20 | INDIGO | INDIGO 5000 CE 2026-11-23 | ₹25,550 | 11-04 15:15 | TIME_15:15 | 0 | **₹+8,257** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-05 15:15 | TIME_15:15 | 0 | **₹+509** |
| 11-05 09:20 | TMPV | TMPV 285 CE 2026-11-23 | ₹20,362 | 11-05 14:20 | LINE_STOP | 0 | **₹+4,233** |
| 11-05 09:20 | GODREJCP | GODREJCP 870 CE 2026-11-23 | ₹13,130 | 11-05 15:10 | LINE_STOP | 0 | **₹-4,233** |
| 11-05 09:20 | PFC | PFC 320 CE 2026-11-23 | ₹12,277 | 11-05 15:15 | TIME_15:15 | 0 | **₹+2,759** |
| 11-06 09:20 | M&M | M&M 3150 CE 2026-11-23 | ₹19,412 | 11-06 15:15 | TIME_15:15 | 0 | **₹+7,191** |
| 11-06 09:20 | TCS | TCS 2540 CE 2026-11-23 | ₹19,021 | 11-06 10:57 | LINE_STOP | 0 | **₹-6,538** |
| 11-06 09:20 | ENRIN | ENRIN 2800 PE 2026-11-23 | ₹24,657 | 11-06 13:56 | LINE_STOP | 0 | **₹-2,927** |
| 11-06 09:20 | ABB | ABB 6600 PE 2026-11-23 | ₹34,454 | 11-06 11:11 | LINE_STOP | 0 | **₹-1,860** |
| 11-06 12:05 | BEL | BEL 390 PE 2026-11-23 | ₹14,249 | 11-06 13:13 | LINE_STOP | 0 | **₹-2,827** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-09 15:15 | TIME_15:15 | 0 | **₹+29,426** |
| 11-09 09:20 | MUTHOOTFIN | MUTHOOTFIN 2850 CE 2026-11-23 | ₹32,552 | 11-09 12:49 | LINE_STOP | 0 | **₹+971** |
| 11-09 09:20 | IOC | IOC 145 CE 2026-11-23 | ₹19,301 | 11-09 14:02 | LINE_STOP | 0 | **₹+3,042** |
| 11-09 09:20 | HCLTECH | HCLTECH 1440 PE 2026-11-23 | ₹18,988 | 11-09 13:33 | LINE_STOP | 0 | **₹+2,517** |
| 11-09 12:50 | AXISBANK | AXISBANK 1310 PE 2026-11-23 | ₹16,854 | 11-09 15:15 | TIME_15:15 | 0 | **₹-2,396** |
| 11-11 09:20 | ENRIN | ENRIN 2900 CE 2026-11-23 | ₹22,474 | 11-11 14:57 | LINE_STOP | 0 | **₹-225** |
| 11-11 09:20 | KOTAKBANK | KOTAKBANK 480 CE 2026-11-23 | ₹21,210 | 11-11 12:11 | LINE_STOP | 0 | **₹+2,151** |
| 11-11 09:20 | BRITANNIA | BRITANNIA 4800 CE 2026-11-23 | ₹14,449 | 11-11 13:12 | LINE_STOP | 0 | **₹+115** |
| 11-11 09:20 | IOC | IOC 147 CE 2026-11-23 | ₹17,578 | 11-11 09:27 | LINE_STOP | 0 | **₹-1,400** |
| 11-11 09:35 | GAIL | GAIL 185 CE 2026-11-23 | ₹18,860 | 11-11 14:38 | LINE_STOP | 0 | **₹+26** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | BAJFINANCE | BAJFINANCE 1100 CE 2026-11-23 | ₹24,467 | 11-12 13:07 | LINE_STOP | 0 | **₹-5,258** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | 11-12 15:15 | TIME_15:15 | 0 | **₹+667** |

## ₹50,000 CAPITAL, your rules (cash-limited: profits reused, losses shrink what you can buy)

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 39** (3.5 per trading day with a trade)
- **Total net: ₹+55,223** · win rate 41% · avg win ₹+7,423 · avg loss ₹-2,763 · worst drawdown ₹-23,528
- Held overnight: 12 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-28 ₹-5,247 · 10-29 ₹-609 · 10-30 ₹-645 · 11-02 ₹-9,799 · 11-03 ₹-3,050 · 11-04 ₹+5,709 · 11-05 ₹+13,171 · 11-06 ₹-16,217 · 11-09 ₹+6,051 · 11-11 ₹+58,483 · 11-12 ₹+7,377
- Skipped: 4 positions already open 1 · 5 trades already today 16 · no option trade at the exit 8 · not enough cash 363 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-28 12:00 | ETERNAL | ETERNAL 325 CE 2026-11-23 | ₹30,248 | 10-28 14:01 | LINE_STOP | 0 | **₹+196** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 09:20 | PFC | PFC 315 CE 2026-11-23 | ₹16,478 | 10-29 11:27 | LINE_STOP | 0 | **₹+613** |
| 10-29 11:15 | HDFCLIFE | HDFCLIFE 515 CE 2026-11-23 | ₹19,720 | 10-30 09:15 | LINE_STOP | 1 | **₹-3,247** |
| 10-29 11:30 | JINDALSTEL | JINDALSTEL 1060 PE 2026-11-23 | ₹19,569 | 10-29 12:09 | LINE_STOP | 0 | **₹-1,250** |
| 10-29 12:15 | SBILIFE | SBILIFE 1680 PE 2026-11-23 | ₹17,422 | 10-29 14:10 | LINE_STOP | 0 | **₹+2,224** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 11-02 09:15 | LINE_STOP | 3 | **₹-2,767** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 12:00 | ONGC | ONGC 224.5 CE 2026-11-23 | ₹5,886 | 10-30 12:00 | LINE_STOP | 0 | **₹-125** |
| 10-30 13:35 | JIOFIN | JIOFIN 207.5 PE 2026-11-23 | ₹15,879 | 11-02 09:15 | LINE_STOP | 3 | **₹-4,264** |
| 11-02 09:20 | BANKBARODA | BANKBARODA 245 CE 2026-11-23 | ₹24,432 | 11-03 09:17 | LINE_STOP | 1 | **₹-7,228** |
| 11-02 09:20 | POWERGRID | POWERGRID 267.5 CE 2026-11-23 | ₹10,938 | 11-02 10:13 | LINE_STOP | 0 | **₹-2,768** |
| 11-03 09:20 | ASIANPAINT | ASIANPAINT 2360 CE 2026-11-23 | ₹15,756 | 11-03 12:13 | LINE_STOP | 0 | **₹+6,794** |
| 11-03 12:30 | GAIL | GAIL 177.5 CE 2026-11-23 | ₹22,983 | 11-03 13:50 | LINE_STOP | 0 | **₹-1,050** |
| 11-03 13:40 | ITC | ITC 267.5 CE 2026-11-23 | ₹10,018 | 11-05 10:07 | LINE_STOP | 2 | **₹+12,235** |
| 11-03 13:55 | GRASIM | GRASIM 3080 CE 2026-11-23 | ₹19,607 | 11-03 14:24 | LINE_STOP | 0 | **₹-1,566** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 12:25 | HINDUNILVR | HINDUNILVR 1940 CE 2026-11-23 | ₹10,969 | 11-04 15:12 | LINE_STOP | 0 | **₹+819** |
| 11-04 13:50 | CIPLA | CIPLA 1390 CE 2026-11-23 | ₹12,298 | 11-05 09:15 | LINE_STOP | 1 | **₹+936** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-06 09:15 | LINE_STOP | 1 | **₹-5,892** |
| 11-05 11:50 | KOTAKBANK | KOTAKBANK 460 CE 2026-11-23 | ₹21,917 | 11-06 09:15 | LINE_STOP | 1 | **₹-960** |
| 11-06 09:20 | M&M | M&M 3150 CE 2026-11-23 | ₹19,412 | 11-09 09:16 | LINE_STOP | 3 | **₹+8,940** |
| 11-06 09:20 | TCS | TCS 2540 CE 2026-11-23 | ₹19,021 | 11-06 10:57 | LINE_STOP | 0 | **₹-6,538** |
| 11-06 12:05 | BEL | BEL 390 PE 2026-11-23 | ₹14,249 | 11-06 13:13 | LINE_STOP | 0 | **₹-2,827** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-11 12:35 | LINE_STOP | 2 | **₹+65,709** |
| 11-09 09:20 | GODREJCP | GODREJCP 850 PE 2026-11-23 | ₹11,034 | 11-09 11:19 | LINE_STOP | 0 | **₹-2,144** |
| 11-09 11:40 | COALINDIA | COALINDIA 400 CE 2026-11-23 | ₹10,431 | 11-09 13:25 | LINE_STOP | 0 | **₹-745** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-11 13:20 | ABB | ABB 6900 CE 2026-11-23 | ₹35,981 | 11-12 11:01 | LINE_STOP | 1 | **₹+1,380** |
| 11-11 13:45 | BOSCHLTD | BOSCHLTD 50000 CE 2026-11-23 | ₹31,562 | 11-11 15:11 | LINE_STOP | 0 | **₹-4,834** |
| 11-11 13:55 | HINDALCO | HINDALCO 970 PE 2026-11-23 | ₹17,852 | 11-12 09:16 | LINE_STOP | 1 | **₹-684** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | open | OPEN | 0 | **₹+167** |
| 11-12 11:05 | TVSMOTOR | TVSMOTOR 4600 PE 2026-11-23 | ₹21,731 | 11-12 14:02 | LINE_STOP | 0 | **₹+5,187** |

## ₹50,000 CAPITAL, always out by 15:15 (for comparison)

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 45** (4.1 per trading day with a trade)
- **Total net: ₹+34,418** · win rate 47% · avg win ₹+4,623 · avg loss ₹-2,611 · worst drawdown ₹-20,813
- Held overnight: 0 trades · still OPEN at the end (valued at the last price): 0
- Net by exit day: 10-28 ₹-5,247 · 10-29 ₹+18,267 · 10-30 ₹+3,874 · 11-02 ₹-7,134 · 11-03 ₹-2,611 · 11-04 ₹+1,542 · 11-05 ₹+508 · 11-06 ₹-4,656 · 11-09 ₹+32,468 · 11-11 ₹+668 · 11-12 ₹-3,262
- Skipped: 4 positions already open 3 · 5 trades already today 42 · not enough cash 337 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-28 12:00 | ETERNAL | ETERNAL 325 CE 2026-11-23 | ₹30,248 | 10-28 14:01 | LINE_STOP | 0 | **₹+196** |
| 10-29 09:20 | ADANIPORTS | ADANIPORTS 1780 CE 2026-11-23 | ₹27,274 | 10-29 15:15 | TIME_15:15 | 0 | **₹+20,667** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 13:40 | ITC | ITC 262.5 CE 2026-11-23 | ₹13,590 | 10-29 15:14 | LINE_STOP | 0 | **₹-204** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 10-30 15:15 | TIME_15:15 | 0 | **₹-1,272** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 09:20 | JINDALSTEL | JINDALSTEL 1080 PE 2026-11-23 | ₹26,292 | 10-30 10:21 | LINE_STOP | 0 | **₹-1,455** |
| 10-30 10:45 | NTPC | NTPC 310 CE 2026-11-23 | ₹10,529 | 10-30 13:43 | LINE_STOP | 0 | **₹+2,371** |
| 10-30 11:05 | HDFCBANK | HDFCBANK 680 CE 2026-11-23 | ₹12,375 | 10-30 13:46 | LINE_STOP | 0 | **₹+1,504** |
| 11-02 09:20 | BANKBARODA | BANKBARODA 245 CE 2026-11-23 | ₹24,432 | 11-02 15:15 | TIME_15:15 | 0 | **₹-5,638** |
| 11-02 09:20 | BAJAJ-AUTO | BAJAJ-AUTO 10400 CE 2026-11-23 | ₹20,748 | 11-02 09:22 | LINE_STOP | 0 | **₹-2,132** |
| 11-02 09:20 | TATAPOWER | TATAPOWER 345 CE 2026-11-23 | ₹17,574 | 11-02 13:07 | LINE_STOP | 0 | **₹+4,571** |
| 11-02 09:25 | DRREDDY | DRREDDY 1350 CE 2026-11-23 | ₹22,536 | 11-02 12:22 | LINE_STOP | 0 | **₹-3,939** |
| 11-02 12:55 | AXISBANK | AXISBANK 1220 PE 2026-11-23 | ₹17,265 | 11-02 15:15 | TIME_15:15 | 0 | **₹+3** |
| 11-03 09:20 | INDIGO | INDIGO 5000 CE 2026-11-23 | ₹27,656 | 11-03 12:46 | LINE_STOP | 0 | **₹-4,770** |
| 11-03 09:20 | ASIANPAINT | ASIANPAINT 2360 CE 2026-11-23 | ₹15,756 | 11-03 12:13 | LINE_STOP | 0 | **₹+6,794** |
| 11-03 09:20 | SUNPHARMA | SUNPHARMA 1780 PE 2026-11-23 | ₹15,200 | 11-03 10:31 | LINE_STOP | 0 | **₹-2,468** |
| 11-03 12:30 | GAIL | GAIL 177.5 CE 2026-11-23 | ₹22,983 | 11-03 13:50 | LINE_STOP | 0 | **₹-1,050** |
| 11-03 12:50 | AMBUJACEM | AMBUJACEM 365 CE 2026-11-23 | ₹16,241 | 11-03 14:24 | LINE_STOP | 0 | **₹-1,117** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 09:20 | GAIL | GAIL 180 CE 2026-11-23 | ₹21,621 | 11-04 12:20 | LINE_STOP | 0 | **₹-670** |
| 11-04 09:20 | HDFCLIFE | HDFCLIFE 525 CE 2026-11-23 | ₹15,943 | 11-04 10:32 | LINE_STOP | 0 | **₹+41** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 11:55 | CANBK | CANBK 118 PE 2026-11-23 | ₹21,134 | 11-04 13:32 | LINE_STOP | 0 | **₹-2,718** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-05 15:15 | TIME_15:15 | 0 | **₹+509** |
| 11-05 09:20 | TMPV | TMPV 285 CE 2026-11-23 | ₹20,362 | 11-05 14:20 | LINE_STOP | 0 | **₹+4,233** |
| 11-05 09:20 | GODREJCP | GODREJCP 870 CE 2026-11-23 | ₹13,130 | 11-05 15:10 | LINE_STOP | 0 | **₹-4,233** |
| 11-06 09:20 | M&M | M&M 3150 CE 2026-11-23 | ₹19,412 | 11-06 15:15 | TIME_15:15 | 0 | **₹+7,191** |
| 11-06 09:20 | TCS | TCS 2540 CE 2026-11-23 | ₹19,021 | 11-06 10:57 | LINE_STOP | 0 | **₹-6,538** |
| 11-06 09:20 | POWERGRID | POWERGRID 257.5 PE 2026-11-23 | ₹12,474 | 11-06 12:59 | LINE_STOP | 0 | **₹-2,482** |
| 11-06 12:05 | BEL | BEL 390 PE 2026-11-23 | ₹14,249 | 11-06 13:13 | LINE_STOP | 0 | **₹-2,827** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-09 15:15 | TIME_15:15 | 0 | **₹+29,426** |
| 11-09 09:20 | IOC | IOC 145 CE 2026-11-23 | ₹19,301 | 11-09 14:02 | LINE_STOP | 0 | **₹+3,042** |
| 11-11 09:20 | ENRIN | ENRIN 2900 CE 2026-11-23 | ₹22,474 | 11-11 14:57 | LINE_STOP | 0 | **₹-225** |
| 11-11 09:20 | KOTAKBANK | KOTAKBANK 480 CE 2026-11-23 | ₹21,210 | 11-11 12:11 | LINE_STOP | 0 | **₹+2,151** |
| 11-11 09:20 | BRITANNIA | BRITANNIA 4800 CE 2026-11-23 | ₹14,449 | 11-11 13:12 | LINE_STOP | 0 | **₹+115** |
| 11-11 09:20 | IOC | IOC 147 CE 2026-11-23 | ₹17,578 | 11-11 09:27 | LINE_STOP | 0 | **₹-1,400** |
| 11-11 09:35 | GAIL | GAIL 185 CE 2026-11-23 | ₹18,860 | 11-11 14:38 | LINE_STOP | 0 | **₹+26** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | BAJFINANCE | BAJFINANCE 1100 CE 2026-11-23 | ₹24,467 | 11-12 13:07 | LINE_STOP | 0 | **₹-5,258** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | 11-12 15:15 | TIME_15:15 | 0 | **₹+667** |

## ₹50,000: drawdown rules compared (each fixed before looking; same 11 days)

| version | trades | total net ₹ | worst drawdown ₹ | lowest balance ₹ | without the best trade ₹ | win rate |
|---|---|---|---|---|---|---|
| A. your rules (baseline) | 39 | ₹+55,223 | ₹-23,528 | ₹26,472 | ₹-10,486 | 41% |
| B. + premium stop: sell if the option trades 25 % below entry | 34 | ₹+47,197 | ₹-28,287 | ₹21,713 | ₹-18,512 | 38% |
| C. + daily loss stop ₹5,000 (10 % of capital) | 32 | ₹+55,384 | ₹-19,614 | ₹30,386 | ₹-10,325 | 41% |
| D. + max ₹15,000 premium per trade (30 % of capital) | 36 | ₹+36,143 | ₹-14,962 | ₹49,374 | ₹+2,532 | 39% |
| E. + after 2 losses in a row, no new trade until tomorrow | 32 | ₹+55,244 | ₹-19,614 | ₹30,386 | ₹-10,465 | 41% |
| F. all of B + C + D + E | 31 | ₹+43,057 | ₹-8,852 | ₹49,374 | ₹+9,446 | 42% |

## ₹50,000 · A. your rules (baseline)

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 39** (3.5 per trading day with a trade)
- **Total net: ₹+55,223** · win rate 41% · avg win ₹+7,423 · avg loss ₹-2,763 · worst drawdown ₹-23,528
- Held overnight: 12 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-28 ₹-5,247 · 10-29 ₹-609 · 10-30 ₹-645 · 11-02 ₹-9,799 · 11-03 ₹-3,050 · 11-04 ₹+5,709 · 11-05 ₹+13,171 · 11-06 ₹-16,217 · 11-09 ₹+6,051 · 11-11 ₹+58,483 · 11-12 ₹+7,377
- Skipped: 4 positions already open 1 · 5 trades already today 16 · no option trade at the exit 8 · not enough cash 363 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-28 12:00 | ETERNAL | ETERNAL 325 CE 2026-11-23 | ₹30,248 | 10-28 14:01 | LINE_STOP | 0 | **₹+196** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 09:20 | PFC | PFC 315 CE 2026-11-23 | ₹16,478 | 10-29 11:27 | LINE_STOP | 0 | **₹+613** |
| 10-29 11:15 | HDFCLIFE | HDFCLIFE 515 CE 2026-11-23 | ₹19,720 | 10-30 09:15 | LINE_STOP | 1 | **₹-3,247** |
| 10-29 11:30 | JINDALSTEL | JINDALSTEL 1060 PE 2026-11-23 | ₹19,569 | 10-29 12:09 | LINE_STOP | 0 | **₹-1,250** |
| 10-29 12:15 | SBILIFE | SBILIFE 1680 PE 2026-11-23 | ₹17,422 | 10-29 14:10 | LINE_STOP | 0 | **₹+2,224** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 11-02 09:15 | LINE_STOP | 3 | **₹-2,767** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 12:00 | ONGC | ONGC 224.5 CE 2026-11-23 | ₹5,886 | 10-30 12:00 | LINE_STOP | 0 | **₹-125** |
| 10-30 13:35 | JIOFIN | JIOFIN 207.5 PE 2026-11-23 | ₹15,879 | 11-02 09:15 | LINE_STOP | 3 | **₹-4,264** |
| 11-02 09:20 | BANKBARODA | BANKBARODA 245 CE 2026-11-23 | ₹24,432 | 11-03 09:17 | LINE_STOP | 1 | **₹-7,228** |
| 11-02 09:20 | POWERGRID | POWERGRID 267.5 CE 2026-11-23 | ₹10,938 | 11-02 10:13 | LINE_STOP | 0 | **₹-2,768** |
| 11-03 09:20 | ASIANPAINT | ASIANPAINT 2360 CE 2026-11-23 | ₹15,756 | 11-03 12:13 | LINE_STOP | 0 | **₹+6,794** |
| 11-03 12:30 | GAIL | GAIL 177.5 CE 2026-11-23 | ₹22,983 | 11-03 13:50 | LINE_STOP | 0 | **₹-1,050** |
| 11-03 13:40 | ITC | ITC 267.5 CE 2026-11-23 | ₹10,018 | 11-05 10:07 | LINE_STOP | 2 | **₹+12,235** |
| 11-03 13:55 | GRASIM | GRASIM 3080 CE 2026-11-23 | ₹19,607 | 11-03 14:24 | LINE_STOP | 0 | **₹-1,566** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 12:25 | HINDUNILVR | HINDUNILVR 1940 CE 2026-11-23 | ₹10,969 | 11-04 15:12 | LINE_STOP | 0 | **₹+819** |
| 11-04 13:50 | CIPLA | CIPLA 1390 CE 2026-11-23 | ₹12,298 | 11-05 09:15 | LINE_STOP | 1 | **₹+936** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-06 09:15 | LINE_STOP | 1 | **₹-5,892** |
| 11-05 11:50 | KOTAKBANK | KOTAKBANK 460 CE 2026-11-23 | ₹21,917 | 11-06 09:15 | LINE_STOP | 1 | **₹-960** |
| 11-06 09:20 | M&M | M&M 3150 CE 2026-11-23 | ₹19,412 | 11-09 09:16 | LINE_STOP | 3 | **₹+8,940** |
| 11-06 09:20 | TCS | TCS 2540 CE 2026-11-23 | ₹19,021 | 11-06 10:57 | LINE_STOP | 0 | **₹-6,538** |
| 11-06 12:05 | BEL | BEL 390 PE 2026-11-23 | ₹14,249 | 11-06 13:13 | LINE_STOP | 0 | **₹-2,827** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-11 12:35 | LINE_STOP | 2 | **₹+65,709** |
| 11-09 09:20 | GODREJCP | GODREJCP 850 PE 2026-11-23 | ₹11,034 | 11-09 11:19 | LINE_STOP | 0 | **₹-2,144** |
| 11-09 11:40 | COALINDIA | COALINDIA 400 CE 2026-11-23 | ₹10,431 | 11-09 13:25 | LINE_STOP | 0 | **₹-745** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-11 13:20 | ABB | ABB 6900 CE 2026-11-23 | ₹35,981 | 11-12 11:01 | LINE_STOP | 1 | **₹+1,380** |
| 11-11 13:45 | BOSCHLTD | BOSCHLTD 50000 CE 2026-11-23 | ₹31,562 | 11-11 15:11 | LINE_STOP | 0 | **₹-4,834** |
| 11-11 13:55 | HINDALCO | HINDALCO 970 PE 2026-11-23 | ₹17,852 | 11-12 09:16 | LINE_STOP | 1 | **₹-684** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | open | OPEN | 0 | **₹+167** |
| 11-12 11:05 | TVSMOTOR | TVSMOTOR 4600 PE 2026-11-23 | ₹21,731 | 11-12 14:02 | LINE_STOP | 0 | **₹+5,187** |

## ₹50,000 · B. + premium stop: sell if the option trades 25 % below entry

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 34** (3.1 per trading day with a trade)
- **Total net: ₹+47,197** · win rate 38% · avg win ₹+8,060 · avg loss ₹-2,742 · worst drawdown ₹-28,287
- Held overnight: 8 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-28 ₹-5,247 · 10-29 ₹-609 · 10-30 ₹-645 · 11-02 ₹-18,624 · 11-03 ₹+1,834 · 11-04 ₹+896 · 11-06 ₹-5,892 · 11-09 ₹+8,940 · 11-11 ₹+58,483 · 11-12 ₹+8,062
- Skipped: 4 positions already open 1 · 5 trades already today 16 · no option trade at the exit 8 · not enough cash 368 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-28 12:00 | ETERNAL | ETERNAL 325 CE 2026-11-23 | ₹30,248 | 10-28 14:01 | LINE_STOP | 0 | **₹+196** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 09:20 | PFC | PFC 315 CE 2026-11-23 | ₹16,478 | 10-29 11:27 | LINE_STOP | 0 | **₹+613** |
| 10-29 11:15 | HDFCLIFE | HDFCLIFE 515 CE 2026-11-23 | ₹19,720 | 10-30 09:15 | LINE_STOP | 1 | **₹-3,247** |
| 10-29 11:30 | JINDALSTEL | JINDALSTEL 1060 PE 2026-11-23 | ₹19,569 | 10-29 12:09 | LINE_STOP | 0 | **₹-1,250** |
| 10-29 12:15 | SBILIFE | SBILIFE 1680 PE 2026-11-23 | ₹17,422 | 10-29 14:10 | LINE_STOP | 0 | **₹+2,224** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 11-02 09:15 | LINE_STOP | 3 | **₹-2,767** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 12:00 | ONGC | ONGC 224.5 CE 2026-11-23 | ₹5,886 | 10-30 12:00 | LINE_STOP | 0 | **₹-125** |
| 10-30 13:35 | JIOFIN | JIOFIN 207.5 PE 2026-11-23 | ₹15,879 | 11-02 09:15 | LINE_STOP | 3 | **₹-4,264** |
| 11-02 09:20 | BANKBARODA | BANKBARODA 245 CE 2026-11-23 | ₹24,432 | 11-02 10:09 | PREMIUM_STOP_25% | 0 | **₹-6,498** |
| 11-02 09:20 | POWERGRID | POWERGRID 267.5 CE 2026-11-23 | ₹10,938 | 11-02 10:09 | PREMIUM_STOP_25% | 0 | **₹-2,909** |
| 11-02 10:10 | ADANIPORTS | ADANIPORTS 1860 PE 2026-11-23 | ₹25,523 | 11-02 12:15 | LINE_STOP | 0 | **₹-2,186** |
| 11-02 12:55 | AXISBANK | AXISBANK 1220 PE 2026-11-23 | ₹17,265 | 11-03 09:15 | LINE_STOP | 1 | **₹-2,344** |
| 11-03 09:20 | ASIANPAINT | ASIANPAINT 2360 CE 2026-11-23 | ₹15,756 | 11-03 12:13 | LINE_STOP | 0 | **₹+6,794** |
| 11-03 12:30 | GAIL | GAIL 177.5 CE 2026-11-23 | ₹22,983 | 11-03 13:50 | LINE_STOP | 0 | **₹-1,050** |
| 11-03 13:55 | GRASIM | GRASIM 3080 CE 2026-11-23 | ₹19,607 | 11-03 14:24 | LINE_STOP | 0 | **₹-1,566** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 11:55 | CANBK | CANBK 118 PE 2026-11-23 | ₹21,134 | 11-04 13:32 | LINE_STOP | 0 | **₹-2,718** |
| 11-04 13:40 | ASIANPAINT | ASIANPAINT 2400 CE 2026-11-23 | ₹16,955 | 11-04 15:02 | LINE_STOP | 0 | **₹-1,275** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-06 09:15 | LINE_STOP | 1 | **₹-5,892** |
| 11-06 09:20 | M&M | M&M 3150 CE 2026-11-23 | ₹19,412 | 11-09 09:16 | LINE_STOP | 3 | **₹+8,940** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-11 12:35 | LINE_STOP | 2 | **₹+65,709** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-11 13:20 | ABB | ABB 6900 CE 2026-11-23 | ₹35,981 | 11-12 11:01 | LINE_STOP | 1 | **₹+1,380** |
| 11-11 13:45 | BOSCHLTD | BOSCHLTD 50000 CE 2026-11-23 | ₹31,562 | 11-11 15:11 | LINE_STOP | 0 | **₹-4,834** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | open | OPEN | 0 | **₹+167** |
| 11-12 11:05 | TVSMOTOR | TVSMOTOR 4600 PE 2026-11-23 | ₹21,731 | 11-12 14:02 | LINE_STOP | 0 | **₹+5,187** |

## ₹50,000 · C. + daily loss stop ₹5,000 (10 % of capital)

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 32** (3.6 per trading day with a trade)
- **Total net: ₹+55,384** · win rate 41% · avg win ₹+7,911 · avg loss ₹-2,498 · worst drawdown ₹-19,614
- Held overnight: 10 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-28 ₹-5,443 · 10-29 ₹-609 · 10-30 ₹-645 · 11-02 ₹-7,031 · 11-03 ₹-5,886 · 11-04 ₹+5,709 · 11-05 ₹+13,171 · 11-06 ₹-6,852 · 11-09 ₹-2,889 · 11-11 ₹+58,483 · 11-12 ₹+7,377
- Skipped: 4 positions already open 1 · 5 trades already today 16 · daily loss stop (−₹5,000) hit 84 · no option trade at the exit 8 · not enough cash 286 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 09:20 | PFC | PFC 315 CE 2026-11-23 | ₹16,478 | 10-29 11:27 | LINE_STOP | 0 | **₹+613** |
| 10-29 11:15 | HDFCLIFE | HDFCLIFE 515 CE 2026-11-23 | ₹19,720 | 10-30 09:15 | LINE_STOP | 1 | **₹-3,247** |
| 10-29 11:30 | JINDALSTEL | JINDALSTEL 1060 PE 2026-11-23 | ₹19,569 | 10-29 12:09 | LINE_STOP | 0 | **₹-1,250** |
| 10-29 12:15 | SBILIFE | SBILIFE 1680 PE 2026-11-23 | ₹17,422 | 10-29 14:10 | LINE_STOP | 0 | **₹+2,224** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 11-02 09:15 | LINE_STOP | 3 | **₹-2,767** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 12:00 | ONGC | ONGC 224.5 CE 2026-11-23 | ₹5,886 | 10-30 12:00 | LINE_STOP | 0 | **₹-125** |
| 10-30 13:35 | JIOFIN | JIOFIN 207.5 PE 2026-11-23 | ₹15,879 | 11-02 09:15 | LINE_STOP | 3 | **₹-4,264** |
| 11-03 09:20 | INDIGO | INDIGO 5000 CE 2026-11-23 | ₹27,656 | 11-03 12:46 | LINE_STOP | 0 | **₹-4,770** |
| 11-03 12:50 | AMBUJACEM | AMBUJACEM 365 CE 2026-11-23 | ₹16,241 | 11-03 14:24 | LINE_STOP | 0 | **₹-1,117** |
| 11-03 13:40 | ITC | ITC 267.5 CE 2026-11-23 | ₹10,018 | 11-05 10:07 | LINE_STOP | 2 | **₹+12,235** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 12:25 | HINDUNILVR | HINDUNILVR 1940 CE 2026-11-23 | ₹10,969 | 11-04 15:12 | LINE_STOP | 0 | **₹+819** |
| 11-04 13:50 | CIPLA | CIPLA 1390 CE 2026-11-23 | ₹12,298 | 11-05 09:15 | LINE_STOP | 1 | **₹+936** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-06 09:15 | LINE_STOP | 1 | **₹-5,892** |
| 11-05 11:50 | KOTAKBANK | KOTAKBANK 460 CE 2026-11-23 | ₹21,917 | 11-06 09:15 | LINE_STOP | 1 | **₹-960** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-11 12:35 | LINE_STOP | 2 | **₹+65,709** |
| 11-09 09:20 | GODREJCP | GODREJCP 850 PE 2026-11-23 | ₹11,034 | 11-09 11:19 | LINE_STOP | 0 | **₹-2,144** |
| 11-09 11:40 | COALINDIA | COALINDIA 400 CE 2026-11-23 | ₹10,431 | 11-09 13:25 | LINE_STOP | 0 | **₹-745** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-11 13:20 | ABB | ABB 6900 CE 2026-11-23 | ₹35,981 | 11-12 11:01 | LINE_STOP | 1 | **₹+1,380** |
| 11-11 13:45 | BOSCHLTD | BOSCHLTD 50000 CE 2026-11-23 | ₹31,562 | 11-11 15:11 | LINE_STOP | 0 | **₹-4,834** |
| 11-11 13:55 | HINDALCO | HINDALCO 970 PE 2026-11-23 | ₹17,852 | 11-12 09:16 | LINE_STOP | 1 | **₹-684** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | open | OPEN | 0 | **₹+167** |
| 11-12 11:05 | TVSMOTOR | TVSMOTOR 4600 PE 2026-11-23 | ₹21,731 | 11-12 14:02 | LINE_STOP | 0 | **₹+5,187** |

## ₹50,000 · D. + max ₹15,000 premium per trade (30 % of capital)

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 36** (3.6 per trading day with a trade)
- **Total net: ₹+36,143** · win rate 39% · avg win ₹+4,918 · avg loss ₹-1,487 · worst drawdown ₹-14,962
- Held overnight: 6 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-29 ₹-204 · 10-30 ₹+2,983 · 11-02 ₹+2,444 · 11-04 ₹-1,753 · 11-05 ₹+8,937 · 11-06 ₹+3,322 · 11-09 ₹-6,861 · 11-11 ₹+30,469 · 11-12 ₹-3,194
- Skipped: 4 positions already open 12 · 5 trades already today 12 · no option trade at the exit 8 · not enough cash 4 · premium above ₹15,000 for 1 lot 358

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-29 13:40 | ITC | ITC 262.5 CE 2026-11-23 | ₹13,590 | 10-29 15:14 | LINE_STOP | 0 | **₹-204** |
| 10-30 09:35 | VEDL | VEDL 230 CE 2026-11-23 | ₹13,938 | 10-30 12:58 | LINE_STOP | 0 | **₹-296** |
| 10-30 10:45 | NTPC | NTPC 310 CE 2026-11-23 | ₹10,529 | 10-30 13:43 | LINE_STOP | 0 | **₹+2,371** |
| 10-30 11:05 | HDFCBANK | HDFCBANK 680 CE 2026-11-23 | ₹12,375 | 10-30 13:46 | LINE_STOP | 0 | **₹+1,504** |
| 10-30 12:00 | ONGC | ONGC 224.5 CE 2026-11-23 | ₹5,886 | 10-30 12:00 | LINE_STOP | 0 | **₹-125** |
| 10-30 13:05 | HINDUNILVR | HINDUNILVR 1840 CE 2026-11-23 | ₹11,650 | 10-30 15:12 | LINE_STOP | 0 | **₹-470** |
| 11-02 09:20 | POWERGRID | POWERGRID 267.5 CE 2026-11-23 | ₹10,938 | 11-02 10:13 | LINE_STOP | 0 | **₹-2,768** |
| 11-02 09:20 | VEDL | VEDL 235 CE 2026-11-23 | ₹12,126 | 11-02 14:54 | LINE_STOP | 0 | **₹+3,027** |
| 11-02 09:20 | HINDUNILVR | HINDUNILVR 1860 CE 2026-11-23 | ₹11,347 | 11-02 11:43 | LINE_STOP | 0 | **₹+1,894** |
| 11-02 13:10 | GODREJCP | GODREJCP 820 PE 2026-11-23 | ₹11,868 | 11-02 13:42 | LINE_STOP | 0 | **₹+291** |
| 11-03 13:40 | ITC | ITC 267.5 CE 2026-11-23 | ₹10,018 | 11-05 10:07 | LINE_STOP | 2 | **₹+12,235** |
| 11-04 09:50 | VEDL | VEDL 240 CE 2026-11-23 | ₹12,405 | 11-06 09:15 | LINE_STOP | 2 | **₹+10,558** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 12:25 | HINDUNILVR | HINDUNILVR 1940 CE 2026-11-23 | ₹10,969 | 11-04 15:12 | LINE_STOP | 0 | **₹+819** |
| 11-04 13:50 | CIPLA | CIPLA 1390 CE 2026-11-23 | ₹12,298 | 11-05 09:15 | LINE_STOP | 1 | **₹+936** |
| 11-05 09:20 | GODREJCP | GODREJCP 870 CE 2026-11-23 | ₹13,130 | 11-05 15:10 | LINE_STOP | 0 | **₹-4,233** |
| 11-05 09:20 | PFC | PFC 320 CE 2026-11-23 | ₹12,277 | 11-06 09:15 | LINE_STOP | 1 | **₹-454** |
| 11-05 13:25 | AMBUJACEM | AMBUJACEM 385 CE 2026-11-23 | ₹14,908 | 11-06 09:15 | LINE_STOP | 1 | **₹-673** |
| 11-06 09:20 | POWERGRID | POWERGRID 257.5 PE 2026-11-23 | ₹12,474 | 11-06 12:59 | LINE_STOP | 0 | **₹-2,482** |
| 11-06 09:20 | COALINDIA | COALINDIA 395 PE 2026-11-23 | ₹9,954 | 11-06 10:09 | LINE_STOP | 0 | **₹-2,202** |
| 11-06 09:20 | RELIANCE | RELIANCE 1310 PE 2026-11-23 | ₹12,978 | 11-06 09:45 | LINE_STOP | 0 | **₹-927** |
| 11-06 09:30 | TORNTPHARM | TORNTPHARM 4700 CE 2026-11-23 | ₹14,853 | 11-06 12:07 | LINE_STOP | 0 | **₹+38** |
| 11-06 09:45 | ITC | ITC 277.5 CE 2026-11-23 | ₹10,541 | 11-06 11:22 | LINE_STOP | 0 | **₹-536** |
| 11-09 09:20 | GODREJCP | GODREJCP 850 PE 2026-11-23 | ₹11,034 | 11-09 11:19 | LINE_STOP | 0 | **₹-2,144** |
| 11-09 09:20 | INFY | INFY 1160 PE 2026-11-23 | ₹13,473 | 11-09 13:53 | LINE_STOP | 0 | **₹-69** |
| 11-09 10:05 | TATACONSUM | TATACONSUM 1080 CE 2026-11-23 | ₹13,860 | 11-09 10:52 | LINE_STOP | 0 | **₹-1,903** |
| 11-09 10:25 | CIPLA | CIPLA 1410 CE 2026-11-23 | ₹13,736 | 11-09 11:22 | LINE_STOP | 0 | **₹-2,745** |
| 11-09 10:55 | IRFC | IRFC 80 CE 2026-11-23 | ₹12,328 | 11-11 12:10 | LINE_STOP | 2 | **₹+33,611** |
| 11-11 09:20 | BRITANNIA | BRITANNIA 4800 CE 2026-11-23 | ₹14,449 | 11-11 13:12 | LINE_STOP | 0 | **₹+115** |
| 11-11 09:20 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,165 | 11-11 11:10 | LINE_STOP | 0 | **₹-865** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 09:20 | TATACONSUM | TATACONSUM 1080 CE 2026-11-23 | ₹14,026 | 11-12 10:57 | LINE_STOP | 0 | **₹-1,934** |
| 11-12 09:20 | SUNPHARMA | SUNPHARMA 1900 PE 2026-11-23 | ₹12,691 | 11-12 12:59 | LINE_STOP | 0 | **₹-657** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | open | OPEN | 0 | **₹+167** |

## ₹50,000 · E. + after 2 losses in a row, no new trade until tomorrow

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 32** (3.6 per trading day with a trade)
- **Total net: ₹+55,244** · win rate 41% · avg win ₹+7,900 · avg loss ₹-2,498 · worst drawdown ₹-19,614
- Held overnight: 10 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-28 ₹-5,443 · 10-29 ₹-609 · 10-30 ₹-645 · 11-02 ₹-7,031 · 11-03 ₹-5,886 · 11-04 ₹+5,709 · 11-05 ₹+13,171 · 11-06 ₹-6,852 · 11-09 ₹-2,889 · 11-11 ₹+58,483 · 11-12 ₹+7,237
- Skipped: 2 losses in a row today 86 · 5 trades already today 16 · no option trade at the exit 8 · not enough cash 285 · premium above ₹50,000 for 1 lot 3

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-28 09:20 | HDFCLIFE | HDFCLIFE 515 PE 2026-11-23 | ₹17,554 | 10-28 11:20 | LINE_STOP | 0 | **₹-2,276** |
| 10-28 09:20 | ASIANPAINT | ASIANPAINT 2260 PE 2026-11-23 | ₹19,897 | 10-28 11:24 | LINE_STOP | 0 | **₹-3,166** |
| 10-29 09:20 | BAJAJFINSV | BAJAJFINSV 1660 PE 2026-11-23 | ₹15,423 | 10-29 10:45 | LINE_STOP | 0 | **₹-2,196** |
| 10-29 09:20 | PFC | PFC 315 CE 2026-11-23 | ₹16,478 | 10-29 11:27 | LINE_STOP | 0 | **₹+613** |
| 10-29 11:15 | HDFCLIFE | HDFCLIFE 515 CE 2026-11-23 | ₹19,720 | 10-30 09:15 | LINE_STOP | 1 | **₹-3,247** |
| 10-29 11:30 | JINDALSTEL | JINDALSTEL 1060 PE 2026-11-23 | ₹19,569 | 10-29 12:09 | LINE_STOP | 0 | **₹-1,250** |
| 10-29 12:15 | SBILIFE | SBILIFE 1680 PE 2026-11-23 | ₹17,422 | 10-29 14:10 | LINE_STOP | 0 | **₹+2,224** |
| 10-30 09:20 | TATASTEEL | TATASTEEL 170 PE 2026-11-23 | ₹16,359 | 11-02 09:15 | LINE_STOP | 3 | **₹-2,767** |
| 10-30 09:20 | TORNTPHARM | TORNTPHARM 4550 CE 2026-11-23 | ₹16,438 | 10-30 13:28 | LINE_STOP | 0 | **₹+2,727** |
| 10-30 12:00 | ONGC | ONGC 224.5 CE 2026-11-23 | ₹5,886 | 10-30 12:00 | LINE_STOP | 0 | **₹-125** |
| 10-30 13:35 | JIOFIN | JIOFIN 207.5 PE 2026-11-23 | ₹15,879 | 11-02 09:15 | LINE_STOP | 3 | **₹-4,264** |
| 11-03 09:20 | INDIGO | INDIGO 5000 CE 2026-11-23 | ₹27,656 | 11-03 12:46 | LINE_STOP | 0 | **₹-4,770** |
| 11-03 12:50 | AMBUJACEM | AMBUJACEM 365 CE 2026-11-23 | ₹16,241 | 11-03 14:24 | LINE_STOP | 0 | **₹-1,117** |
| 11-03 13:40 | ITC | ITC 267.5 CE 2026-11-23 | ₹10,018 | 11-05 10:07 | LINE_STOP | 2 | **₹+12,235** |
| 11-04 09:20 | BAJAJFINSV | BAJAJFINSV 1700 CE 2026-11-23 | ₹15,877 | 11-04 10:58 | LINE_STOP | 0 | **₹+7,462** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 12:25 | HINDUNILVR | HINDUNILVR 1940 CE 2026-11-23 | ₹10,969 | 11-04 15:12 | LINE_STOP | 0 | **₹+819** |
| 11-04 13:50 | CIPLA | CIPLA 1390 CE 2026-11-23 | ₹12,298 | 11-05 09:15 | LINE_STOP | 1 | **₹+936** |
| 11-05 09:20 | ASIANPAINT | ASIANPAINT 2500 CE 2026-11-23 | ₹17,322 | 11-06 09:15 | LINE_STOP | 1 | **₹-5,892** |
| 11-05 11:50 | KOTAKBANK | KOTAKBANK 460 CE 2026-11-23 | ₹21,917 | 11-06 09:15 | LINE_STOP | 1 | **₹-960** |
| 11-09 09:20 | PNB | PNB 126 CE 2026-11-23 | ₹29,088 | 11-11 12:35 | LINE_STOP | 2 | **₹+65,709** |
| 11-09 09:20 | GODREJCP | GODREJCP 850 PE 2026-11-23 | ₹11,034 | 11-09 11:19 | LINE_STOP | 0 | **₹-2,144** |
| 11-09 11:40 | COALINDIA | COALINDIA 400 CE 2026-11-23 | ₹10,431 | 11-09 13:25 | LINE_STOP | 0 | **₹-745** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-11 13:20 | ABB | ABB 6900 CE 2026-11-23 | ₹35,981 | 11-12 11:01 | LINE_STOP | 1 | **₹+1,380** |
| 11-11 13:45 | BOSCHLTD | BOSCHLTD 50000 CE 2026-11-23 | ₹31,562 | 11-11 15:11 | LINE_STOP | 0 | **₹-4,834** |
| 11-11 13:55 | HINDALCO | HINDALCO 970 PE 2026-11-23 | ₹17,852 | 11-12 09:16 | LINE_STOP | 1 | **₹-684** |
| 11-12 09:20 | ENRIN | ENRIN 2950 CE 2026-11-23 | ₹24,109 | 11-12 11:18 | LINE_STOP | 0 | **₹+2,099** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 11:05 | TVSMOTOR | TVSMOTOR 4600 PE 2026-11-23 | ₹21,731 | 11-12 14:02 | LINE_STOP | 0 | **₹+5,187** |
| 11-12 11:10 | BRITANNIA | BRITANNIA 4850 PE 2026-11-23 | ₹13,932 | open | OPEN | 0 | **₹+27** |

## ₹50,000 · F. all of B + C + D + E

- Candidates (5m flip before 14:00 with 15m agreeing): 430; **taken: 31** (3.4 per trading day with a trade)
- **Total net: ₹+43,057** · win rate 42% · avg win ₹+5,294 · avg loss ₹-1,431 · worst drawdown ₹-8,852
- Held overnight: 6 trades · still OPEN at the end (valued at the last price): 1
- Net by exit day: 10-29 ₹-204 · 10-30 ₹+3,453 · 11-02 ₹+2,303 · 11-04 ₹-1,753 · 11-05 ₹+9,412 · 11-06 ₹+9,431 · 11-09 ₹-6,861 · 11-11 ₹+30,469 · 11-12 ₹-3,194
- Skipped: 2 losses in a row today 14 · 4 positions already open 7 · 5 trades already today 9 · no option trade at the exit 8 · not enough cash 3 · premium above ₹15,000 for 1 lot 358

| entry | stock | option | premium (1 lot) | exit | why | nights | net ₹ |
|---|---|---|---|---|---|---|---|
| 10-29 13:40 | ITC | ITC 262.5 CE 2026-11-23 | ₹13,590 | 10-29 15:14 | LINE_STOP | 0 | **₹-204** |
| 10-30 09:35 | VEDL | VEDL 230 CE 2026-11-23 | ₹13,938 | 10-30 12:58 | LINE_STOP | 0 | **₹-296** |
| 10-30 10:45 | NTPC | NTPC 310 CE 2026-11-23 | ₹10,529 | 10-30 13:43 | LINE_STOP | 0 | **₹+2,371** |
| 10-30 11:05 | HDFCBANK | HDFCBANK 680 CE 2026-11-23 | ₹12,375 | 10-30 13:46 | LINE_STOP | 0 | **₹+1,504** |
| 10-30 12:00 | ONGC | ONGC 224.5 CE 2026-11-23 | ₹5,886 | 10-30 12:00 | LINE_STOP | 0 | **₹-125** |
| 11-02 09:20 | POWERGRID | POWERGRID 267.5 CE 2026-11-23 | ₹10,938 | 11-02 10:09 | PREMIUM_STOP_25% | 0 | **₹-2,909** |
| 11-02 09:20 | VEDL | VEDL 235 CE 2026-11-23 | ₹12,126 | 11-02 14:54 | LINE_STOP | 0 | **₹+3,027** |
| 11-02 09:20 | HINDUNILVR | HINDUNILVR 1860 CE 2026-11-23 | ₹11,347 | 11-02 11:43 | LINE_STOP | 0 | **₹+1,894** |
| 11-02 13:10 | GODREJCP | GODREJCP 820 PE 2026-11-23 | ₹11,868 | 11-02 13:42 | LINE_STOP | 0 | **₹+291** |
| 11-03 13:40 | ITC | ITC 267.5 CE 2026-11-23 | ₹10,018 | 11-05 10:07 | LINE_STOP | 2 | **₹+12,235** |
| 11-04 09:50 | VEDL | VEDL 240 CE 2026-11-23 | ₹12,405 | 11-06 09:15 | LINE_STOP | 2 | **₹+10,558** |
| 11-04 11:05 | NTPC | NTPC 320 PE 2026-11-23 | ₹12,878 | 11-04 13:39 | LINE_STOP | 0 | **₹-2,572** |
| 11-04 12:25 | HINDUNILVR | HINDUNILVR 1940 CE 2026-11-23 | ₹10,969 | 11-04 15:12 | LINE_STOP | 0 | **₹+819** |
| 11-04 13:50 | CIPLA | CIPLA 1390 CE 2026-11-23 | ₹12,298 | 11-05 09:15 | LINE_STOP | 1 | **₹+936** |
| 11-05 09:20 | GODREJCP | GODREJCP 870 CE 2026-11-23 | ₹13,130 | 11-05 09:40 | PREMIUM_STOP_25% | 0 | **₹-3,492** |
| 11-05 09:20 | PFC | PFC 320 CE 2026-11-23 | ₹12,277 | 11-06 09:15 | LINE_STOP | 1 | **₹-454** |
| 11-05 13:25 | AMBUJACEM | AMBUJACEM 385 CE 2026-11-23 | ₹14,908 | 11-06 09:15 | LINE_STOP | 1 | **₹-673** |
| 11-05 13:30 | TORNTPHARM | TORNTPHARM 4700 CE 2026-11-23 | ₹14,292 | 11-05 15:05 | LINE_STOP | 0 | **₹-267** |
| 11-09 09:20 | GODREJCP | GODREJCP 850 PE 2026-11-23 | ₹11,034 | 11-09 11:19 | LINE_STOP | 0 | **₹-2,144** |
| 11-09 09:20 | INFY | INFY 1160 PE 2026-11-23 | ₹13,473 | 11-09 13:53 | LINE_STOP | 0 | **₹-69** |
| 11-09 10:05 | TATACONSUM | TATACONSUM 1080 CE 2026-11-23 | ₹13,860 | 11-09 10:52 | LINE_STOP | 0 | **₹-1,903** |
| 11-09 10:25 | CIPLA | CIPLA 1410 CE 2026-11-23 | ₹13,736 | 11-09 11:22 | LINE_STOP | 0 | **₹-2,745** |
| 11-09 10:55 | IRFC | IRFC 80 CE 2026-11-23 | ₹12,328 | 11-11 12:10 | LINE_STOP | 2 | **₹+33,611** |
| 11-11 09:20 | BRITANNIA | BRITANNIA 4800 CE 2026-11-23 | ₹14,449 | 11-11 13:12 | LINE_STOP | 0 | **₹+115** |
| 11-11 09:20 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,165 | 11-11 11:10 | LINE_STOP | 0 | **₹-865** |
| 11-11 13:15 | CIPLA | CIPLA 1400 CE 2026-11-23 | ₹14,874 | 11-11 15:01 | LINE_STOP | 0 | **₹-2,392** |
| 11-12 09:20 | BAJAJFINSV | BAJAJFINSV 1860 CE 2026-11-23 | ₹14,014 | 11-12 11:27 | LINE_STOP | 0 | **₹+1,288** |
| 11-12 09:20 | PFC | PFC 340 CE 2026-11-23 | ₹12,539 | 11-12 10:26 | LINE_STOP | 0 | **₹-2,059** |
| 11-12 09:20 | TATACONSUM | TATACONSUM 1080 CE 2026-11-23 | ₹14,026 | 11-12 10:57 | LINE_STOP | 0 | **₹-1,934** |
| 11-12 09:20 | SUNPHARMA | SUNPHARMA 1900 PE 2026-11-23 | ₹12,691 | 11-12 12:59 | LINE_STOP | 0 | **₹-657** |
| 11-12 10:55 | TCS | TCS 2460 PE 2026-11-23 | ₹12,919 | open | OPEN | 0 | **₹+167** |
