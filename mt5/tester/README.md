# MT5 Strategy Tester package

This folder contains starter `.ini` files for running the Price Action Quant
candidate sets in MetaTrader 5 Strategy Tester.

## Files

Expert Advisor:

```text
mt5/PriceActionQuantEA.mq5
```

Candidate sets:

```text
mt5/sets/XAUUSD_H1_LONG_PriceActionQuant_v0.2_candidate.set
mt5/sets/XAUUSD_H1_LONG_ATR25_PriceActionQuant_v0.2_candidate.set
mt5/sets/GBPUSD_H1_SHORT_PriceActionQuant_v0.2_candidate.set
```

Tester configs:

```text
mt5/tester/XAUUSD_H1_LONG_ATR20_v0.2.ini
mt5/tester/XAUUSD_H1_LONG_ATR25_v0.2.ini
mt5/tester/GBPUSD_H1_SHORT_v0.2.ini
```

## Manual setup

1. Copy `mt5/PriceActionQuantEA.mq5` to the terminal `MQL5/Experts/` folder.
2. Compile it in MetaEditor.
3. Copy the `.set` files to the MT5 tester inputs location used by the terminal
   (commonly `MQL5/Profiles/Tester/`, or load them manually from Strategy Tester).
4. Run Strategy Tester with:
   - model: every tick based on real ticks, if available;
   - period: `2021-01-03` to `2026-06-08`;
   - timeframe: H1;
   - deposit: 10,000 USD or broker/account equivalent;
   - broker-real spread/commission/slippage.

## Command-line tester notes

The `.ini` files are templates. Broker installations vary, so adjust:

- `Expert=` if MT5 stores the EA in a subfolder;
- `ExpertParameters=` if MT5 expects an absolute or terminal-relative `.set` path;
- `Symbol=` if the broker uses suffixes, e.g. `XAUUSD.r`, `GOLD`, `GBPUSDm`;
- `Deposit`, `Currency`, and `Leverage`;
- `Model=` if the terminal uses a different numeric value for real ticks.

Typical Windows launch pattern:

```text
terminal64.exe /config:path\to\XAUUSD_H1_LONG_ATR25_v0.2.ini
```

If command-line mode is unreliable, run the same tests manually in Strategy
Tester by loading the EA and `.set` files.

## Python reference metrics

Use these as rough reference only. MT5 broker data, bid/ask handling,
commission, stop-levels, session gaps and tick model can materially change the
results.

### XAUUSD H1 long, ATR 2.0, R:R 2.0

Full 2021-2026 Python/Dukascopy proxy:

- Trades: 82
- Win rate: 47.56%
- Profit factor: 1.69
- Total: +31.19R
- Max DD: 8.31R

OOS 2024-2026:

- Trades: 46
- Win rate: 43.48%
- Profit factor: 1.46
- Total: +12.38R
- Max DD: 8.31R

### XAUUSD H1 long, ATR 2.5, R:R 2.0

Full 2021-2026 Python/Dukascopy proxy:

- Trades: 80
- Win rate: 46.25%
- Profit factor: 1.63
- Total: +28.02R
- Max DD: 6.20R

OOS 2024-2026:

- Trades: 46
- Win rate: 43.48%
- Profit factor: 1.48
- Total: +12.70R
- Max DD: 6.20R

### GBPUSD H1 short, ATR 2.5, R:R 2.0

Full 2021-2026 Python/Dukascopy proxy:

- Trades: 65
- Win rate: 40.00%
- Profit factor: 1.28
- Total: +11.19R
- Max DD: 6.16R

OOS 2024-2026:

- Trades: 28
- Win rate: 39.29%
- Profit factor: 1.24
- Total: +4.14R
- Max DD: 6.16R

## Reporting

Save final tester notes in:

```text
price_action_quant/reports/
```

Use the template:

```text
price_action_quant/reports/mt5_strategy_tester_template.md
```
