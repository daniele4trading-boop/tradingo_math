# Test report — Pattern GO, giro 2 (verifica dei fix, commit `bfe1ade`)

Branch `devin/1785881125-pattern-go`, HEAD `2b806fb` (contiene `bfe1ade`).
Test da shell (nessuna GUI → nessuna registrazione). Conto demo Velotrade
`default:130000638`, credenziali via env `DXTRADE_USERNAME` / `DXTRADE_PASSWORD`.

**Esito: tutti i difetti bloccanti del giro 1 sono risolti.** 2 ordini demo da 0.01 once,
conto riportato a **0 posizioni / 0 ordini** (verificato). Nessun `CLOSE_FAILED` nel journal.
Resta un solo rilievo minore, non bloccante (§ Rilievi residui).

---

## Riepilogo assertion

| # | Test | Esito |
|---|---|---|
| 1 | `ruff check .` pulito | ✅ passato |
| 1 | `pytest tests` → 101 test verdi | ✅ passato |
| 2 | **Fix #1**: dry-run senza patch → exit 0, `WARMUP` M5+M15, `STARTUP` | ✅ passato |
| 3 | **Fix #2**: STOP lontano col codice del repo accettato, visibile in `orders()`, cancellato | ✅ passato |
| 4 | **Fix #5**: `on_fill` salva `position_id` in `OpenTrade` | ✅ passato |
| 5 | **Fix #3**: chiusura via `runner._close()` riuscita, `TRADE_CLOSED`, posizione sparita | ✅ passato |
| 6 | **Nuovo**: `_check_protective_exits` chiude con `exit_reason: STOP_LOSS` | ✅ passato |
| 7 | **Fix #4**: config invalide bloccate da `ConfigError` all'avvio | ✅ passato |
| 8 | Nessuna password né `sessionToken` nei log | ✅ passato (0 occorrenze) |
| 9 | Conto a 0 posizioni / 0 ordini a fine test | ✅ passato |
| 10 | Slippage e spread misurati su fill reali | ✅ misurato (vedi § Misure) |
| — | Regressione: `RiskManager.quantity()` con `risk_fraction` negativa | ⚠️ rilievo minore residuo |

---

## 1. Fix #1 — dry-run senza patch (`toTime`)

```
$ PYTHONPATH=. python3 -m pattern_go --config config.json --dry-run
2026-08-05 06:33:02,662 INFO pattern_go.dxtrade dxtrade login ok
EXIT=0
```

