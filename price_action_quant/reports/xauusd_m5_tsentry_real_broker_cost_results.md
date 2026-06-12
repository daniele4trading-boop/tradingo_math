# XAUUSD TSEntry M5 - Real Broker Cost Results - 2026-06-12

## Execution status

The requested MT5 broker-cost export could not be completed from this cloud
session because the runtime is Linux, while the Python `MetaTrader5` package and
the configured MT5 terminals are Windows-only.

Initial repository check:

```text
## main...origin/main
```

Runtime checks:

- OS observed by Python: `Linux-6.12.58+-x86_64-with-glibc2.39`
- `python` command: not installed in this session
- `python3`: available (`3.12.3`)
- `pandas`: installed locally during the run so the tool could execute
- `MetaTrader5`: unavailable; `pip` reports no matching Linux distribution
- MT5-related environment variables: none found
- MT5/Wine terminal processes: none found
- `data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv`: not present locally

Because no MT5 terminal could be initialized, Market Watch could not be queried
and no broker symbol could be verified beyond the requested `XAUUSD` attempt.
No synthetic spread data was generated.

## MT5 export attempts

The export command was executed for each requested broker using the available
`python3` executable and the requested `XAUUSD` symbol:

```text
python3 tsentry_broker_costs.py export-mt5 --broker <broker> --symbol XAUUSD --days 30 --point-size 0.01 --commission-r 0.00 --slippage-points 0 --out-ticks data/backtests/broker_costs_<broker>_XAUUSD_ticks.csv --out-profile data/backtests/broker_costs_<broker>_XAUUSD_profile.json
```

All four runs failed before MT5 initialization with:

```text
RuntimeError: MetaTrader5 package is required for export-mt5
```

## Broker spread profiles

| Broker | Symbol used | Symbol verified in Market Watch | Tick samples | Mean spread | Median | p75 | p90 | p95 | Max | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Vantage | XAUUSD attempted | No | 0 | n/a | n/a | n/a | n/a | n/a | n/a | unavailable: `MetaTrader5` package not available on Linux runtime |
| Ultima | XAUUSD attempted | No | 0 | n/a | n/a | n/a | n/a | n/a | n/a | unavailable: `MetaTrader5` package not available on Linux runtime |
| StarTrader | XAUUSD attempted | No | 0 | n/a | n/a | n/a | n/a | n/a | n/a | unavailable: `MetaTrader5` package not available on Linux runtime |
| XM | XAUUSD attempted | No | 0 | n/a | n/a | n/a | n/a | n/a | n/a | unavailable: `MetaTrader5` package not available on Linux runtime |

No `data/backtests/broker_costs_*_XAUUSD_ticks.csv` or
`data/backtests/broker_costs_*_XAUUSD_profile.json` files were produced.

## Apply-profiles attempt

The requested profile application command was executed after the failed exports:

```text
python3 tsentry_broker_costs.py apply-profiles --trades data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv --profile data/backtests/broker_costs_*_XAUUSD_profile.json --spread-quantile p95 --start-capital 50000 --risk-fraction 0.01 --out-summary data/backtests/TSENTRY_XAUUSD_M5_real_broker_cost_summary.csv --out-trades data/backtests/TSENTRY_XAUUSD_M5_real_broker_cost_trades.csv
```

It could not compute results because the source trade list is not present in the
checkout:

```text
FileNotFoundError: [Errno 2] No such file or directory: 'data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv'
```

## TSEntry results after real broker costs

No real-broker TSEntry results are available in this run, because zero broker
profiles were created and the required local trade list CSV was absent.

| Broker | Family | Trades | Winrate | PF | Expectancy R | DD giornaliero | DD max | Capitale finale | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Vantage | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |
| Vantage | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |
| Ultima | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |
| Ultima | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |
| StarTrader | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |
| StarTrader | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |
| XM | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |
| XM | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not computed |

## Unavailable brokers and reasons

| Broker | Reason |
| --- | --- |
| Vantage | The Linux cloud runtime cannot import/install `MetaTrader5`; no configured Windows MT5 terminal was reachable. |
| Ultima | The Linux cloud runtime cannot import/install `MetaTrader5`; no configured Windows MT5 terminal was reachable. |
| StarTrader | The Linux cloud runtime cannot import/install `MetaTrader5`; no configured Windows MT5 terminal was reachable. |
| XM | The Linux cloud runtime cannot import/install `MetaTrader5`; no configured Windows MT5 terminal was reachable. |

## Files intentionally not committed

The task requested not to commit heavy CSV/JSON outputs. This run produced no
CSV or JSON exports under `data/backtests/`.

