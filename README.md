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
