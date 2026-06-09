# TSEntry CSV Backtest - XAUUSD H1

## Data used

- Primary file: `data/backtests/XAUUSD_H1_dukascopy_2021_2026.csv`
- Symbol: `XAUUSD`
- Timeframe: `H1`
- Source: `dukascopy`
- Period: 2021-01-03 23:00 UTC -> 2026-06-08 00:00 UTC
- Bars: 32,087
- SMT file: `data/backtests/XAGUSD_H1_dukascopy_2021_2026.csv`

## Assumptions

- Risk per trade: 1.00%
- Starting equity for PnL normalization: 100,000.00
- Sweep buffer: 80.0 points x point size 0.01
- Max consecutive losing trades per NY day: 2
- SMT required: False
- Spread/commission/slippage: not explicitly charged beyond the sweep buffer.
- Same-bar ambiguity: bar-based backtest uses conservative stop checks before target checks.
- Execution feed: historical CSV, not live broker tick feed.

## Per-style results

| Style | Trades | Win rate | Total R | Expectancy R | Net PnL | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| swing | 7 | 42.86% | 5.69 | 0.813 | 5691.68 | -2000.00 |
| short_term_weekly | 184 | 50.54% | 63.82 | 0.347 | 63820.95 | -6953.36 |

## Overlay

- Trades: 191
- Total R: 69.51
- Expectancy R: 0.364
- Net PnL: 69512.63

## Reproducibility

Example command:

```bash
python3 tsentry_runner.py csv-backtest --symbol XAUUSD --csv-timeframe H1 --source dukascopy --styles swing short_term_weekly
```
