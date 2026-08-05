# Test report — Pattern GO (PR #38, branch `devin/1785881125-pattern-go`)

Test **da riga di comando** (nessuna GUI → nessuna registrazione video).
Conto demo Velotrade `default:130000638`, credenziali via env `DXTRADE_USERNAME` /
`DXTRADE_PASSWORD` (mai scritte su disco, verificato con grep).

**Esito complessivo: il dry-run contro il conto demo NON funziona.** Due chiamate su tre
del percorso di trading (candele di warmup, invio ordine, chiusura posizione) usano payload
rifiutati dal broker. Con 3 ordini demo da 0.01 once ho individuato i payload corretti.
Il conto è stato riportato a **0 posizioni / 0 ordini** (verificato).

---

## Riepilogo assertion

| # | Test | Esito |
|---|---|---|
| T1 | `ruff check .` pulito | ✅ passato ("All checks passed!") |
| T1 | `pytest tests` verde | ⚠️ passato con nota: **78 passed**, non 79 |
| T2 | Dry-run reale: login + strumento XAU + metrics | ✅ passato |
| T2 | Dry-run reale: warmup M5/M15 + evento STARTUP + exit 0 | ❌ **FALLITO** (HTTP 400 `<toTime>`) |
| T2b | Dry-run con patch temporanea `toTime`: STARTUP/WARMUP corretti | ✅ passato |
| T3 | Nessuna password né `sessionToken` nei log | ✅ passato (0 occorrenze) |
| T4 | Kill switch ferma il ciclo e logga l'evento | ✅ passato |
| T5 | `analyze_logs` + report giornaliero senza trade, nessuna eccezione | ✅ passato |
| T6.1 | Password errata → errore chiaro, nessun retry loop | ✅ passato |
| T6.2 | Credenziali mancanti → errore chiaro prima della rete | ✅ passato |
| T6.3 | `config.json` senza `broker`/`risk` → KeyError col nome del campo | ✅ passato (ma stack trace grezzo) |
| T6.4 | `risk_fraction` negativa rifiutata | ❌ **FALLITO** (accettata, quantità 0.01) |
| T6.5 | Floor sopra il saldo → nessuna quantità positiva | ❌ **FALLITO** (quantità 0.01) |
| T6.6 | Simbolo inesistente → errore chiaro | ✅ passato |
| T7 | Barre di warmup coerenti su dati veri | ✅ passato |
| T8 | Spread reale XAU misurato | ✅ misurato: mediano **3.0 punti** |
| T9 | Payload stop order accettato dal broker | ❌ **FALLITO** (`legs` → 400) |
| T10 | Fill detection + slippage + `TRADE_OPENED` | ✅ passato (con payload corretto) |
| T10 | `close_position()` accettato dal broker | ❌ **FALLITO** (`legs` → 400, poi manca `positionCode`) |
| T10b | Ciclo completo open→fill→close con payload corretti + `TRADE_CLOSED` | ✅ passato |

---

## Difetti trovati (in ordine di gravità)

### 1. BLOCCANTE — il warmup non funziona: `candles()` senza `toTime` è rifiutato

`pattern_go/runner.py:342` chiama `self.client.candles(symbol, timeframe, frm)` senza
`to_time`, e il broker rifiuta la richiesta. Il dry-run muore con exit 1 **prima** di
scrivere l'evento `STARTUP`:

```
pattern_go.dxtrade.DXTradeError: POST /marketdata: 400
{"errorCode":"32","description":"Incorrect request parameters: <toTime> for event type Candle"}
```

Journal prodotto dal dry-run reale — solo `RECONCILE`, nessun `STARTUP`, nessun `WARMUP`:

```json
{"event": "RECONCILE", "order_codes": [], "orders": 0, "position_ids": [], "positions": 0, "ts": "2026-08-05T06:07:13.525400+00:00"}
```

Confermato in isolamento che è `toTime` la causa:

```
candles NO toTime   -> DXTradeError 400 ... <toTime> for event type Candle
candles WITH toTime -> 20 barre OK
```

