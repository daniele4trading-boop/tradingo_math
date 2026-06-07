# ICT Sniper Infrastructure

Questa infrastruttura copre i primi quattro blocchi approvati:

1. download dati storici M1/M5/H1 da MT5;
2. archivio locale dati;
3. backtester ICT/FVG/Liquidity Sweep;
4. validazione statistica iniziale.

Il codice vive nel package `tradingo_core` ed e' separato dai motori live
prop/hedge esistenti.

## Architettura

```text
tradingo_core/
  market_data.py   -> downloader MT5 + archivio CSV mensile
  ict_sniper.py    -> detector setup sniper ICT/SMC
  backtester.py    -> simulatore candle-by-candle
  validation.py    -> CLI report su dati archiviati

data/
  XAUUSD/
    M1/
      2026-06.csv
```

## Setup Python sulla VPS Windows

Da `C:\TradinGO_Math\` o dalla cartella in cui verra' clonato il repository:

```powershell
python -m pip install -r requirements.txt
python -m pip install MetaTrader5
```

La libreria `MetaTrader5` va installata sulla VPS Windows dove sono presenti i
terminali MT5.

## Download storico da MT5

Usare variabili ambiente per evitare credenziali hardcodate:

```powershell
$env:MT5_TERMINAL_PATH="C:\Program Files\Vantage MetaTrader 5\terminal64.exe"
$env:MT5_LOGIN="123456789"
$env:MT5_PASSWORD="***"
$env:MT5_SERVER="Broker-Server"
```

Esempio download XAUUSD M1:

```powershell
python -m tradingo_core.market_data `
  --symbol XAUUSD `
  --timeframe M1 `
  --start 2026-01-01T00:00:00Z `
  --end 2026-06-01T00:00:00Z `
  --archive-root data `
  --chunk-days 7
```

Output atteso:

```text
data/XAUUSD/M1/2026-01.csv
data/XAUUSD/M1/2026-02.csv
...
```

Nota: lo storico disponibile dipende dal broker e da quanto MT5 ha scaricato.
Per aumentare lo storico aprire il grafico del simbolo/timeframe su MT5 e
forzare il download da History Center o scroll storico.

## Validazione/backtest

Esempio:

```powershell
python -m tradingo_core.validation `
  --archive-root data `
  --symbol XAUUSD `
  --timeframe M1 `
  --start 2026-01-01T00:00:00Z `
  --end 2026-06-01T00:00:00Z `
  --risk-pct 0.005 `
  --max-daily-dd-pct 0.02 `
  --max-daily-trades 3 `
  --min-score 65 `
  --rr 2 `
  --trades-csv reports/xauusd_ict_sniper_trades.csv
```

Metriche prodotte:

- setup rilevati;
- trade chiusi;
- equity finale;
- winrate;
- profit factor;
- expectancy in R;
- max drawdown;
- max daily drawdown.

## Logica strategia implementata

Il detector usa:

- bias higher timeframe;
- sweep di swing high/low recenti;
- Fair Value Gap dopo displacement;
- volume z-score su sweep e impulso;
- range/ATR per misurare displacement;
- retest del FVG;
- filtro Kill Zone Europe/Rome:
  - London Open 07:00-10:00;
  - NY Open 14:30-16:30.

Entry:

- limit al 50% del FVG;
- stop oltre l'estremo dello sweep con buffer ATR;
- TP1 a 1R;
- TP2 default a 2R.

Risk/backtest:

- rischio default 0.5% per trade;
- massimo 3 trade al giorno;
- stop giornaliero simulato al 2%;
- break-even quando il trade raggiunge 1R.

## Fonti dati consigliate

Ordine pratico:

1. dati MT5 dei broker gia' installati sulla VPS, per coerenza con esecuzione
   reale;
2. Dukascopy per storico forex esteso;
3. dati futures CME/GC a pagamento per volume reale su Gold.

Per la distribuzione ad amici e' preferibile fornire via API segnali, score e
dati derivati. La redistribuzione di dati grezzi puo' essere limitata dai
contratti dei provider esterni.

## Roadmap API/EA

Il primo scheletro API/EA e' gia' presente:

```text
Python VPS API:
  /health
  /symbols
  /signals/latest
  /signals/ack
  /accounts/heartbeat
  /risk/config

EA MQL5:
  legge segnali via WebRequest
  valida spread/rischio locale
  piazza ordini
  gestisce SL/TP/BE
  invia feedback esecuzione alla VPS
```

L'EA distribuito agli amici deve restare leggero: il cervello resta sulla VPS,
mentre l'EA fa execution e fail-safe locale.

## Avvio API sulla VPS

Installare dipendenze:

```powershell
python -m pip install -r requirements.txt
```

