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

Il passo successivo, dopo validazione della strategia, e':

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
