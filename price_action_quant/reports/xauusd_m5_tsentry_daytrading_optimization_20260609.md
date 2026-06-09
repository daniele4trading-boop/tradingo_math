# XAUUSD TSEntry Daytrading M5 Optimization - 2026-06-09

Dataset: `data/backtests/XAUUSD_M5_dukascopy_2021_2026.csv`

SMT dataset: `data/backtests/XAGUSD_M5_dukascopy_2021_2026.csv`

Source: Dukascopy BID OHLC, approximately 2021-01-03 23:00 UTC -> 2026-06-08 00:00 UTC.

Assumptions: risk 1%, point size 0.01, no explicit commission/slippage beyond sweep buffer, NY-day loss circuit breaker.

## Ranked optimization table

| Rank | SMT | Buffer pts | Max daily loss streak | Trades | Winrate | PF | Daily DD | Max DD | Expectancy R | Total R |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | smt | 40 | 1 | 236 | 61.02% | 4.22 | -1000 | -8321 | 1.229 | 290.15 |
| 2 | base | 40 | 1 | 255 | 56.47% | 3.47 | -1000 | -8321 | 1.067 | 272.03 |
| 3 | smt | 60 | 1 | 184 | 60.87% | 3.65 | -1000 | -8210 | 0.995 | 183.01 |
| 4 | base | 60 | 1 | 212 | 59.91% | 3.48 | -1000 | -7356 | 0.971 | 205.87 |
| 5 | base | 120 | 1 | 104 | 67.31% | 4.17 | -1000 | -4113 | 0.954 | 99.20 |
| 6 | smt | 40 | 2 | 315 | 53.97% | 3.10 | -2163 | -14049 | 0.932 | 293.52 |
| 7 | smt | 120 | 1 | 86 | 65.12% | 3.91 | -1000 | -3113 | 0.925 | 79.51 |
| 8 | smt | 80 | 1 | 141 | 61.70% | 3.52 | -1000 | -6701 | 0.917 | 129.27 |
| 9 | base | 40 | 2 | 379 | 52.77% | 2.98 | -3000 | -14049 | 0.906 | 343.45 |
| 10 | base | 80 | 2 | 222 | 59.46% | 3.33 | -2000 | -6000 | 0.885 | 196.58 |
| 11 | base | 80 | 1 | 168 | 61.31% | 3.40 | -1000 | -6895 | 0.877 | 147.36 |
| 12 | smt | 80 | 2 | 179 | 58.66% | 3.27 | -2000 | -6000 | 0.870 | 155.68 |
| 13 | smt | 40 | 3 | 357 | 52.10% | 2.84 | -4000 | -13565 | 0.850 | 303.39 |
| 14 | base | 40 | 3 | 437 | 51.72% | 2.80 | -4000 | -14565 | 0.842 | 368.05 |
| 15 | smt | 80 | 3 | 197 | 57.36% | 3.11 | -3000 | -5941 | 0.832 | 163.85 |
| 16 | base | 80 | 3 | 244 | 57.79% | 3.08 | -3736 | -6941 | 0.825 | 201.18 |
| 17 | smt | 120 | 2 | 101 | 62.38% | 3.46 | -2000 | -3540 | 0.818 | 82.64 |
| 18 | base | 60 | 2 | 286 | 54.90% | 2.89 | -3000 | -11269 | 0.816 | 233.26 |
| 19 | base | 120 | 2 | 122 | 63.11% | 3.40 | -2000 | -3000 | 0.801 | 97.68 |
| 20 | base | 120 | 3 | 132 | 62.12% | 3.32 | -3000 | -4000 | 0.788 | 103.98 |
| 21 | base | 60 | 3 | 328 | 53.96% | 2.77 | -3708 | -14159 | 0.779 | 255.63 |
| 22 | smt | 120 | 3 | 109 | 60.55% | 3.21 | -3000 | -4540 | 0.766 | 83.46 |
| 23 | smt | 60 | 2 | 237 | 54.43% | 2.78 | -2000 | -11122 | 0.763 | 180.78 |
| 24 | smt | 60 | 3 | 268 | 53.36% | 2.73 | -3000 | -13012 | 0.758 | 203.24 |

## Read

- Best expectancy row: SMT `smt`, buffer 40, max daily loss streak 1, expectancy 1.229R, PF 4.22, trades 236.
- Prior baseline (base, buffer 80, loss streak 2): 222 trades, winrate 59.46%, PF 3.33, daily DD -2000, max DD -6000, expectancy 0.885R.
- Daily DD is realized closed-trade drawdown by New York calendar day, not tick-level intraday equity drawdown.
- Max DD is realized closed-trade equity-curve drawdown over the full sample.

Detailed CSV output is local/ignored: `data/backtests/TSENTRY_XAUUSD_M5_daytrading_daily_optimization_20260609.csv`.
