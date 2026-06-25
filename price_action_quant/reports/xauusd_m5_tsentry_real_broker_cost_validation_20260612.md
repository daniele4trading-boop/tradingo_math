# XAUUSD TSEntry M5 - Real Broker Cost Validation Setup - 2026-06-12

## Stato

In questa copia della VPS/repo non sono presenti export reali di spread/tick per
Vantage, StarTrader o XM. Sono presenti log storici parziali di vecchi motori,
ma non sono abbastanza completi o normalizzati per validare correttamente i
quattro broker richiesti.

Per evitare dati inventati, la validazione real-broker deve partire da export
MT5 o CSV bid/ask/spread per:

- Vantage
- Ultima
- StarTrader
- XM

## Tool aggiunto

Script:

```text
tsentry_broker_costs.py
```

Funzioni:

1. esporta tick/spread da MT5;
2. crea profili costo broker da CSV;
3. applica i profili alla trade list TSEntry già validata.

Trade list sorgente:

```text
data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv
```

## Export da MT5 Windows

Eseguire su ogni terminale/broker MT5 della VPS Windows/CursorWeb.

### Vantage

```bash
python tsentry_broker_costs.py export-mt5 \
  --broker vantage \
  --symbol XAUUSD \
  --days 30 \
  --point-size 0.01 \
  --commission-r 0.00 \
  --slippage-points 0 \
  --out-ticks data/backtests/broker_costs_vantage_XAUUSD_ticks.csv \
  --out-profile data/backtests/broker_costs_vantage_XAUUSD_profile.json
```

### Ultima

```bash
python tsentry_broker_costs.py export-mt5 \
  --broker ultima \
  --symbol XAUUSD \
  --days 30 \
  --point-size 0.01 \
  --commission-r 0.00 \
  --slippage-points 0 \
  --out-ticks data/backtests/broker_costs_ultima_XAUUSD_ticks.csv \
  --out-profile data/backtests/broker_costs_ultima_XAUUSD_profile.json
```

### StarTrader

```bash
python tsentry_broker_costs.py export-mt5 \
  --broker startrader \
  --symbol XAUUSD \
  --days 30 \
  --point-size 0.01 \
  --commission-r 0.00 \
  --slippage-points 0 \
  --out-ticks data/backtests/broker_costs_startrader_XAUUSD_ticks.csv \
  --out-profile data/backtests/broker_costs_startrader_XAUUSD_profile.json
```

### XM

```bash
python tsentry_broker_costs.py export-mt5 \
  --broker xm \
  --symbol XAUUSD \
  --days 30 \
  --point-size 0.01 \
  --commission-r 0.00 \
  --slippage-points 0 \
  --out-ticks data/backtests/broker_costs_xm_XAUUSD_ticks.csv \
  --out-profile data/backtests/broker_costs_xm_XAUUSD_profile.json
```

If a broker uses a different symbol name, replace `XAUUSD` with the exact
Market Watch symbol, for example `GOLD`, `XAUUSD.a`, `XAUUSDm`, etc.

## Apply broker profiles

After all profile JSONs are available:

```bash
python tsentry_broker_costs.py apply-profiles \
  --trades data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv \
  --profile \
    data/backtests/broker_costs_vantage_XAUUSD_profile.json \
    data/backtests/broker_costs_ultima_XAUUSD_profile.json \
    data/backtests/broker_costs_startrader_XAUUSD_profile.json \
    data/backtests/broker_costs_xm_XAUUSD_profile.json \
  --spread-quantile p95 \
  --start-capital 50000 \
  --risk-fraction 0.01 \
  --out-summary data/backtests/TSENTRY_XAUUSD_M5_real_broker_cost_summary.csv \
  --out-trades data/backtests/TSENTRY_XAUUSD_M5_real_broker_cost_trades.csv
```

Recommended primary metric is `p95` spread, because TSEntry executes around
London/NY volatility windows where mean spread can understate execution cost.

## CSV input alternative

If MT5 export is not available but another agent has bid/ask or spread CSVs:

```bash
python tsentry_broker_costs.py profile-from-csv \
  --broker vantage \
  --symbol XAUUSD \
  --csv data/backtests/vantage_XAUUSD_tick_spreads.csv \
  --point-size 0.01 \
  --commission-r 0.00 \
  --slippage-points 0 \
  --out data/backtests/broker_costs_vantage_XAUUSD_profile.json
```

CSV accepted columns:

- either `spread_points`;
- or `bid` and `ask`.

## Notes

- Raw broker tick/spread CSVs and resulting summaries stay under
  `data/backtests/`, which is ignored by git.
- This report and `tsentry_broker_costs.py` are committed so every agent can
  collect and apply broker costs without duplicating implementation work.
- Commission/slippage must be filled with real broker terms if known. If not
  known, first run with `0`, then repeat with conservative assumptions.
