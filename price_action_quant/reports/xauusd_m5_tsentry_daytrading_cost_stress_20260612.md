# XAUUSD TSEntry M5 - Stress test costi e slippage - 2026-06-12

## Metodo

- Trade list: `data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv`
- Capitale iniziale: `50.000$`
- Rischio fisso: `1%`, quindi `1R = 500$`
- Costo in R per trade: `(spread_points + slippage_points) * 0.01 / abs(entry-stop) + commission_r`
- Il costo viene sottratto da ogni `result_r` della trade list originale.
- DD giornaliero e DD massimo sono drawdown realizzati su trade chiusi, non floating tick-by-tick.

## Scenari costo

| Scenario | Spread pts | Slippage pts | Commissione R | Descrizione |
| --- | ---: | ---: | ---: | --- |
| Zero costi | 0 | 0 | 0.00 | baseline teorico già usato nei backtest precedenti |
| Basso | 20 | 5 | 0.01 | spread 0.20$, slippage 0.05$, commissione 0.01R |
| Medio | 40 | 10 | 0.02 | spread 0.40$, slippage 0.10$, commissione 0.02R |
| Severo | 80 | 20 | 0.04 | spread 0.80$, slippage 0.20$, commissione 0.04R |

## Full 2021-2026

| Scenario | Famiglia | Trade | Winrate | PF | Avg costo R | Expectancy R | DD giornaliero | DD max | Capitale finale |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Zero costi | Aggressiva/filtrata | 236 | 61.02% | 4.22 | 0.000 | 1.229 | $-500 | $-4,161 | $195,073 |
| Zero costi | Conservativa strutturale | 222 | 59.46% | 3.33 | 0.000 | 0.885 | $-1,000 | $-3,000 | $148,289 |
| Basso | Aggressiva/filtrata | 236 | 58.90% | 3.43 | 0.147 | 1.083 | $-644 | $-4,823 | $177,784 |
| Basso | Conservativa strutturale | 222 | 57.66% | 2.85 | 0.101 | 0.785 | $-1,160 | $-3,320 | $137,106 |
| Medio | Aggressiva/filtrata | 236 | 57.63% | 2.84 | 0.293 | 0.936 | $-789 | $-5,485 | $160,495 |
| Medio | Conservativa strutturale | 222 | 57.21% | 2.46 | 0.202 | 0.684 | $-1,357 | $-4,147 | $125,923 |
| Severo | Aggressiva/filtrata | 236 | 57.20% | 2.00 | 0.586 | 0.643 | $-1,077 | $-6,809 | $125,917 |
| Severo | Conservativa strutturale | 222 | 55.41% | 1.87 | 0.403 | 0.482 | $-1,752 | $-5,871 | $103,556 |

## OOS 2024-2026

| Scenario | Famiglia | Trade | Winrate | PF | Avg costo R | Expectancy R | DD giornaliero | DD max | Capitale finale |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Zero costi | Aggressiva/filtrata | 94 | 64.89% | 5.81 | 0.000 | 1.688 | $-500 | $-1,500 | $129,323 |
| Zero costi | Conservativa strutturale | 107 | 59.81% | 3.60 | 0.000 | 1.022 | $-1,000 | $-2,186 | $104,668 |
| Basso | Aggressiva/filtrata | 94 | 63.83% | 4.97 | 0.120 | 1.568 | $-630 | $-1,655 | $123,675 |
| Basso | Conservativa strutturale | 107 | 57.94% | 3.17 | 0.088 | 0.934 | $-1,147 | $-2,587 | $99,950 |
| Medio | Aggressiva/filtrata | 94 | 61.70% | 4.28 | 0.240 | 1.447 | $-760 | $-1,811 | $118,027 |
| Medio | Conservativa strutturale | 107 | 57.94% | 2.81 | 0.176 | 0.845 | $-1,295 | $-2,987 | $95,232 |
| Severo | Aggressiva/filtrata | 94 | 61.70% | 3.26 | 0.481 | 1.207 | $-1,020 | $-2,247 | $106,731 |
| Severo | Conservativa strutturale | 107 | 55.14% | 2.23 | 0.353 | 0.669 | $-1,589 | $-3,788 | $85,795 |

## IS 2021-2023

| Scenario | Famiglia | Trade | Winrate | PF | Avg costo R | Expectancy R | DD giornaliero | DD max | Capitale finale |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Zero costi | Aggressiva/filtrata | 142 | 58.45% | 3.30 | 0.000 | 0.926 | $-500 | $-4,161 | $115,750 |
| Zero costi | Conservativa strutturale | 115 | 59.13% | 3.05 | 0.000 | 0.759 | $-1,000 | $-3,000 | $93,621 |
| Basso | Aggressiva/filtrata | 142 | 55.63% | 2.60 | 0.164 | 0.762 | $-644 | $-4,823 | $104,109 |
| Basso | Conservativa strutturale | 115 | 57.39% | 2.55 | 0.112 | 0.646 | $-1,160 | $-3,320 | $87,156 |
| Medio | Aggressiva/filtrata | 142 | 54.93% | 2.08 | 0.328 | 0.598 | $-789 | $-5,485 | $92,468 |
| Medio | Conservativa strutturale | 115 | 56.52% | 2.14 | 0.225 | 0.534 | $-1,357 | $-4,147 | $80,691 |
| Severo | Aggressiva/filtrata | 142 | 54.23% | 1.38 | 0.656 | 0.270 | $-1,077 | $-6,809 | $69,186 |
| Severo | Conservativa strutturale | 115 | 55.65% | 1.54 | 0.450 | 0.309 | $-1,752 | $-5,871 | $67,762 |

## Lettura

- Aggressiva/filtrata: scenario medio full expectancy 0.936R / PF 2.84; scenario severo OOS expectancy 1.207R / PF 3.26.
- Conservativa strutturale: scenario medio full expectancy 0.684R / PF 2.46; scenario severo OOS expectancy 0.669R / PF 2.23.
- Entrambe le famiglie restano positive anche nello scenario severo OOS.
- La famiglia aggressiva/filtrata mantiene metriche migliori in OOS anche dopo costi severi, ma resta piu sensibile ai costi perche usa buffer/stop medi piu stretti.
- Prima della demo MT5 va sostituita questa griglia teorica con spread/commissioni reali Vantage/Ultima/StarTrader/XM.

## Output locale

- CSV ignorato: `data/backtests/TSENTRY_XAUUSD_M5_daytrading_cost_stress_20260612.csv`
