# XAUUSD TSEntry Initial Results - 2026-06-09

Initial TSEntry research run using shared Dukascopy BID OHLC CSVs under
`data/backtests/`.

## Data inventory

New local datasets made available to other agents on the shared VPS:

| File | Bars | Notes |
| --- | ---: | --- |
| `data/backtests/XAUUSD_M1_dukascopy_2021_2026.csv` | 1,923,593 | Primary scalping source |
| `data/backtests/XAUUSD_M5_dukascopy_2021_2026.csv` | 384,829 | Primary daytrading source |
| `data/backtests/XAUUSD_H1_dukascopy_2021_2026.csv` | 32,087 | Swing / short-term source |
| `data/backtests/XAGUSD_M1_dukascopy_2021_2026.csv` | 1,910,403 | SMT source for M1 |
| `data/backtests/XAGUSD_M5_dukascopy_2021_2026.csv` | 384,612 | SMT source for M5 |
| `data/backtests/XAGUSD_H1_dukascopy_2021_2026.csv` | 32,086 | SMT source for H1 |
| `data/backtests/EURUSD_H1_dukascopy_2021_2026.csv` | 33,847 | Shared FX context |
| `data/backtests/EURUSD_H4_dukascopy_2021_2026.csv` | 8,750 | Shared FX context |
| `data/backtests/GBPUSD_H1_dukascopy_2021_2026.csv` | 33,844 | Shared FX context |
| `data/backtests/GBPUSD_H4_dukascopy_2021_2026.csv` | 8,749 | Shared FX context |

Raw CSVs and generated trade lists are intentionally ignored by git.

## Assumptions

- Source: Dukascopy BID candles.
- Period for H1/M5 tests: approximately 2021-01-01 -> 2026-06-08 UTC.
- Period for M1 scalping test: 2025-01-01 -> 2026-06-08 UTC.
- Risk normalization: 1% per trade.
- Daily circuit breaker: stop taking further signals after 2 consecutive losing
  trades in the same New York calendar day.
- Spread/commission/slippage: not explicitly charged beyond the sweep buffer.
- Sweep buffer: 80 points x 0.01 point size.
- These are research results, not live/demo deployment settings.

## Results

| Style | CSV TF | SMT required | Period | Trades | Win rate | Total R | Expectancy R | Max DD |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `swing` | H1 | no | 2021-2026 | 7 | 42.86% | 5.69 | 0.813 | -2,000 |
| `swing` | H1 | yes | 2021-2026 | 4 | 25.00% | 2.41 | 0.603 | -1,000 |
| `short_term_weekly` | H1 | no | 2021-2026 | 184 | 50.54% | 63.82 | 0.347 | -6,953 |
| `short_term_weekly` | H1 | yes | 2021-2026 | 155 | 51.61% | 57.82 | 0.373 | -7,021 |
| `daytrading_daily` | M5 | no | 2021-2026 | 222 | 59.46% | 196.58 | 0.885 | -6,000 |
| `daytrading_daily` | M5 | yes | 2021-2026 | 179 | 58.66% | 155.68 | 0.870 | -6,000 |
| `scalping_h1` | M1 | no | 2025-2026 | 184 | 47.83% | 52.34 | 0.284 | -13,636 |
| `scalping_h1` | M1 | yes | 2025-2026 | 151 | 47.68% | 47.14 | 0.312 | -10,919 |

## Read

- `daytrading_daily` is the strongest first candidate: enough trades, high
  expectancy, and stable base vs SMT behavior.
- `short_term_weekly` is viable for optimization. SMT improves expectancy
  slightly but does not improve drawdown in this first pass.
- `scalping_h1` needs drawdown optimization before demo use. SMT helps reduce
  drawdown and improves expectancy, so it should remain in the parameter grid.
- `swing` has too few trades to judge from this sample.

## Generated detailed reports

- `price_action_quant/reports/xauusd_h1_tsentry_csv_backtest_base_20260609.md`
- `price_action_quant/reports/xauusd_h1_tsentry_csv_backtest_smt_20260609.md`
- `price_action_quant/reports/xauusd_m5_tsentry_csv_backtest_base_20260609.md`
- `price_action_quant/reports/xauusd_m5_tsentry_csv_backtest_smt_20260609.md`
- `price_action_quant/reports/xauusd_m1_tsentry_csv_backtest_base_20250101_20260608_20260609.md`
- `price_action_quant/reports/xauusd_m1_tsentry_csv_backtest_smt_20250101_20260608_20260609.md`

## Next optimization cycle

Recommended grid, in this order:

1. `daytrading_daily` M5:
   - sweep buffer: 40 / 60 / 80 / 120 points;
   - NY windows: London only, NY only, both;
   - max consecutive daily losses: 1 / 2 / 3;
   - SMT optional vs required.
2. `short_term_weekly` H1:
   - Monday only vs Monday+Tuesday;
   - require prior D1 level only vs also prior H1 level;
   - SMT optional vs required.
3. `scalping_h1` M1:
   - shorter NY windows;
   - tighter daily loss breaker;
   - require SMT;
   - test by yearly splits before full-range aggregation.

Do not move to demo execution until out-of-sample/split tests preserve positive
expectancy and acceptable drawdown.