Configurare chiavi API con variabili ambiente. Usare chiavi diverse per admin e
client; non committarle mai nel repository.

```powershell
$env:TRADINGO_API_DATA_DIR="C:\TradinGO_Math\runtime\api_state"
$env:TRADINGO_API_KEYS="client-key-1,client-key-2"
$env:TRADINGO_ADMIN_API_KEYS="admin-key-1"
```

Avvio locale:

```powershell
python -m uvicorn tradingo_core.api_server:create_app --factory --host 0.0.0.0 --port 8080
```

Su Windows Server e' preferibile installare l'API come Scheduled Task:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install_api_task.ps1 `
  -RepoDir C:\TradinGO_Research `
  -HostAddress 127.0.0.1 `
  -Port 8080 `
  -AllowDevKey
```

Per produzione rimuovere `-AllowDevKey` e passare chiavi reali:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install_api_task.ps1 `
  -RepoDir C:\TradinGO_Research `
  -HostAddress 0.0.0.0 `
  -Port 8080 `
  -ApiKeys "client-key-1,client-key-2" `
  -AdminApiKeys "admin-key-1"
```

Endpoint principali:

```text
GET  /health
GET  /signals/latest?symbol=XAUUSD       header X-API-Key: client
POST /signals/publish                    header X-API-Key: admin
POST /signals/ack                        header X-API-Key: client
POST /accounts/heartbeat                 header X-API-Key: client
GET  /accounts/heartbeats                header X-API-Key: admin
GET  /risk/config                        header X-API-Key: client
POST /risk/config                        header X-API-Key: admin
```

Esempio publish segnale:

```json
{
  "signal_id": "demo-001",
  "symbol": "XAUUSD",
  "direction": "BUY",
  "entry_type": "LIMIT",
  "entry": 2300.0,
  "sl": 2298.0,
  "tp1": 2302.0,
  "tp2": 2304.0,
  "risk_pct": 0.005,
  "score": 82,
  "expires_at": "2026-06-08T10:00:00+00:00"
}
```

L'API rifiuta segnali con rischio non valido o RR inferiore a 1:2.

## EA MQL5 client

File:

```text
mt5_ea/TradinGoSignalClient.mq5
```

Installazione:

1. copiare il file in `MQL5\Experts\TradinGo\`;
2. aprire MetaEditor e compilare;
3. in MT5 abilitare:
   - `Tools > Options > Expert Advisors > Allow WebRequest for listed URL`;
   - aggiungere l'URL API, es. `http://144.91.76.28:8080`;
4. attach dell'EA al grafico del simbolo;
5. impostare:
   - `ApiBaseUrl`;
   - `ApiKey`;
   - `ClientId`;
   - `BrokerName`;
   - `TradeSymbol`;
   - `EnableLiveTrading=false` per i primi test.

Per sicurezza l'EA parte in dry-run. In dry-run riceve segnali e invia ack, ma
non piazza ordini.

Installazione automatica dry-run sui terminali VPS principali:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install_ea_dryrun.ps1 `
  -RepoDir C:\TradinGO_Research `
  -ApiBaseUrl http://127.0.0.1:8080 `
  -ApiKey dev-local-key `
  -TradeSymbol XAUUSD
```

Lo script copia e compila l'EA in:

- Ultima Markets MT5;
- STARTRADER Financial MetaTrader 5;
- XM MT5;
- Vantage International MT5.

Crea anche il preset:

```text
MQL5\Presets\TradinGoSignalClient_DRYRUN.set
```

con `EnableLiveTrading=false`.

Attach manuale consigliato per il primo test:

1. aprire un grafico `XAUUSD` su una MT5 demo;
2. verificare `Algo Trading` attivo;
3. abilitare WebRequest verso `http://127.0.0.1:8080`;
4. trascinare `Expert Advisors > TradinGo > TradinGoSignalClient` sul grafico;
5. caricare il preset `TradinGoSignalClient_DRYRUN.set`;
6. controllare nei log Experts che arrivi `DRY_RUN`;
7. verificare nell'API `/accounts/heartbeats` e `/signals/ack`.

Controlli locali dell'EA:

- API key obbligatoria;
- simbolo coerente;
- spread massimo;
- RR minimo 1:2;
- risk_pct non superiore al limite locale;
- sizing basato su equity, tick size e tick value;
- ack remoto per `DRY_RUN`, `REJECTED`, `EXECUTED`, `ERROR`.

## Test demo multi-broker suggerito

1. avviare API in locale sulla VPS;
2. pubblicare un segnale demo con `EnableLiveTrading=false`;
3. verificare ack e heartbeat da ogni MT5;
4. passare un solo terminale demo a `EnableLiveTrading=true`;
5. testare solo lotti minimi e mercato chiuso/riaperto;
6. confrontare ordini, spread, rejection e log per broker.
