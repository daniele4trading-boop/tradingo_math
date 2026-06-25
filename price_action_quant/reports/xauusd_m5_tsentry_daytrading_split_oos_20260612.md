# XAUUSD TSEntry Daytrading M5 Split / OOS Validation - 2026-06-12

## Purpose

Validate two selected TSEntry daytrading families on chronological splits after the initial optimization pass.

## Data and assumptions

- Primary data: `data/backtests/XAUUSD_M5_dukascopy_2021_2026.csv`
- SMT data: `data/backtests/XAGUSD_M5_dukascopy_2021_2026.csv`
- Source: Dukascopy BID OHLC
- Coverage: approximately 2021-01-03 23:00 UTC -> 2026-06-08 00:00 UTC
- Risk normalization: 1% per trade on 100,000 starting equity
- DD giornaliero: realized closed-trade drawdown by New York calendar day, not tick-level floating equity
- DD massimo: realized closed-trade equity curve drawdown over each split
- Costs: no explicit commission/slippage beyond sweep buffer

## Families tested

| Family | SMT | Buffer | Max consecutive daily losses |
| --- | --- | ---: | ---: |
| Aggressiva/filtrata | yes | 40 | 1 |
| Conservativa strutturale | no | 80 | 2 |

## Main split comparison

| Split | Family | Trades | Winrate | PF | DD giornaliero | DD max | Expectancy R | Total R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full 2021-2026 | Aggressiva/filtrata | 236 | 61.02% | 4.22 | -1000 | -8321 | 1.229 | 290.15 |
| Full 2021-2026 | Conservativa strutturale | 222 | 59.46% | 3.33 | -2000 | -6000 | 0.885 | 196.58 |
| IS 2021-2023 | Aggressiva/filtrata | 142 | 58.45% | 3.30 | -1000 | -8321 | 0.926 | 131.50 |
| IS 2021-2023 | Conservativa strutturale | 115 | 59.13% | 3.05 | -2000 | -6000 | 0.759 | 87.24 |
| OOS 2024-2026 | Aggressiva/filtrata | 94 | 64.89% | 5.81 | -1000 | -2219 | 1.688 | 158.65 |
| OOS 2024-2026 | Conservativa strutturale | 107 | 59.81% | 3.60 | -2000 | -3035 | 1.022 | 109.34 |

## Yearly / YTD stability

| Split | Family | Trades | Winrate | PF | DD giornaliero | DD max | Expectancy R | Total R |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2021 | Aggressiva/filtrata | 40 | 42.50% | 1.65 | -1000 | -8321 | 0.373 | 14.93 |
| 2021 | Conservativa strutturale | 42 | 50.00% | 2.20 | -2000 | -6000 | 0.524 | 22.03 |
| 2022 | Aggressiva/filtrata | 45 | 64.44% | 5.13 | -1000 | -4418 | 1.300 | 58.52 |
| 2022 | Conservativa strutturale | 41 | 68.29% | 5.28 | -2000 | -3000 | 1.163 | 47.67 |
| 2023 | Aggressiva/filtrata | 57 | 64.91% | 3.90 | -1000 | -6000 | 1.019 | 58.06 |
| 2023 | Conservativa strutturale | 32 | 59.38% | 2.35 | -2000 | -3498 | 0.548 | 17.55 |
| 2024 | Aggressiva/filtrata | 48 | 68.75% | 5.78 | -1000 | -2000 | 1.492 | 71.63 |
| 2024 | Conservativa strutturale | 50 | 66.00% | 3.64 | -2000 | -2372 | 0.899 | 44.93 |
| 2025 | Aggressiva/filtrata | 37 | 62.16% | 5.63 | -1000 | -2219 | 1.753 | 64.85 |
| 2025 | Conservativa strutturale | 44 | 56.82% | 4.00 | -2000 | -3035 | 1.228 | 54.02 |
| 2026 YTD | Aggressiva/filtrata | 9 | 55.56% | 6.54 | -1000 | -2000 | 2.463 | 22.17 |
| 2026 YTD | Conservativa strutturale | 13 | 46.15% | 2.48 | -2000 | -3000 | 0.799 | 10.38 |

## Read

- Aggressiva/filtrata: IS expectancy 0.926R / PF 3.30; OOS expectancy 1.688R / PF 5.81.
- Conservativa strutturale: IS expectancy 0.759R / PF 3.05; OOS expectancy 1.022R / PF 3.60.
- Both families remain positive in OOS. The aggressive/filtered family has higher OOS expectancy and PF, but its yearly 2021 split is weaker than the conservative family.
- The conservative family is smoother in 2021 and has a lower full-sample max DD, while the aggressive family has better OOS quality metrics after 2024.

## Local ignored outputs

- `data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_20260612.csv`
- `data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv`
