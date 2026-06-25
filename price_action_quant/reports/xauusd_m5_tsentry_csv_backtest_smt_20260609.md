# TSEntry CSV Backtest - XAUUSD M5

## Data used

- Primary file: `data/backtests/XAUUSD_M5_dukascopy_2021_2026.csv`
- Symbol: `XAUUSD`
- Timeframe: `M5`
- Source: `dukascopy`
- Period: 2021-01-03 23:00 UTC -> 2026-06-08 00:00 UTC
- Bars: 384,829
- SMT file: `data/backtests/XAGUSD_M5_dukascopy_2021_2026.csv`

## Assumptions

- Risk per trade: 1.00%
- Starting equity for PnL normalization: 100,000.00
- Sweep buffer: 80.0 points x point size 0.01
- Max consecutive losing trades per NY day: 2
- SMT required: True
- Spread/commission/slippage: not explicitly charged beyond the sweep buffer.
- Same-bar ambiguity: bar-based backtest uses conservative stop checks before target checks.
- Execution feed: historical CSV, not live broker tick feed.

## Per-style results

| Style | Trades | Win rate | Total R | Expectancy R | Net PnL | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| daytrading_daily | 179 | 58.66% | 155.68 | 0.870 | 155679.37 | -6000.00 |

## Overlay

- Trades: 179
- Total R: 155.68
- Expectancy R: 0.870
- Net PnL: 155679.37

## Reproducibility

Example command:

```bash
python3 tsentry_runner.py csv-backtest --symbol XAUUSD --csv-timeframe M5 --source dukascopy --styles daytrading_daily
```
