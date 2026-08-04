# Pattern GO

Trading automatico della strategia **Pattern GO** su oro (`XAU`) tramite API REST
**DXtrade**, su conto **Velotrade PRO 1-Step 10k**.

Prima release: **solo demo/challenge**. Lo scopo non è fare profitto, è misurare lo
scostamento fra backtest ed esecuzione reale: spread, slippage, fill mancati, latenza.
Ogni evento finisce in un journal JSON e `analyze_logs` lo confronta con i numeri del
backtest.

Il modulo è isolato dal resto della repo: nessun import da `tg_tradingo/` o da StatArb,
configurazione, log e stato propri.

## Struttura

```
pattern_go/
  pattern_go/
    types.py         tipi condivisi (Bar, Swing, PendingOrder, OpenTrade, ...)
    strategy.py      logica pura: swing, sessioni, bias, pattern, filtri, TP
    engine.py        macchina a stati di una strategia (un timeframe) -> intenzioni
    risk.py          regole Velotrade: floor statico, daily loss, sizing
    dxtrade.py       client REST DXtrade (login, quote, candele, ordini)
    config.py        configurazione esterna, credenziali da variabili d'ambiente
    runner.py        servizio persistente: polling, esecuzione, riconciliazione
    journal.py       logging JSON con rotazione
    report.py        report giornaliero
    analyze_logs.py  confronto forward test vs backtest
  tools/
    spread_sampler.py  campionatore di spread reale su XAU
  config.example.json
  tests/
```

## Avvio

```bash
python3 -m pip install -r requirements.txt
cp config.example.json config.json          # config.json NON va committato
export DXTRADE_USERNAME=...                 # secret, mai nel file di configurazione
export DXTRADE_PASSWORD=...
python3 -m pattern_go --config config.json --dry-run   # verifica credenziali e dati
python3 -m pattern_go --config config.json             # servizio
```

Analisi e report:

```bash
python3 -m pattern_go.analyze_logs --log-dir logs            # forward test vs backtest
python3 -m pattern_go.analyze_logs --log-dir logs --json
python3 tools/spread_sampler.py --minutes 720 --interval 60  # spread reale su 12h
```

Kill switch: crea il file indicato in `runtime.kill_switch_file` (default `KILL_SWITCH`).
Con `kill_switch_closes_positions: true` chiude tutto e blocca il ciclo; per riprendere,
cancella il file.

## Regole del conto implementate

| Regola Velotrade PRO 1-Step | Implementazione |
|---|---|
| Max drawdown 3% **statico** | floor fisso a `initial_balance × 0.97` = 9.700 USD, mai spostato |
| Daily loss 3% | floor giornaliero = `saldo_chiusura_ieri × 0.97`, reset **00:30 UTC** |
| Valutazione su equity flottante | il guard usa l'equity, non il saldo chiuso |
| — | `floor_effettivo = max(floor_statico, floor_giornaliero)` |

Sizing (nessun valore hardcoded, tutto in `config.json`):

```
serbatoio  = min( min(saldo, cap_size) − 9.700 ,  equity − floor_effettivo )
rischio $  = risk_fraction × serbatoio            # risk_fraction = 0.05
quantità   = rischio $ / distanza_SL              # arrotondata a 0.01 per difetto
```

All'attivazione: serbatoio 300 USD → 15 USD di rischio per trade → con SL mediano di
backtest (3,67 USD) circa **4,08 once**. Poiché il rischio è una *frazione* del
serbatoio, 200 perdite piene consecutive non possono portare il saldo sotto il floor
(verificato nei test). Se la quantità calcolata scende sotto `min_quantity` viene
alzata a **0,01** (scelta esplicita: `round_below_min_to_min`).

Guard a due livelli sul consumo dell'allowance giornaliera:
al **60%** blocco nuovi ingressi, all'**80%** chiusura di tutto e blocco fino al reset.

Limiti di esposizione: **1 posizione per strategia, 2 in totale** (1 M5 + 1 M15).

## Assunzioni e punti aperti

Verificato direttamente contro l'API (sola lettura, nessun ordine inviato):

- base URL `https://dx.velotrade.com/dxsca-web`, login con `username`/`domain`/`password`,
  header `Authorization: DXAPI <sessionToken>`, sessione con timeout 30 minuti;
- account `default:130000638`, equity/saldo 10.000 USD;
- **il simbolo dell'oro è `XAU`, non `XAUUSD`**;
- `XAU` è un CFD con `lotSize = 1.0`, `quantityIncrement = 0.01`, `priceIncrement = 0.01`:
  la quantità è in **once**, quindi non vale il modello "1 lotto = 100 once" del backtest e
  la granularità è 100× più fine di MT4 (il problema del lotto minimo non esiste);
- quote e candele M5/M15 disponibili via `POST /marketdata`.

Assunzioni **non ancora verificate in esecuzione**, da confermare col primo ordine demo:

1. **payload degli ordini**: lo stop d'ingresso viene inviato come ordine `STOP` con SL e TP
   come richieste collegate. La forma esatta accettata da questo broker (ordine OCO/bracket
   vs. due ordini separati) va confermata con un ordine demo di quantità minima;
2. **rilevamento del fill**: dedotto confrontando le posizioni del broker prima/dopo, perché
   non c'è ancora uno stream di esecuzioni. Il prezzo di fill usato per lo slippage è
   `openPrice` della nuova posizione;
3. **SL/TP lato broker**: se il broker non accettasse gli ordini collegati, SL e TP vanno
   gestiti dal runner (uscita a mercato), con slippage maggiore;
4. **spread**: il filtro `risk_spread_mult` è il parametro che decide la tradabilità. Prima
   misura alle 22:11 UTC (rollover): 162 punti — a quel livello M5 non entrerebbe mai. Nei
   minuti successivi lo spread è tornato a 1–42 punti (mediano 16,5), compatibile coi filtri.
   Serve il campione su 24h di `spread_sampler.py` prima di trarre conclusioni;
5. **timezone delle sessioni**: le sessioni sono definite con timezone IANA
   (`Europe/Rome`, `America/New_York`), quindi seguono la DST; l'orario di apertura deve
   cadere esattamente su un'apertura di barra del timeframe.

Il runner **non è ancora stato eseguito contro il conto demo**: nessun ordine è stato
inviato, né in demo né in reale.

## Deploy sul VPS (da autorizzare)

Non ancora eseguito. Procedura prevista sul Contabo (`144.91.76.28:2222`, Windows Server),
in una cartella separata da `C:\TG_TradinGo\`:

1. `C:\PatternGO\` con il codice e un virtualenv Python 3.11+;
2. `config.json` sul VPS (non in repo), credenziali in variabili d'ambiente del servizio;
3. Scheduled Task Windows all'avvio, con riavvio automatico, che lancia
   `python -m pattern_go --config C:\PatternGO\config.json`;
4. log in `C:\PatternGO\logs\`, report in `C:\PatternGO\reports\`;
5. controllo giornaliero con `analyze_logs`: se lo slippage medio su M5 supera 30 punti, o
   il costo round-trip stimato supera il break-even (85 punti M5, 151 M15), la strategia va
   fermata — `analyze_logs` esce con codice 1 in questi casi.

## Test

```bash
python3 -m ruff check .
PYTHONPATH=. python3 -m pytest tests -q
```
