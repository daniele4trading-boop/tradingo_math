# TSEntry Shared Data Workflow

This note documents how the TSEntry research runner reuses the shared
`data/backtests/` historical data folder without duplicating downloads.

## Current integration

- Code entry point: `tsentry_runner.py`
- Strategy engine: `tsentry_strategy.py`
- Shared CSV folder: `data/backtests/`
- Shared readable reports: `price_action_quant/reports/`
- Raw CSVs and generated trade lists remain local because `data/backtests/` is
  intentionally ignored by git.

## Before downloading data

Always check whether the required CSV already exists:

```bash
ls -la data/backtests/
```

Recommended naming convention:

```text
data/backtests/<SYMBOL>_<TIMEFRAME>_<SOURCE>_<START>_<END>.csv
```

Examples:

```text
data/backtests/EURUSD_H1_dukascopy_2021_2026.csv
data/backtests/GBPUSD_H1_dukascopy_2021_2026.csv
data/backtests/XAUUSD_H1_dukascopy_2021_2026.csv
```

## Running TSEntry on existing CSVs

Run all styles that can be supported by the CSV timeframe:

```bash
python3 tsentry_runner.py csv-backtest \
  --symbol XAUUSD \
  --csv-timeframe H1 \
  --source dukascopy \
  --styles all
```

Risk control defaults:

- `--risk 0.01`
- `--max-consecutive-daily-losses 2`

The daily loss circuit breaker is evaluated by New York calendar day. Once the
configured number of consecutive losing trades is reached, the backtest skips
the remaining signals for that same day.

If the file follows the naming convention, the runner discovers it
automatically. Otherwise pass it explicitly:

```bash
python3 tsentry_runner.py csv-backtest \
  --symbol XAUUSD \
  --csv-timeframe H1 \
  --csv data/backtests/XAUUSD_H1_dukascopy_2021_2026.csv \
  --styles short_term_weekly swing
```

Optional SMT confirmation can use a second CSV:

```bash
python3 tsentry_runner.py csv-backtest \
  --symbol XAUUSD \
  --smt-symbol XAGUSD \
  --csv-timeframe M5 \
  --smt-csv data/backtests/XAGUSD_M5_dukascopy_2021_2026.csv \
  --styles daytrading_daily \
  --require-smt
```

Large M1 files can be tested in rolling windows first:

```bash
python3 tsentry_runner.py csv-backtest \
  --symbol XAUUSD \
  --csv-timeframe M1 \
  --styles scalping_h1 \
  --start 2025-01-01 \
  --end 2026-06-08
```

## Timeframe compatibility

The runner refuses to downsample coarse data into finer execution data:

| Style | Required entry TF | Compatible source CSV |
| --- | ---: | --- |
| `swing` | D1 | D1 or finer |
| `short_term_weekly` | H1 | H1 or finer |
| `daytrading_daily` | M5 | M5 or finer |
| `scalping_h1` | M1 | M1 only |

So the currently described H1 Dukascopy files can validate `swing` and
`short_term_weekly`, but not M5 daytrading or M1 scalping without finer data.

## Outputs

Generated local outputs:

```text
data/backtests/TSENTRY_<SYMBOL>_<ENTRY_TF>_<STYLE>_trades.csv
data/backtests/TSENTRY_<SYMBOL>_<ENTRY_TF>_<STYLE>_summary.json
data/backtests/TSENTRY_<SYMBOL>_<CSV_TF>_overlay_trades.csv
```

Generated committed-readable report:

```text
price_action_quant/reports/<symbol>_<timeframe>_tsentry_csv_backtest_<yyyymmdd>.md
```

Each report records:

- data file used;
- source, symbol, timeframe, period and bar count;
- SMT file if available;
- risk and buffer assumptions;
- spread/slippage/cost assumption;
- per-style summary and overlay result.

## Downloading a missing Dukascopy CSV

Only download if the file is absent locally:

```bash
python3 -m price_action_quant.research download-dukascopy \
  --symbol XAUUSD \
  --timeframe H1 \
  --start 2021-01-01 \
  --end 2026-06-08 \
  --out data/backtests/XAUUSD_H1_dukascopy_2021_2026.csv
```

Do not commit raw CSVs unless explicitly requested.