Journal completo, **senza nessuna patch** (l'ultima volta il processo moriva qui con
exit 1 e nel journal c'era solo `RECONCILE`):

```json
{"event": "RECONCILE", "orders": 0, "positions": 0, "position_ids": [], "order_codes": []}
{"event": "WARMUP", "strategy": "M5",  "bars": 399}
{"event": "WARMUP", "strategy": "M15", "bars": 399}
{"event": "STARTUP", "symbol": "XAU", "quantity_increment": 0.01,
 "balance": 9999.92, "equity": 9999.92, "static_floor": 9700.0, "effective_floor": 9700.0,
 "reservoir": 299.9200000000001, "risk_amount": 14.996000000000004,
 "strategies": ["M15", "M5"]}
```

`static_floor` = 9700.0 corretto. `reservoir` 299.92 / `risk_amount` 14.996 invece di
300/15 solo perché il saldo demo è 9999.92 dopo i test precedenti (−0.08 USD di costi):
la formula è corretta e i valori esatti sono coperti dagli unit test.

## 2. Fix #2 — stop order col codice del repo (ordine 1 di 2)

Nessun payload artigianale: `DXTradeClient.place_stop_order()` così com'è nel repo.

```
bid/ask: 4149.06 / 4149.17 (spread 11 punti) -> stop BUY lontano: 4199.17
place_stop_order(qty=0.01) -> ACCETTATO {"orderId": 2536084, "updateOrderId": 2536084}
orders(): [('PG-FAR-1785911601', 'STOP', 'WORKING', 4199.17, 0.01)]
positions(): []
cancel_order() -> {'orderId': 2536084, 'updateOrderId': 2536087}
orders() dopo cancel: []   positions() dopo cancel: []
```

L'ordine è accettato, resta `WORKING` al prezzo e alla quantità richiesti, e la
cancellazione lo rimuove. Nessun ordine di protezione collegato inviato, come previsto.

## 3. Fix #3 + #5 + uscite protettive — ciclo completo (ordine 2 di 2)

Tutto attraverso il `Runner` reale (`startup()`, `_execute()`, `_detect_fill()`,
`_check_protective_exits()`): nessuna chiamata al client fatta a mano.

```
bid/ask: 4150.42 / 4151.23 (spread 81 punti) -> trigger BUY stop: 4151.28
ordine inviato, broker id: 2536100
FILL entry: 4151.34  teorico: 4151.28  slippage_pt: 6.0  position_id: 2536100
quote attuale bid/ask: 4151.24 / 4151.40 (spread 16 punti)
stop_loss forzato a 4152.24 > bid 4151.24 -> _check_protective_exits deve chiudere
engine.trade dopo il check: None

FINALE positions: []
FINALE orders: []
FINALE metrics: AccountMetrics(equity=9999.87, balance=9999.87, open_pl=0.0,
                               open_positions=0, open_orders=0)
```

`position_id: 2536100` è **salvato in `OpenTrade`** (fix #5 confermato: l'ultima volta era
`None`). Journal:

```json
{"event":"ORDER_PLACED","broker_order_id":"2536100","theoretical_entry_price":4151.28,
 "quantity":0.01,"stop_loss":4146.28,"take_profit":4156.28,"spread_at_signal":0.8099999999994907}
{"event":"TRADE_OPENED","entry_price":4151.34,"theoretical_entry_price":4151.28,
 "slippage":0.06000000000040018,"position_id":"2536100","quantity":0.01,"risk_currency":0.05}
{"event":"TRADE_CLOSED","exit_price":4151.24,"exit_reason":"STOP_LOSS",
 "pnl":-0.001000000000003638,"r_realized":-0.020000000000072758,"quantity":0.01}
```

- la chiusura **va a buon fine** e la posizione **sparisce davvero** da `positions()`
  (l'ultima volta restava aperta con `CLOSE_FAILED`);
- `grep -c CLOSE_FAILED logs/journal_*.jsonl` → **0**;
- `exit_reason` è **`STOP_LOSS`**, generato da `_check_protective_exits` con lo SL portato
  a un livello già superato dal bid corrente: la sorveglianza SL/TP lato runner funziona su
  un trade reale e chiude a mercato.

## 4. Fix #4 — validazione della configurazione

```
=== no_broker    ConfigError: sezione 'broker' mancante o non valida nella configurazione
=== no_risk      ConfigError: sezione 'risk' mancante o non valida nella configurazione
=== neg_fraction ConfigError: configurazione non valida:
                 - risk.risk_fraction deve stare in (0, 1], trovato -0.05
=== floor_above  ConfigError: configurazione non valida:
                 - account.cap_size (11000.0) non puo' essere sotto initial_balance (20000.0):
                   il serbatoio sarebbe nullo
=== bad_symbol   DXTradeError: strumento XAUUSD_FAKE non trovato
```

Tutti exit 1 con messaggio esplicito, e — differenza sostanziale rispetto al giro 1 — le
config assurde vengono **fermate al caricamento**, prima di qualsiasi contatto col broker.

## 5. Nessun segreto nei log

`grep -Rqi` di username, password e `sessionToken` su `logs/`, `state/` e sui campioni di
spread → **exit 1, zero occorrenze**.

---

## Misure

### Slippage sui fill reali

| Fill | Spread al segnale | Teorico | Eseguito | Slippage |
|---|---|---|---|---|
| Giro 2 (questo test) | 81 punti | 4151.28 | 4151.34 | **6 punti** |
| Giro 1, fill A | 14 punti | 4145.95 | 4146.57 | **62 punti** |
| Giro 1, fill B | 1 punto | 4150.00 | 4150.00 | **0 punti** |

I 62 punti del giro 1 **sembrano un caso isolato**: su 3 fill totali la mediana è 6 punti,
ben sotto la soglia di disattivazione di M5 (30 punti medi). Con 3 soli campioni però la
media resta dominata dall'outlier (22,7 punti) e non è statisticamente utile: serve il
forward test.

### Spread XAU

84 campioni complessivi (10 s di intervallo, ~06:12–06:45 UTC del 2026-08-05):

```
n 84  media 12.5  mediana 5.0  min 1.0  max 123.0 punti
quota campioni > 30 punti: 6.0 %
```

Ultimo campionamento isolato (30 campioni): medio 12.4, mediano 5.5, min/max 1.0/123.0.
Con lo spread mediano i filtri passano largamente:

```
M5:  con spread mediano servono SL >= 27 punti (backtest 367) -> PASSA
M15: con spread mediano servono SL >= 47 punti (backtest 713) -> PASSA
```

Il 6% di campioni sopra i 30 punti e i picchi a 123 punti confermano che il campione su
12–24 h resta necessario prima di dichiarare la strategia tradabile.

---

## Rilievi residui (non bloccanti)

**`RiskManager.quantity()` non è difensivo se costruito a mano.** Con un `RiskConfig`
creato direttamente in codice (bypassando `load_config`):

```
RiskConfig(initial_balance=10000, cap_size=11000, risk_fraction=-0.05)
 risk_amount: -15.0   quantity(3.67): (0.01, 'rounded_up_to_min')
```

`round_below_min_to_min` continua a trasformare un rischio negativo in una quantità di
0.01. Ora è **irraggiungibile dal percorso di configurazione** (la validazione blocca
prima), quindi non è bloccante; resta una difesa in profondità mancante: un `quantity()`
che restituisce `(0.0, 'risk_non_positive')` quando `risk_amount <= 0` chiuderebbe il caso.

**Nota operativa sulle uscite**: SL/TP ora sono sorvegliati a ogni `tick()` con
`poll_seconds: 10.0` e uscita a mercato. Lo slippage in uscita sarà quindi
strutturalmente più alto di quello del backtest (che assume l'esecuzione al livello
esatto), e su M5 un movimento veloce può superare il livello fra due poll. È un limite
noto e documentato nel codice, ma va tenuto d'occhio nel confronto con il backtest.

## Note

- 2 ordini di ingresso in tutto (1 pendente cancellato, 1 eseguito e chiuso), sempre
  0.01 once. Costo di questo giro: **−0.05 USD** (saldo da 9999.92 a 9999.87).
- Nessuna posizione o ordine preesistente toccato: il conto era vuoto all'inizio.
- Nessuna modifica al codice sotto test.
