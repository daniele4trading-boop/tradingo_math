# Integrazione DXtrade (dxSCA REST API)

**Risposta breve: sì, è possibile.** DXtrade espone una REST API di trading
(`/dxsca-web`) con le stesse credenziali della piattaforma, senza chiavi
separate. Il bridge Python può quindi diventare un terzo target accanto ai
file JSON per MT5 e MT4.

Il lavoro non è nel "chiamare l'API": è nel fatto che **su MT4/MT5 la logica
di esecuzione sta nell'EA**, mentre su DXtrade non esiste un EA. Tutto quello
che oggi fa `TG_TradinGoEA` (valutazione range, N ticket per TP, fill degli
slot mancanti, break-even, chiusure parziali, kill-switch, journal) va
riscritto in Python lato bridge.

---

## 1. Superficie API rilevante

Base URL: `https://<host-broker>/dxsca-web`.
Documentazione per broker: `https://<host-broker>/developers/`
(specifica "DXtrade REST API"), schema live su `https://<host-broker>/dxsca-web/specs`.

| Cosa | Chiamata |
|------|----------|
| Login | `POST /login` `{username, domain, password}` → `{sessionToken, timeout}` |
| Header auth | `Authorization: DXAPI <sessionToken>` (alternativa: HMAC con coppia di token) |
| Keep-alive | `POST /ping` (il token scade per inattività; su `401` si rifà login) |
| Logout | `POST /logout` |
| Strumenti | `GET /instruments/{symbol}`, `GET /instruments/query?symbols=` |
| Quote / candele | `POST /marketdata` |
| Posizioni | `GET /accounts/{account}/positions` |
| Portafoglio / metriche | `GET /accounts/{account}/portfolio`, `.../metrics` |
| Ordini aperti / storico | `GET /accounts/{account}/orders`, `.../orders/history` |
| **Invio ordine** | `POST /accounts/{account}/orders` (singolo o gruppo) |
| Modifica ordine | `PUT /accounts/{account}/orders` (solo richieste condizionali, `If-Match`) |
| Cancellazione | `DELETE /accounts/{account}/orders/{orderCode}` |
| Chiusura di massa | `POST /accounts/{account}/close` |

**Rate limit** (default di piattaforma, configurabili dal broker): login 1/s per
IP, letture 10/s per sessione, trading 10/s, richieste "grosse" 1/s. Con ~40
segnali al giorno non siamo neanche vicini al limite; oltre soglia arriva
`429 Too Many Requests`.

**Push API**: gli aggiornamenti in tempo reale (fill, TP colpito) sono su un
canale WebSocket separato, documentato a parte. La REST è sincrona
request-response.

---

## 2. Le tre differenze che contano rispetto a MT4/MT5

### 2.1 Quantità in unità, non in lotti

`quantity` è in unità dello strumento. La conversione richiede `lotSize` da
`GET /instruments/{symbol}`, con arrotondamento a `quantityIncrement`:

```
unità = lotti × lotSize          (arrotondate a quantityIncrement)
```

Esempio con `XAU/USD` (`lotSize=100`, `quantityIncrement=1`): 0.10 lotti = 10
unità. Con `EUR/USD` (`lotSize=100000`, `quantityIncrement=1000`): 0.01 lotti =
1000 unità.

### 2.2 SL e TP non sono campi dell'ordine

Sono **ordini di protezione** separati. Due modi:

* **In apertura**: gruppo `IF-THEN` in un solo `POST` — ordine `MARKET` di
  apertura + `STOP` (SL) + `LIMIT` (TP), questi ultimi con `quantity: 0` e
  `positionEffect: CLOSE`.
* **Su posizione già aperta** (il nostro `UPDATE_OPEN` dopo un `OPEN_NOW`):
  `POST` con `positionCode` della posizione. Le due protezioni richiedono
  **due POST distinti**: l'API non accetta SL e TP in una sola richiesta su una
  posizione esistente.

Un ordine `MARKET` già eseguito è in stato finale e **non** si modifica con
`PUT`: per cambiare SL/TP si agisce sugli ordini di protezione.

### 2.3 Non esiste il magic number

Su MT5 l'identità del ticket è `magic_base + i`. Su DXtrade abbiamo due
sostituti, entrambi migliori:

* **`orderCode`**: client id univoco per account, obbligatorio. Lo generiamo
  deterministico: `TG-GOLD-32cf923e6b-T1O`. Un secondo POST con lo stesso
  codice viene rifiutato con `409 / errorCode 100`, quindi **la deduplica è
  garantita dalla piattaforma**: un retry di rete non può aprire un doppione.
  Oggi su MT5 questa protezione è affidata al dedup per `timestamp` nell'EA.
