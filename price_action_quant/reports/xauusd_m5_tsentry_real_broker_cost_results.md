# XAUUSD TSEntry M5 - Real Broker Cost Results - 2026-06-12

## Scope

Goal: validate the XAUUSD M5 TSEntry trade list with real broker costs exported
from MT5 tick/spread data for Vantage, Ultima, StarTrader, and XM.

Safety constraints respected:

- no trades opened;
- no live-trading command executed;
- no credentials printed;
- no CSV/JSON outputs committed from `data/backtests/`.

Initial git check:

```text
## cursor/real-broker-costs-96f4...origin/cursor/real-broker-costs-96f4
```

The working branch was then switched to the requested target branch:
`cursor/tsentry-automation-2bd6`.

## Broker export attempts

`data/backtests/` was created before running the exports.

The available interpreter in this session is `python3`; the `python` command is
not installed. The MT5 export tool was therefore executed with `python3`.

| Broker | Symbol used | Output tick CSV | Output profile JSON | Status |
| --- | --- | --- | --- | --- |
| Vantage | `XAUUSD` | `data/backtests/broker_costs_vantage_XAUUSD_ticks.csv` | `data/backtests/broker_costs_vantage_XAUUSD_profile.json` | failed |
| Ultima | `XAUUSD` | `data/backtests/broker_costs_ultima_XAUUSD_ticks.csv` | `data/backtests/broker_costs_ultima_XAUUSD_profile.json` | failed |
| StarTrader | `XAUUSD` | `data/backtests/broker_costs_startrader_XAUUSD_ticks.csv` | `data/backtests/broker_costs_startrader_XAUUSD_profile.json` | failed |
| XM | `GOLD#` | `data/backtests/broker_costs_xm_GOLD_ticks.csv` | `data/backtests/broker_costs_xm_GOLD_profile.json` | failed |

All four commands failed before `mt5.initialize()` and before any Market Watch
symbol validation because the Python `MetaTrader5` module is not available in
this runtime:

```text
ModuleNotFoundError: No module named 'MetaTrader5'
RuntimeError: MetaTrader5 package is required for export-mt5
```

No profile JSON was created, so `apply-profiles` had no real broker profile to
apply. The expected trade list was also not present in the local checkout:

```text
data/backtests/TSENTRY_XAUUSD_M5_daytrading_split_oos_trades_20260612.csv
```

## Broker availability / failure reasons

| Broker | Symbol | Available | Reason |
| --- | --- | --- | --- |
| Vantage | `XAUUSD` | no | `MetaTrader5` Python module missing in this session; MT5 terminal could not be initialized. |
| Ultima | `XAUUSD` | no | `MetaTrader5` Python module missing in this session; MT5 terminal could not be initialized. |
| StarTrader | `XAUUSD` | no | `MetaTrader5` Python module missing in this session; MT5 terminal could not be initialized. |
| XM | `GOLD#` | no | `MetaTrader5` Python module missing in this session; MT5 terminal could not be initialized. |

## Spread metrics by broker

No real tick samples were exported. Metrics are therefore intentionally left as
not available instead of being inferred from synthetic or unrelated data.

| Broker | Symbol | Samples | Spread mean | Spread median | Spread p75 | Spread p90 | Spread p95 | Spread max |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Vantage | `XAUUSD` | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| Ultima | `XAUUSD` | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| StarTrader | `XAUUSD` | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| XM | `GOLD#` | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

## TSEntry results by broker and family

No TSEntry real-cost summary was generated because no broker profile JSON files
were available. Results below are not computed.

| Broker | Family | Trades | Winrate | PF | Expectancy R | DD giornaliero | DD max | Capitale finale da 50,000 USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Vantage | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Vantage | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Ultima | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Ultima | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| StarTrader | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| StarTrader | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| XM | Aggressiva/filtrata | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| XM | Conservativa strutturale | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Conclusive read

- Broker piu adatto: non determinabile in questo run, per assenza di profili
  reali esportati.
- Broker piu costoso: non determinabile in questo run, per assenza di metriche
  spread reali.
- Famiglia aggressiva/filtrata: non validabile con costi reali in questo run.
- Famiglia conservativa strutturale: non validabile con costi reali in questo
  run.
- Raccomandazione demo test: ripetere lo stesso workflow sulla VPS Windows/Contabo
  dove il modulo Python `MetaTrader5`, i terminali demo MT5 e la trade list locale
  siano realmente disponibili. Dopo la creazione dei profili JSON, applicare solo
  i profili riusciti e confrontare il p95 spread per scegliere broker/famiglia.

