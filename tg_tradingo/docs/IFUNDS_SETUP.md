# iFunds — equity floor guard, kill switch e sizing dal serbatoio (EA v2.12)

Regola unica del conto iFunds: **non superare il drawdown massimo statico, calcolato
sull'equity** (quindi conta il flottante intraday, non solo il realizzato). Il floor
è fissato al punto di partenza e non si muove.

Tutti i nuovi input hanno **default neutro**: con `InpDdMaxPct=0`,
`InpDdSizingEnabled=false`, `InpMaxConcurrentLots=0` la build si comporta esattamente
come la v2.11 sui demo Vantage/Ultima. I guard si accendono solo dal `.set` iFunds.

## 1. Equity floor guard

```
floor        = InpDdStartEquity * (1 - InpDdMaxPct/100)
allowance    = InpDdStartEquity - floor
livello_X%   = floor + allowance * (1 - X/100)     // X = % di allowance consumata
```

Piano 6% su 10k → floor 9.400, allowance 600, chiusura a 9.520 (80%), blocco nuove
aperture a 9.640 (60%).

| Comportamento | Dove |
|---|---|
| Controllo su `ACCOUNT_EQUITY` a ogni tick | `CheckEquityFloorGuard()`, chiamata da `OnTick()` |
| Equity ≤ livello `InpDdCloseAtPct` → chiude **tutte** le posizioni TG e latch dell'halt | `CloseAllOurPositions("KILLSWITCH_EQUITY_FLOOR")` + `DdSetHalted(true)` |
| Equity ≤ livello `InpDdBlockNewAtPct` → blocca solo le **nuove aperture** | `IsOpenBlocked()` |
| L'halt sopravvive al riavvio del terminale | GlobalVariable `TG_TRADINGO_DD_HALT` |
| Reset manuale obbligatorio | cancellare la GlobalVariable `TG_TRADINGO_DD_HALT` |
| Errori di chiusura loggati a livello ERROR | `CloseAllOurPositions()` |

Si chiude **prima** del floor per costruzione: al floor esatto il breach è già avvenuto,
perché i fill arrivano dopo la decisione. Le chiusure sono marcate nel journal con
`close_reason=KILLSWITCH_EQUITY_FLOOR`.

`InpDdStartEquity=0` fa catturare l'equity al primo init e la persiste in
`TG_TRADINGO_DD_START`: sul conto iFunds è però meglio scriverla esplicitamente
(10000) così il floor non dipende dal momento in cui l'EA è stato attaccato.

## 2. Kill switch manuale