**Fix**: passare `datetime.now(UTC)` come `to_time` in `_closed_bars`.
Impatto: il servizio non parte mai in produzione (`run()` chiama `startup()`).

### 2. BLOCCANTE — payload ordine rifiutato: il campo `legs` non è accettato

`place_stop_order()` (`dxtrade.py:311`) e `close_position()` (`dxtrade.py:358`) inviano
`legs`. Il broker rifiuta:

```
--- A: STOP + orderRequests SL/TP collegati (codice attuale)
RIFIUTATO: 400 {"errorCode":"32","description":"Incorrect request parameters: Order request is incorrect"}

--- B: STOP + legs, senza SL/TP
RIFIUTATO: 400 {"errorCode":"32","description":"Incorrect request parameters: Order request is incorrect"}

--- C: STOP senza legs, senza orderRequests
ACCETTATO: {"orderId": 2534716, "updateOrderId": 2534716}
```

**Payload di ingresso che funziona** (ordine visto come `WORKING` in `orders()`):

```json
{"account":"default:130000638","orderCode":"PG-C-...","type":"STOP","instrument":"XAU",
 "quantity":0.01,"positionEffect":"OPEN","side":"BUY","stopPrice":4194.18,"tif":"GTC"}
```

Conseguenza aperta: **SL e TP collegati non sono supportati in questa forma**. Non ho
trovato una variante accettata di `orderRequests`; servono SL/TP gestiti dal runner o una
forma di bracket diversa (assunzione #3 del README quindi si conferma necessaria).

`cancel_order(clientOrderId)` invece **funziona** come implementato:

```
ordini pendenti: [('PG-C-1785910097', 'dxsca-integration-session-code:PG-C-1785910097', 'WORKING')]
cancel_order('PG-C-1785910097') -> {'orderId': 2534716, 'updateOrderId': 2534735}
ordini dopo cancel: []
```

### 3. BLOCCANTE — `close_position()` non chiude: serve `positionCode`

Con il codice attuale la chiusura falliva e il journal registrava `CLOSE_FAILED`, **lasciando
la posizione aperta sul conto**:

```json
{"event":"CLOSE_FAILED","client_order_id":"PG-M5-L-20260805T060907","strategy":"M5",
 "error":"POST /accounts/default:130000638/orders: 400 {\"errorCode\":\"32\",\"description\":\"Incorrect request parameters: Order request is incorrect\"}"}
```

Togliendo `legs` l'errore cambia e rivela il campo mancante:

```
RIFIUTATO: 400 {"errorCode":"33","description":"Incorrect request. <positionCode>"}
```

**Payload di chiusura che funziona** (posizione chiusa, conto a zero):

```json
{"account":"default:130000638","orderCode":"PG-CL1-...","type":"MARKET","instrument":"XAU",
 "quantity":0.01,"positionEffect":"CLOSE","side":"SELL","tif":"IOC","positionCode":"2534790"}
```

Nota operativa importante: `close_position()` non riceve il `positionCode`; va propagato da
`OpenTrade.position_id` (vedi difetto 5). **Questo rende oggi non funzionanti anche il kill
switch con `kill_switch_closes_positions: true` e il risk guard `CLOSE_ALL` contro il broker
reale**: loggano l'evento ma non chiudono nulla.

### 4. GRAVE — `risk_fraction` negativa e serbatoio nullo producono comunque quantità 0.01

Logica pura, nessuna rete:

```
=== risk_fraction=-0.05
 static_floor: 9700.0 reservoir: 300.0 risk_amount: -15.0
 quantity(sl=3.67): (0.01, 'rounded_up_to_min')     <-- ordine valido con rischio negativo
 evaluate: ('ALLOW', 'ok')

=== initial_balance=20000 (floor 19400 > saldo 10000)
 static_floor: 19400.0 reservoir: 0.0 risk_amount: 0.0
 quantity(sl=3.67): (0.01, 'rounded_up_to_min')     <-- ordine anche con serbatoio zero
 evaluate: ('CLOSE_ALL', 'equity_at_or_below_floor')
```

`round_below_min_to_min` maschera rischio negativo o nullo: una config assurda non viene
rifiutata, si traduce in ordini reali al lotto minimo. Nel secondo caso il risk guard
(`CLOSE_ALL`) protegge a runtime, nel primo **no**. Manca validazione della config
(`risk_fraction > 0`, floor < saldo) all'avvio.

### 5. MINORE — `position_id` perso: `engine.on_fill()` ignora il parametro

`engine.py:289-307`: `on_fill(fill_price, position_id=...)` accetta `position_id` ma non lo
assegna a `OpenTrade`, quindi `trade.position_id` resta `None`:

```
trade: OpenTrade(..., entry_price=4146.57, theoretical_entry_price=4145.95, position_id=None)
```

Il journal salva comunque il `position_id` (passato come extra da `_detect_fill`), ma il
runner non ha il codice posizione in memoria — proprio il valore che serve per la chiusura
(difetto 3).

### 6. MINORE — errori di config come stack trace grezzo

`config.json` senza sezioni obbligatorie termina con `KeyError: 'broker'` / `KeyError: 'risk'`
e traceback completo, invece di un messaggio d'errore leggibile. Credenziali mancanti/errate
sono gestite meglio (`ValueError`/`AuthError` con messaggio chiaro) ma anch'esse con traceback.

---

## Dettaglio dei test passati

### T1 — Lint e unit test

```
$ python3 -m ruff check .
All checks passed!
$ PYTHONPATH=. python3 -m pytest tests
78 passed in 0.12s
```

I test attesi erano 79: ne risultano **78**. Nessun test fallito o skippato.

### T2b — Dry-run con patch temporanea di `toTime` (per provare il resto dello startup)

Ho applicato una patch **temporanea e già ripristinata** (`runner.py` è bit-identico
all'originale, verificato con `diff`) che passa `datetime.now(UTC)` come `to_time`. Con quella
il dry-run arriva a exit 0 e scrive tutto:

```json
{"event": "WARMUP", "strategy": "M5",  "bars": 399}
{"event": "WARMUP", "strategy": "M15", "bars": 399}
{"event": "STARTUP", "symbol": "XAU", "quantity_increment": 0.01,
 "balance": 9999.92, "equity": 9999.92, "static_floor": 9700.0, "effective_floor": 9700.0,
 "reservoir": 299.9200000000001, "risk_amount": 14.996000000000004,
 "strategies": ["M15", "M5"]}
```

`static_floor` = **9700.0** come richiesto. `reservoir` 299.92 e `risk_amount` 14.996 invece
di 300/15 **solo** perché il saldo era 9999.92 dopo i miei ordini di prova (−0.08 USD di
costi): la formula è corretta, e con saldo 10.000 esatti i valori 300.0 / 15.0 sono verificati
dallo unit test `test_startup_reconciles_and_logs_the_floor`.

### T3 — Nessun segreto nei log

`grep -Rqi` di username, password e `sessionToken` su `logs/`, `state/`, `reports/`, sugli
stdout catturati dei dry-run e sui campioni di spread → **exit 1, zero occorrenze**.

### T4 — Kill switch (FakeClient, nessuna chiamata al broker)

```
KILL_SWITCH events: [{'closes': True, 'event': 'KILL_SWITCH', 'ts': '...'}]
ordini piazzati: [] chiusure: []
dopo rimozione del file, KILL_SWITCH totali: 1   (il ciclo riprende)
```

Il ciclo si ferma e logga. **Attenzione**: con un broker reale la chiusura non avverrebbe
(difetto 3).

### T5 — `analyze_logs` e report giornaliero su journal senza trade

```
$ python3 -m pattern_go.analyze_logs --log-dir logs
# Pattern GO — forward test vs backtest
EXIT=0
$ python3 -m pattern_go.analyze_logs --log-dir logs --json
{"strategies": {}, "warnings": []}
EXIT=0
```

Nessuna eccezione, exit 0. Report giornaliero generato correttamente:

```
# Pattern GO — report 20260805
Equity: 10000.00 · floor effettivo: 9700.00 · margine: 300.00
Errori API/esecuzione loggati: 0
| strategia | trade | win rate | PnL | R medio | slippage medio | spread medio | segnali scartati |
| - | 0 | — | 0.0 | — | — | — | 0 |
```

### T7 — Coerenza barre di warmup su dati veri

```
M5: richieste 400, ricevute 400, chiuse 399
  crescenti: True | allineate a 5min: True
  barre in formazione scartate: 1 (['2026-08-05T06:10:00+00:00'])
  gap non-standard: 0 | coerenza OHLC: True
M15: richieste 400, ricevute 400, chiuse 399
  crescenti: True | allineate a 15min: True
  barre in formazione scartate: 1 (['2026-08-05T06:00:00+00:00'])
  gap non-standard: 0 | coerenza OHLC: True
```

Ordinamento crescente, nessun buco, barra in formazione correttamente esclusa da
`_closed_bars`, OHLC coerenti.

### T10 / T10b — Fill detection, slippage e ciclo completo (ordini demo 0.01 once)

Primo fill, in un momento di mercato mosso:

```
bid/ask: 4145.76 / 4145.90  (spread 14 punti), trigger BUY stop 4145.95
posizione: {"positionCode":"2534790","openPrice":4146.57,"quantity":0.01,"side":"BUY"}
FILL entry 4146.57 vs teorico 4145.95 -> SLIPPAGE 62.0 punti
```

`_detect_fill()` rileva correttamente la nuova posizione confrontando `positions()`, e il
campo del prezzo di fill è **`openPrice`**, esattamente come previsto dal codice. Journal:

```json
{"event":"TRADE_OPENED","strategy":"M5","side":"LONG","theoretical_entry_price":4145.95,
 "entry_price":4146.57,"slippage":0.6199999999998909,"quantity":0.01,"risk_currency":0.05,
 "spread_at_signal":0.13999999999941792,"position_id":"2534790"}
```

Ciclo completo open→fill→close con i payload corretti (spread 1 punto, mercato fermo):

```json
{"event":"ORDER_PLACED","broker_order_id":"2534869","theoretical_entry_price":4150.0}
{"event":"TRADE_OPENED","entry_price":4150.0,"slippage":0.0,"position_id":"2534869"}
{"event":"TRADE_CLOSED","exit_price":4149.99,"exit_reason":"MANUAL","pnl":-0.0001,"r_realized":-0.002}
```

**Slippage reale misurato: 62 punti** sul primo fill (mercato mosso), **0 punti** sul secondo
(mercato fermo). Il primo valore, se rappresentativo, supera da solo la soglia di
disattivazione di M5 (30 punti medi) — serve un campione più ampio.

### Pulizia del conto (verificata)

```
VERIFICA FINALE CONTO
 positions: []
 orders: []
 metrics: AccountMetrics(equity=9999.92, balance=9999.92, open_pl=0.0, open_positions=0, open_orders=0)
```

3 ordini di ingresso in tutto (1 pendente cancellato, 2 eseguiti e chiusi), sempre 0.01 once.
Costo totale del test: **−0.08 USD** sul saldo demo. Nessuna posizione o ordine preesistente
toccato (il conto era vuoto all'inizio).

### T8 — Spread reale XAU

24 campioni a intervalli di 10 s, 2026-08-05 ~06:12–06:16 UTC:

```
campioni: 24
spread medio:   11.5 punti
spread mediano:  3.0 punti
min/max:         1.0 / 106.0 punti
M5:  con spread mediano servono SL >= 15 punti (backtest 367) -> PASSA
M15: con spread mediano servono SL >= 26 punti (backtest 713) -> PASSA
```

Con lo spread mediano di 3 punti i filtri `risk_spread_mult` non sono un ostacolo, ma i picchi
(106 punti) mostrano che il campione su 12–24 h resta necessario. Campione grezzo:
`/tmp/spread_samples.jsonl`.

---

## Note

- Nessuna modifica permanente al codice: `git status` mostra solo il file di piano non
  tracciato; `pattern_go/runner.py` è identico all'originale.
- Le credenziali non sono state scritte su disco in nessun file.
