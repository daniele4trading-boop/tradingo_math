---
name: testing-pattern-go
description: Come testare il servizio Pattern GO (oro XAU su API REST DXtrade/Velotrade) da riga di comando, incluse le forme di payload accettate dal broker per ordini e chiusure.
---

# Testing Pattern GO

Servizio Python in `pattern_go/`, isolato dal resto della repo. Non è un'app web: nessun
frontend, nessun dev server → **test da shell, nessuna registrazione video**.

## Setup

```bash
python3 -m pip install requests pytest ruff
cd pattern_go
cp config.example.json config.json     # config.json è gitignored
export DXTRADE_USERNAME=... DXTRADE_PASSWORD=...
python3 -m ruff check .
PYTHONPATH=. python3 -m pytest tests
PYTHONPATH=. python3 -m pattern_go --config config.json --dry-run
```

`PYTHONPATH=.` è obbligatorio per pytest e per i moduli. Conto demo Velotrade
`default:130000638`, base URL `https://dx.velotrade.com/dxsca-web`, domain `default`.
Simbolo oro = `XAU` (non `XAUUSD`), quantità in **once**, `quantityIncrement = 0.01`.

## Devin Secrets Needed

- `DXTRADE_USERNAME`
- `DXTRADE_PASSWORD`

Non esistono nel repo: se non sono nell'ambiente, chiedile al lead. Non scriverle su disco:
il journal e lo stdout vanno verificati con
`grep -Rqi -e '<user>' -e '<pass>' -e sessiontoken logs/` (atteso: 0 occorrenze).

## Regole di sicurezza

**Nessun ordine (nemmeno demo) senza autorizzazione esplicita dell'utente.** Sono sempre
sicure le chiamate in lettura: `login`, `instrument`, `metrics`, `positions`, `orders`,
`quote`, `candles`. Se gli ordini demo sono autorizzati: quantità 0.01, uno alla volta,
e **ripulisci sempre** verificando alla fine `positions() == []` e `orders() == []`.
Per un ordine che deve restare pendente: BUY stop ~50 USD sopra l'ask. Per uno che deve
eseguire: BUY stop ~0.05 USD sopra l'ask (fill in genere entro 1-2 minuti).

## Payload DXtrade accettati da questo broker (misurati sul conto demo)

Il broker è severo sui parametri; l'errore generico è
`400 {"errorCode":"32","description":"Incorrect request parameters: ..."}`.

- **`candles`/`marketdata` richiede `toTime`**: senza di esso →
  `Incorrect request parameters: <toTime> for event type Candle`. Se il warmup fallisce
  all'avvio, è quasi sempre questo. Potrebbe essere già corretto: verifica se
  `Runner._closed_bars` passa `to_time`.
- **il campo `legs` fa rifiutare gli ordini**: uno stop d'ingresso passa solo come
  `{"account","orderCode","type":"STOP","instrument","quantity","positionEffect":"OPEN",
  "side","stopPrice","tif":"GTC"}`. Anche `orderRequests` con SL/TP collegati (`-SL`/`-TP`)
  viene rifiutato: SL/TP potrebbero richiedere gestione lato runner.
- **la chiusura richiede `positionCode` top-level** oltre a `positionEffect: "CLOSE"` e
  `tif: "IOC"`; senza di esso → `errorCode 33 Incorrect request. <positionCode>`. Il
  `positionCode` si legge da `positions()`.
- `cancel_order` funziona passando il `clientOrderId` (non l'`orderCode` prefissato
  `dxsca-integration-session-code:`).
- Il prezzo di fill di una posizione è nel campo **`openPrice`** di `positions()`.

## Testare senza broker

`tests/test_runner.py` contiene un `FakeClient` riusabile: importa
`from tests.test_runner import FakeClient, make_config, _journal` per pilotare `Runner`
(kill switch, risk guard, fill detection) senza rete. Il kill switch è un file il cui path
sta in `runtime.kill_switch_file`; crealo e chiama `runner.tick()`.

## Punti da controllare sempre

- journal JSON in `logs/journal_YYYYMMDD.jsonl`: `STARTUP` deve avere `static_floor` 9700 su
  conto 10k, con `reservoir` 300 e `risk_amount` 15 **solo se il saldo è esattamente 10.000**
  (ordini di prova precedenti spostano questi valori: è atteso, non un bug);
- `analyze_logs` e `write_daily_report` devono funzionare su un journal senza trade;
- config adversarial: `risk_fraction` negativa o floor sopra il saldo potrebbero non essere
  validati e produrre comunque quantità 0.01 per via di `round_below_min_to_min` — verificalo
  chiamando `RiskManager.quantity()` direttamente, in isolamento dalla rete.