* **`metadata`**: fino a 32 coppie chiave-valore restituite insieme all'ordine.
  Ci mettiamo `tg_channel`, `tg_signal`, `tg_tp`, `tg_bridge`.

⚠️ **Le posizioni non portano metadata**: il modello `Position` ha solo
`positionCode`, `symbol`, `quantity`, `side`, `openPrice`, `takeProfitPrice`,
`stopLossPrice`. Quindi il legame posizione ↔ canale/TP va tenuto in uno
**stato locale** (`positionCode` restituito come `orderId` all'apertura), con
recupero da `GET /orders/history` leggendo i metadata dopo un restart.

---

## 3. Mappa azioni bridge → DXtrade

| action | Su DXtrade | Note |
|--------|-----------|------|
| `OPEN` | N gruppi `IF-THEN` (MARKET + STOP + LIMIT), uno per TP | un `orderCode` per ticket |
| `OPEN_NOW` | N ordini `MARKET` nudi | come l'EA: protezioni al messaggio dopo |
| `UPDATE_OPEN` | per slot esistente: 2 POST protezione con `positionCode`; per slot mancante: gruppo `IF-THEN` di apertura | replica `EXECUTED_UPDATE_FILL` dell'EA 2.15 |
| `UPDATE_TP` / `UPDATE_SL` | sostituzione dell'ordine di protezione (`DELETE` + `POST`, o `PUT` con `If-Match`) | |
| `BREAK_EVEN_PRICE` / `CHECK_AND_BE` | come `UPDATE_SL` al prezzo di apertura | serve `openPrice` da `GET /positions` |
| `CHECK_AND_CLOSE` / `CLOSE_ALL_SYMBOL` | un `MARKET` `positionEffect: CLOSE` per `positionCode` | **non** usare `POST /close`: filtra solo per strumento e chiuderebbe anche gli altri canali su XAUUSD |
| `CLOSE_SELECTIVE` | filtro su `openPrice` delle posizioni + chiusure mirate | la logica `BEST`/`HIGHEST`/`LOWEST` è già in `bridge_core` |
| `CLOSE_HALF_BE` | chiusura parziale: `MARKET CLOSE` con `quantity` = metà unità + nuovo SL | |
| `CHECK_AND_CLOSE_TP` | chiusura del `positionCode` mappato su `tp_index` | richiede lo stato locale |

Il range di entrata (`entry_range` + tolleranza in punti) è già portato in
Python in `evaluate_entry()`, con gli stessi stati dell'EA:
`EXECUTED_IN_RANGE`, `EXECUTED_TOLERANCE`, `EXECUTED_DIRECT`,
`CANCELLED_RANGE`. Serve una quote: `POST /marketdata` oppure il WebSocket.

---

## 4. Architettura proposta

```
tradingo_bridge.write_signal()
        │
        ├── file JSON  →  MT5 Vantage / MT5 iFunds / MT4 T4Trade   (invariato)
        │
        └── dxtrade_sink  →  coda su disco  →  dxtrade_worker (processo separato)
                                                    │
                                                    ├── dxtrade_mapper  (segnale → ordini)
                                                    ├── dxtrade_client  (REST)
                                                    └── stato: tp_index → positionCode
```

Perché un **worker separato** e non chiamate dirette da `write_signal`:

* `write_signal` gira dentro l'event loop di Telethon. Una chiamata HTTP lenta
  bloccherebbe la ricezione dei messaggi Telegram, esattamente il problema già
  visto con la share SMB di Gamehosting (per cui i target UNC sono stati messi
  in coda per ultimi).
* Il worker può fare retry, keep-alive del token e riconciliazione posizioni
  senza toccare il percorso critico.
* Se DXtrade è giù, MT4/MT5 continuano a funzionare.

Config proposta in `tradingo_config.json` (accanto a `mt5_instances`):

```json
"dxtrade_accounts": [
  {
    "name": "Broker_DXtrade_Demo",
    "enabled": false,
    "base_url": "https://dx.broker.com/dxsca-web",
    "domain": "default",
    "account": "default:12345",
    "credentials_env": "DXTRADE_DEMO",
    "lot_multiplier": 1.0,
    "dry_run": true,
    "symbol_map": { "XAUUSD": "XAU/USD", "EURUSD": "EUR/USD" },
    "channels": ["CH_GOLD", "CH_ORO", "CH_STARK", "CH_IVAN"]
  }
]
```

Le credenziali **non** stanno nel config: si leggono da environment
(`DXTRADE_DEMO_USERNAME`, `DXTRADE_DEMO_PASSWORD`), come già si fa per i
segreti di questa repo.

---

## 5. Cosa c'è già in repo

| File | Contenuto | Stato |
|------|-----------|-------|
| `dxtrade_client.py` | client REST solo stdlib: login/ping/logout, strumenti, quote, posizioni, metriche, place/modify/cancel, bulk close. Re-login trasparente su `401`, retry su `429`/`5xx`, throttle, `dry_run`, duplicato `409/100` riportato invece di sollevare | pronto |
| `dxtrade_mapper.py` | funzioni pure segnale → ordini: mappatura simboli, lotti→unità, `orderCode`/`metadata`, `evaluate_entry` (porting dell'EA), `plan_open`, `plan_update_open`, `plan_close`. CLI offline per ispezionare i payload | pronto |
| `dxtrade_probe.py` | diagnostica in sola lettura: permesso API, account code, naming simboli, `lotSize`, hedging vs netting, quote REST | pronto |
| `tests/test_dxtrade_client.py` | 18 test contro piattaforma finta locale | verde |
| `tests/test_dxtrade_mapper.py` | 36 test su payload di segnali **reali** del 3 agosto 2026 | verde |
| `tests/test_dxtrade_probe.py` | 6 test end-to-end del probe | verde |

**Non ancora scritto** (serve una decisione, vedi §6): il worker con la
macchina a stati, lo store `positionCode`, il journal DXtrade e l'aggancio a
`write_signal`. Il percorso di produzione MT4/MT5 **non è stato toccato**.

### Provare senza credenziali

```bash
cd tg_tradingo
python -m pytest tests/test_dxtrade_client.py tests/test_dxtrade_mapper.py tests/test_dxtrade_probe.py

# ordini che verrebbero inviati per un segnale reale, senza rete
python dxtrade_mapper.py docs/fixtures/signal_ch_ivan_open_4tp.example.json
python dxtrade_mapper.py docs/fixtures/signal_ch_gold_update_open_215.example.json \
    --position-codes 1:63649
```

### Provare con credenziali (sola lettura)

```bash
export DXTRADE_BASE_URL="https://dx.broker.com/dxsca-web"
export DXTRADE_USERNAME="..." DXTRADE_PASSWORD="..."
export DXTRADE_ACCOUNT="default:12345"
python dxtrade_probe.py --symbols XAUUSD,EURUSD
```

---

## 6. Punti aperti da decidere prima del worker

1. **Quale broker/host.** `base_url`, `domain` e `account code` sono specifici:
   servono host reale e credenziali (demo va benissimo per partire).
2. **Permesso REST API abilitato?** Se l'utente non ce l'ha, ogni chiamata
   risponde `404 / errorCode 2`. Il probe lo rileva subito.
3. **Hedging o netting.** È la domanda più importante: il nostro modello apre
   N posizioni sullo stesso simbolo e lato (una per TP). Su un account
   **netting** collasserebbero in una posizione netta e lo schema multi-TP non
   funziona; servirebbe una sola posizione con chiusure parziali ai livelli.
   Il probe dà un indizio, ma la conferma richiede due ordini di prova sullo
   stesso lato in demo.
4. **Naming simboli.** `XAU/USD` è lo standard DXtrade, ma alcuni broker usano
   varianti. Il probe prova i candidati e segnala quando serve una mappatura
   esplicita.
5. **Quote per `entry_range`.** Se `POST /marketdata` non è abilitato, la
   valutazione del range richiede il WebSocket della Push API.
6. **Regole del conto.** Se è un conto funded/prop: verificare che l'automazione
   sia permessa e replicare i limiti (daily loss, max holding) come già fa il
   kill-switch dell'EA.

---

## 7. Rischi

* **Nessun EA = nessuna rete di sicurezza locale.** Su MT5 se il bridge muore
  l'EA continua a gestire SL/TP già piazzati. Su DXtrade le protezioni sono
  ordini reali sulla piattaforma, quindi restano, ma tutto ciò che è reattivo
  (break-even, chiusure selettive, kill-switch) muore col worker. Vanno
  monitorati con l'heartbeat, come già fa l'EA con `InpHeartbeatMaxAgeSec`.
* **Stato locale come punto singolo.** Perdere la mappa `tp_index → positionCode`
  significa non saper più quale posizione chiudere. Mitigazione: ricostruirla da
  `GET /orders/history` usando i `metadata`.
* **Doppia esecuzione.** Con MT5 e DXtrade sullo stesso segnale l'esposizione
  raddoppia: il `lot_multiplier` per account e il `dry_run` iniziale servono
  proprio a questo.
