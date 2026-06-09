# Price Action Quant v0.1

This folder contains the first research workflow for the Price Action Quant
strategy:

- bullish/bearish engulfing pattern;
- RSI(14) Z-Score filter over a 50-bar RSI window;
- recent RSI Z-Score mode over the last 3 closed bars;
- EMA200 regime filter with slope confirmation;
- ATR-based stop loss and fixed reward/risk target;
- results measured in R, independent from account currency.

The live MT5 Expert Advisor is in `../mt5/PriceActionQuantEA.mq5`.

## 1. Download data

### Dukascopy

Use this route when the VPS does not expose a local MT5 terminal to Python.

```bash
python3 -m pip install -r requirements.txt
python3 -m price_action_quant.research download-dukascopy \
  --symbol EURUSD \
  --timeframe H1 \
  --start 2021-01-01 \
  --end 2026-06-08 \
  --out data/backtests/EURUSD_H1.csv
```

Supported initial symbols: `EURUSD`, `GBPUSD`, `USDJPY`, `AUDUSD`,
`USDCAD`, `USDCHF`, `NZDUSD`, `XAUUSD`/`GOLD`.

### Broker MT5 terminal

The local MT5 terminal must be installed, openable by the Python `MetaTrader5`
package, and have the symbol available in Market Watch.

```bash
python3 -m pip install -r requirements.txt
python3 -m price_action_quant.research download-mt5 \
  --symbol EURUSD \
  --timeframe H1 \
  --bars 50000 \
  --out data/backtests/EURUSD_H1.csv
```

Repeat with `GBPUSD`, `H4`, or the exact broker symbol names.

## 2. Run one baseline backtest

```bash
python3 -m price_action_quant.research backtest \
  --csv data/backtests/EURUSD_H1.csv \
  --symbol EURUSD \
  --timeframe H1 \
  --direction long \
  --trades-out data/backtests/EURUSD_H1_trades.csv \
  --summary-out data/backtests/EURUSD_H1_summary.json
```

The baseline matches the `.set` files:

- long only;
- RSI Z recent minimum <= -2.0;
- EMA200 regime filter enabled;
- close above previous high required;
- SL = 2 ATR;
- TP = 1.5R.

## 3. Run the first constrained optimization

```bash
python3 -m price_action_quant.research optimize \
  --csv data/backtests/EURUSD_H1.csv \
  --symbol EURUSD \
  --timeframe H1 \
  --direction long \
  --min-trades 20 \
  --out data/backtests/EURUSD_H1_optimization.csv
```

The initial grid only varies:

- RSI Z threshold: -1.5, -1.75, -2.0, -2.25, -2.5;
- ATR stop multiplier: 1.5, 2.0, 2.5;
- reward/risk: 1.0, 1.5, 2.0;
- close-break pattern confirmation on/off.

This is intentionally small so that the first results do not become curve-fit.

## 4. MT5 EA installation

1. Copy `mt5/PriceActionQuantEA.mq5` into the MT5 `MQL5/Experts` folder.
2. Compile it from MetaEditor.
3. Copy the desired `.set` file from `mt5/sets/`.
4. Attach the EA to the target chart and load the matching set.

Current baseline sets:

- `EURUSD_H1_PriceActionQuant_v0.1.set`
- `EURUSD_H4_PriceActionQuant_v0.1.set`
- `GBPUSD_H1_PriceActionQuant_v0.1.set`
- `GBPUSD_H4_PriceActionQuant_v0.1.set`

These are not optimized. They are the baseline for the first test cycle.

## 5. TSEntry shared CSV workflow

The TSEntry runner can reuse the same `data/backtests/` CSV archive without
copying or re-downloading raw data:

```bash
python3 tsentry_runner.py csv-backtest \
  --symbol XAUUSD \
  --csv-timeframe H1 \
  --source dukascopy \
  --styles all
```

See `price_action_quant/reports/tsentry_shared_workflow.md` for the anti-
duplication rules, timeframe compatibility, generated output names, and report
conventions.