Diverso dal floor guard: quello è automatico, questo è la leva in mano all'operatore.
Basta creare il file `InpHaltFlagFile` (default `tradingo_halt.flag`) in
`MQL5\Files\` — non serve riavviare né togliere l'EA dal grafico:

- blocca tutte le nuove aperture entro 2 secondi;
- **non** chiude nulla: le posizioni aperte restano sotto gestione normale
  (BE, TP, SL, comandi Telegram di chiusura continuano a funzionare);
- cancellando il file le aperture riprendono, con log della transizione.

## 3. Sizing dal serbatoio

```
serbatoio = picco_equity_CHIUSA (balance) - floor        // non scende mai
lotto     = (serbatoio_quantizzato * InpDdUtilizationPct/100) / float_per_0.01_lotti * 0.01
```

- `float_per_0.01` è il flottante peggiore misurato per canale (`InpDdFloatIvan` ecc.,
  default dalla settimana 24-30/07: IVAN 39,9 · GOLD 15,0 · ORO 12,4 · STARK 10,4).
- Il serbatoio usa il **picco di balance**, non l'equity: un flottante positivo
  temporaneo non aumenta la size.
- Quantizzazione a scatti di `InpDdStepPct` % dell'allowance iniziale (default 10%):
  la size cambia solo quando il serbatoio cresce di un gradino intero.
- Il lotto viene ricalcolato **solo a posizioni chiuse**: finché c'è esposizione TG
  aperta si riusa il valore in cache, così un segnale non cambia size a metà.
- `InpDdMaxLot` è il tetto per posizione. Se il lotto calcolato scende sotto il
  volume minimo del broker, il segnale viene rifiutato con log (mai arrotondato in su).

Serbatoio iniziale 600 (piano 6% su 10k), utilizzo 50%:

| Canale | Lotto teorico per posizione | Con `InpDdMaxLot=0.05` |
|---|---:|---:|
| IVAN (per TP, 4 TP per segnale) | 0,07 | 0,05 |
| ORO | 0,24 | 0,05 |
| GOLD | 0,19 | 0,05 |
| STARK | 0,28 | 0,05 |

Il cap parte a 0,05 di proposito: 0,07 su IVAN significa consumare ~47% del serbatoio
con il flottante peggiore *già osservato*, e una settimana peggiore di quella non
lascia margine. Alzarlo quando il serbatoio è cresciuto con profitti realizzati.

## 4. Cap esposizione concorrente

`InpMaxConcurrentLots` (0 = off) è il tetto sui lotti TG aperti contemporaneamente.
La verifica è **per posizione** dentro `OpenMarket()`: i primi TP di un segnale
restano aperti e solo il volume oltre il cap viene rifiutato, con riga
`CANCELLED_LOTS_CAP` in `tradingo_signal_stats.csv`.

## 5. Mapping input → preset iFunds 10k (piano 6% / split 80%)

| Input | Default sorgente | Preset iFunds 10k | Perché |
|---|---:|---:|---|
| `InpChannels` | `gold,forex,oro,stark,ivan` | `ivan,stark` | canali migliori per coerenza segnali/risultati |
| `InpLotIvan` / `InpLotStark` | 0.0 | 0.05 | fallback se il sizing dinamico è spento |
| `InpMagicOffset` | 0 | 500000 | nessuna collisione con il demo Vantage #24988286 |
| `InpMaxFloatingLossUSD` | 150.0 | 300.0 | 50% dell'allowance: il floor guard è la protezione primaria |
| `InpMaxHoldingMinutes` | 0 | 0 | invariato |
| `InpDdMaxPct` | 0.0 | 6.0 | piano scelto |
| `InpDdStartEquity` | 0.0 | 10000.0 | floor statico esplicito |
| `InpDdCloseAtPct` | 80.0 | 80.0 | chiusura a 9.520 |
| `InpDdBlockNewAtPct` | 60.0 | 60.0 | stop alle nuove entrate a 9.640 |
| `InpHaltFlagFile` | `tradingo_halt.flag` | idem | kill switch manuale |
| `InpDdSizingEnabled` | false | true | sizing dal serbatoio attivo |
| `InpDdUtilizationPct` | 50.0 | 50.0 | scelta operativa |
| `InpDdStepPct` | 10.0 | 10.0 | scatti del 10% |
| `InpDdMaxLot` | 0.0 | 0.05 | tetto prudenziale iniziale |
| `InpDdFloat*` | valori misurati | invariati | flottante per 0,01 lotti per canale |
| `InpMaxConcurrentLots` | 0.0 | 0.30 | IVAN 4×0,05 + STARK 0,05 |

Preset: `mql5/presets/TG_TradinGo_iFunds_10k_dd6.set` e
`mql5/presets/TG_TradinGo_iFunds_50k_dd6.set` (stessa logica su 50k: floor 47.000,
allowance 3.000, cap 0,25).

## 6. Runbook

**Avvio**

1. Copiare `mql5/TG_TradinGoEA.mq5` in `MQL5\Experts\` del terminale iFunds e compilare.
2. Attaccare l'EA a XAUUSD, `Inputs -> Load` → `TG_TradinGo_iFunds_10k_dd6.set`.
3. Verificare nel log di init le due righe:
   - `DD_GUARD armed | start=10000.00 ... floor=9400.00 ... close_all_at_equity=9520.00 block_new_at_equity=9640.00`
   - `v2.12 prop guards | dd_max_pct=6.00 ... dd_sizing=true ...`
   Se `halted=YES`, l'halt di un breach precedente è ancora attivo.
4. Confermare che il bridge scriva l'heartbeat (`HEARTBEAT fresh`).

**Fermare le aperture (kill switch)**

```
echo halt > <terminal_data>\MQL5\Files\tradingo_halt.flag   :: blocca
del        <terminal_data>\MQL5\Files\tradingo_halt.flag    :: riprende
```
Conferma nel log: `KILL_SWITCH ON` / `KILL_SWITCH OFF`.

**Ripartire dopo un breach del floor**

1. Capire perché (journal `trades_*.csv`, righe `KILLSWITCH_EQUITY_FLOOR`).
2. Cancellare la GlobalVariable `TG_TRADINGO_DD_HALT` (Tools → Global Variables).
3. Se il conto è stato ricaricato/sostituito, aggiornare `InpDdStartEquity` e
   cancellare anche `TG_TRADINGO_DD_START` e `TG_TRADINGO_DD_PEAK`.

**Righe di log da controllare ogni giorno**

| Riga | Significato |
|---|---|
| `DD_GUARD armed` | floor e soglie effettive all'avvio |
| `CRITICAL DD_BREACH` | floor guard scattato: tutto chiuso, halt attivo |
| `OPEN blocked — equity=... <= block_level=...` | siamo oltre il 60% dell'allowance |
| `DD_SIZING channel=... lot=...` | nuovo lotto calcolato dal serbatoio |
| `DD_SIZING below broker minimum` | serbatoio troppo piccolo: segnale rifiutato |
| `OPEN rejected — concurrent lots cap` | cap esposizione raggiunto |
| `KILL_SWITCH ON/OFF` | flag manuale |
| `KILLSWITCH_FLOATING bucket=` | flottante di bucket oltre `InpMaxFloatingLossUSD` |

## 7. Procedure di test manuale

Nessuna di queste richiede il conto reale: si eseguono sul demo con
`InpDdStartEquity` impostato vicino all'equity corrente.

| Guard | Procedura | Atteso |
|---|---|---|
| Floor guard | `InpDdMaxPct=6`, `InpDdStartEquity` = equity attuale + 500 (così l'allowance risulta quasi consumata) | log `CRITICAL DD_BREACH`, tutte le posizioni TG chiuse, `close_reason=KILLSWITCH_EQUITY_FLOOR`, aperture successive rifiutate |
| Persistenza halt | dopo il breach, rimuovere e riattaccare l'EA | init stampa `halted=YES` e le aperture restano bloccate |
| Reset | cancellare `TG_TRADINGO_DD_HALT` e riattaccare | init stampa `halted=no`, aperture riammesse |
| Kill switch | creare `tradingo_halt.flag`, poi inviare un segnale di test | `KILL_SWITCH ON`, `OPEN blocked — kill switch flag`, posizioni aperte non toccate |
| Sizing | `InpDdSizingEnabled=true`, variare `InpDdUtilizationPct` a conto piatto | `DD_SIZING channel=... lot=...` coerente con la formula; a posizioni aperte il lotto non cambia |
| Sizing sotto minimo | `InpDdUtilizationPct=1` | `DD_SIZING below broker minimum`, nessuna apertura |
| Cap lotti | `InpMaxConcurrentLots=0.10` con IVAN a 0,05 per TP | primi 2 TP aperti, TP successivi con `OPEN rejected — concurrent lots cap` e riga `CANCELLED_LOTS_CAP` |

Compilazione verificata con MetaEditor64 (`0 errors, 0 warnings`).
