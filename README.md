# TradinGo System

## Dipendenze Python

Il repo usa questi pacchetti Python:

- `pandas`
- `numpy`
- `streamlit`
- `MetaTrader5` dove supportato

`requirements.txt` include `MetaTrader5` solo su Windows, perche il pacchetto ufficiale
non e disponibile nell'ambiente cloud Linux.

### Setup ambiente cloud

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

## TSENTRY_DB_PATH

Gli engine SQLite leggono il path del database condiviso dalla variabile ambiente
`TSENTRY_DB_PATH`.

Default:

```text
C:/tradingo_math/tradingo.db
```

Esempio PowerShell, valido per la sessione corrente:

```powershell
$env:TSENTRY_DB_PATH = "C:\tradingo_math\tradingo.db"
```

Esempio PowerShell persistente per l'utente Windows:

```powershell
[Environment]::SetEnvironmentVariable("TSENTRY_DB_PATH", "C:\tradingo_math\tradingo.db", "User")
```

Esempio CMD, valido per la sessione corrente:

```bat
set TSENTRY_DB_PATH=C:\tradingo_math\tradingo.db
```

## Uso su VPS Windows / MetaTrader 5

Prerequisiti:

1. Python 3 installato e disponibile come `py` o `python`.
2. Terminali MT5 installati nei path configurati negli script:
   - `tradingo_prop.py`: `C:/Program Files/STARTRADER Financial MetaTrader 5/terminal64.exe`
   - `tradingo_hedge.py`: `C:/Program Files/Ultima Markets MT5 Terminal/terminal64.exe`
3. MT5 gia configurato con login, simbolo `XAUUSD` visibile nel Market Watch e storico M5/M15 disponibile.

Setup:

```powershell
cd C:\tradingo_system
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:TSENTRY_DB_PATH = "C:\tradingo_math\tradingo.db"
```

Verifica ambiente:

```powershell
python -c "import MetaTrader5, numpy, pandas; print('MetaTrader5 OK'); print('numpy', numpy.__version__); print('pandas', pandas.__version__)"
```

Avvio engine singoli:

```powershell
python tsentry_runner.py hedge --db-path "C:\tradingo_math\tradingo.db"
python tsentry_runner.py prop --db-path "C:\tradingo_math\tradingo.db"
```

Avvio prop + hedge insieme:

```powershell
python tsentry_runner.py both --db-path "C:\tradingo_math\tradingo.db"
```

Modalita fast prop:

```powershell
python tsentry_runner.py prop-fast --db-path "C:\tradingo_math\tradingo.db"
```

Il runner crea la cartella del DB se manca, inizializza la tabella `state` e passa
`TSENTRY_DB_PATH` agli engine avviati.

## Backtest MZ_MA_Scalper

Il file `backtest_mz_ma_scalper.py` ricostruisce in Python la logica dell'EA
`MZ_MA_Scalper.mq5` basata su medie mobili:

- EMA/SMA fast/slow su barra chiusa
- setup `BREAK` e `BOUNCE`
- filtro orario e filtro spread
- SL iniziale
- lotto fisso o rischio percentuale
- trailing stop a scaglioni approssimato su OHLC

Nota importante: il repo non contiene ancora un dataset storico OHLC Gold
versionato (`.csv`, `.db`, `.parquet`). I log presenti sono utili per analisi
forward/live, ma non bastano per un backtest riproducibile della strategia MA.

### Export storico Gold da VPS Windows / MT5

Esempio PowerShell su VPS, dopo aver attivato `.venv`:

```powershell
python export_mt5_gold_rates.py `
  --symbol XAUUSD `
  --timeframe M1 `
  --from-date 2026-04-01T00:00:00 `
  --to-date 2026-04-30T23:59:59 `
  --output data\xauusd_m1_2026-04.csv `
  --terminal-path "C:\Program Files\STARTRADER Financial MetaTrader 5\terminal64.exe"
```

Se il broker usa un nome diverso, sostituire `--symbol XAUUSD` con ad esempio
`GOLD` o `GOLD#`.

### Esecuzione backtest

```powershell
python backtest_mz_ma_scalper.py `
  --csv data\xauusd_m1_2026-04.csv `
  --fixed-spread-points 20 `
  --trades-out reports\mz_ma_trades.csv `
  --summary-out reports\mz_ma_summary.json
```

Esempio cloud/Linux sullo stesso CSV:

```bash
python3 backtest_mz_ma_scalper.py \
  --csv data/xauusd_m1_2026-04.csv \
  --fixed-spread-points 20 \
  --trades-out reports/mz_ma_trades.csv \
  --summary-out reports/mz_ma_summary.json
```

Il risultato stampato include numero trade, win rate, profitto netto,
profit factor e drawdown monetario massimo. L'approssimazione usa candele OHLC,
quindi non sostituisce il tester tick-by-tick nativo di MT5 quando servono spread
variabile, slippage e sequenza intra-candela reale.
