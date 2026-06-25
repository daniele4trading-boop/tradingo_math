# XAUUSD TSEntry M5 - Real Broker Cost Results

## Environment

- Repo path: `C:\tsentry_repo`
- Branch: `cursor/tsentry-automation-2bd6`
- Python used: `C:\tradingo_system_lab\tradingo_lab\.venv\Scripts\python.exe`
- Real-cost application: `p95` spread
- Start capital: `50,000 USD`
- Risk: `1%`, fixed 1R = 500 USD

## Broker export status

| Broker | Symbol | Status | Notes |
| --- | --- | --- | --- |
| vantage | XAUUSD | success | Profile exported and applied. |
| ultima | XAUUSD | success | Profile exported and applied. |
| startrader | XAUUSD | success | Profile exported and applied. |
| xm | GOLD# | failed | `symbol_select failed`; symbol/terminal not available from current MT5 Python context. |

## Spread metrics

| Broker | Symbol | Samples | Mean | Median | P75 | P90 | P95 | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vantage | XAUUSD | 14440449 | 20.70 | 21.00 | 21.00 | 21.00 | 21.00 | 81.00 |
| ultima | XAUUSD | 14443421 | 20.70 | 21.00 | 21.00 | 21.00 | 21.00 | 81.00 |
| startrader | XAUUSD | 14440900 | 20.70 | 21.00 | 21.00 | 21.00 | 21.00 | 81.00 |
| xm | n/a | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

## TSEntry results with real broker p95 spread

| Broker | Family | Trades | Winrate | PF | Expectancy R | Avg cost R | Daily DD | Max DD | Final capital |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vantage | Aggressiva/filtrata | 236 | 58.90% | 3.59 | 1.115 | 0.115 | $-617 | $-4,675 | $181,542 |
| vantage | Conservativa strutturale | 222 | 57.66% | 2.96 | 0.809 | 0.076 | $-1,116 | $-3,244 | $139,828 |
| ultima | Aggressiva/filtrata | 236 | 58.90% | 3.59 | 1.115 | 0.115 | $-617 | $-4,675 | $181,542 |
| ultima | Conservativa strutturale | 222 | 57.66% | 2.96 | 0.809 | 0.076 | $-1,116 | $-3,244 | $139,828 |
| startrader | Aggressiva/filtrata | 236 | 58.90% | 3.59 | 1.115 | 0.115 | $-617 | $-4,675 | $181,542 |
| startrader | Conservativa strutturale | 222 | 57.66% | 2.96 | 0.809 | 0.076 | $-1,116 | $-3,244 | $139,828 |

## Read

- Vantage, Ultima and StarTrader profiles are effectively identical: p95 spread is 21 points for all three.
- This strongly suggests that the Python MetaTrader5 bridge may have queried the same active MT5 terminal/feed for all three broker labels, because no explicit `--mt5-path` was passed.
- XM was not validated because `GOLD#` was not available from the MT5 terminal selected by Python.
- With the available p95 spread profile, both families remain profitable after real spread application.
- Aggressiva/filtrata remains the preferred family: higher PF, higher expectancy, and higher final capital.
- Conservativa strutturale remains viable but has lower return and lower PF.

## Recommendation

Before demo deployment, repeat broker exports with explicit MT5 terminal paths for each broker, or open one broker terminal at a time and rerun export. Current results are useful, but not sufficient to rank Vantage vs Ultima vs StarTrader because the spread profiles are identical.

Operational candidate remains:

```text
daytrading_daily M5
SMT required
buffer 40
max_consecutive_daily_losses = 1
```

## Local ignored files

- `data/backtests/TSENTRY_XAUUSD_M5_real_broker_cost_summary.csv`
- `data/backtests/TSENTRY_XAUUSD_M5_real_broker_cost_trades.csv`
- `data/backtests/broker_costs_*_ticks.csv`
- `data/backtests/broker_costs_*_profile.json`
