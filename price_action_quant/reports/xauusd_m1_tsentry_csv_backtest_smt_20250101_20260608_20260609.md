# TSEntry CSV Backtest - XAUUSD M1

## Data used

- Primary file: `data/backtests/XAUUSD_M1_dukascopy_2021_2026.csv`
- Symbol: `XAUUSD`
- Timeframe: `M1`
- Source: `dukascopy`
- Period: 2025-01-01 23:00 UTC -> 2026-06-08 00:00 UTC
- Bars: 505,876
- SMT file: `data/backtests/XAGUSD_M1_dukascopy_2021_2026.csv`

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
| scalping_h1 | 151 | 47.68% | 47.14 | 0.312 | 47136.36 | -10918.79 |

## Overlay

- Trades: 151
- Total R: 47.14
- Expectancy R: 0.312
- Net PnL: 47136.36

## Reproducibility

Example command:

```bash
python3 tsentry_runner.py csv-backtest --symbol XAUUSD --csv-timeframe M1 --source dukascopy --styles scalping_h1 --start 2025-01-01 --end 2026-06-08
```
