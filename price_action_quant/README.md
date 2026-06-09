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

## 4. Run an in-sample / out-of-sample split

```bash
python3 -m price_action_quant.research split-evaluate \
  --csv data/backtests/GBPUSD_H1.csv \
  --symbol GBPUSD \
  --timeframe H1 \
  --direction short \
  --split-date 2024-01-01 \
  --min-trades 5 \
  --top-n 10 \
  --cost-per-trade-price 0.00012 \
  --out data/backtests/GBPUSD_H1_split_short_cost_2024.csv
```

`--cost-per-trade-price` is converted into R using each trade's ATR-based
stop distance. For example, `0.00012` on GBPUSD is roughly a 1.2-pip
round-trip cost proxy.

## 5. MT5 EA installation

1. Copy `mt5/PriceActionQuantEA.mq5` into the MT5 `MQL5/Experts` folder.
2. Compile it from MetaEditor.
3. Copy the desired `.set` file from `mt5/sets/`.
4. Attach the EA to the target chart and load the matching set.

Current baseline sets:

- `EURUSD_H1_PriceActionQuant_v0.1.set`
- `EURUSD_H4_PriceActionQuant_v0.1.set`
- `GBPUSD_H1_PriceActionQuant_v0.1.set`
- `GBPUSD_H4_PriceActionQuant_v0.1.set`
- `GBPUSD_H1_SHORT_PriceActionQuant_v0.2_candidate.set`
- `XAUUSD_H1_LONG_PriceActionQuant_v0.2_candidate.set`
- `XAUUSD_H1_LONG_ATR25_PriceActionQuant_v0.2_candidate.set`

The v0.1 files are not optimized. The v0.2 candidate files are based on the
first split/OOS research pass and still require broker MT5 Strategy Tester
validation before paper/live use.

Strategy Tester templates are available in:

```text
mt5/tester/
```

Use the report template when saving MT5 validation results:

```text
price_action_quant/reports/mt5_strategy_tester_template.md
```
