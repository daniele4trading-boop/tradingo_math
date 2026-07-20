# TG TradinGo EA — specifica bridge → MT5

Documento di riferimento per `TG_TradinGoEA.mq5`. Il bridge Python **non** parla con MT5: scrive solo file JSON. L'EA è l'unico componente che esegue ordini.

## Architettura multi-VPS (tu + amici)

```
[La tua VPS]  tradingo_bridge.py  →  signal_ch_*.json
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
            C:\TG_TradinGo\signals    Amico A MQL5\Files    Amico B (share SMB)
                    │                         │                         │
                    ▼                         ▼                         ▼
              TG_TradinGoEA              TG_TradinGoEA              TG_TradinGoEA
              (tuo MT5 demo)             (suo MT5)                  (suo MT5)
```

**Due modi per gli amici:**

1. **Bridge centrale (consigliato):** nel tuo `tradingo_config.json` aggiungi il path `signals_path` della cartella `MQL5\Files` di ogni amico (share di rete o sync). Il bridge scrive gli stessi JSON ovunque.
2. **Solo EA:** l'amico copia/sincronizza i file `signal_ch_*.json` nella propria cartella segnali e avvia l'EA con lo stesso `SignalsBasePath`.

L'EA non richiede Telegram né Python: legge solo i JSON.

---

## File segnale (uno per canale)

| File | Canale | magic_base |
|------|--------|------------|
| `signal_ch_gold.json` | Sala GOLD VIP | 12000 |
| `signal_ch_forex.json` | Sala FOREX VIP | 13000 |
| `signal_ch_oro.json` | Sala ORO VIP | 14100 |
| `signal_ch_stark.json` | Sala Stark | 14000 |
| `signal_ch_ivan.json` | IvanTrades VIP | 17000 |

Stato iniziale / idle: `{"action": "NONE"}`.

Il bridge sovrascrive l'intero file ad ogni evento (scrittura atomica tmp + replace). L'EA deve deduplicare con `timestamp` (o `message_id` + `event_type`).

---

## Campi JSON comuni

| Campo | Tipo | Note |
|-------|------|------|
| `action` | string | Vedi tabella azioni |
| `direction` | `"BUY"` \| `"SELL"` | Obbligatorio per OPEN* |
| `symbol` | string | Es. `XAUUSD`, `EURUSD` |
| `entry` | number \| null | Prezzo singolo; **null** se c'è `entry_range` |
| `entry_range` | `[lo, hi]` \| null | EA valuta prezzo nel range (non usa media) |
| `sl` | number \| null | Stop loss |
| `tp_levels` | number[] | Un TP per trade split |
| `trades` | int | Numero posizioni da aprire |
| `fixed_lot` | number | Lotto per trade (se `use_fixed_lot`) |
| `use_fixed_lot` | bool | Sempre `true` con bridge attuale |
| `splits` | number[] | Legacy; bridge usa `fixed_lot` |
| `magic_base` | int | Magic trade i = `magic_base + i` |
| `channel_id` | string | Es. `CH_GOLD` |
| `timestamp` | string ISO UTC | Dedup EA |
| `message_id` | int | Opzionale, da Telegram |
| `event_type` | `"NEW"` \| `"EDIT"` | Opzionale |
| `is_add_signal` | bool | STARK: lotto dimezzato |
| `inherit_from_first` | bool | STARK: copia SL/TP dal primo trade |
| `new_tp` / `new_sl` | number | UPDATE_TP / UPDATE_SL |
| `is_be` | bool | UPDATE_SL verso break-even |
| `be_price` | number | BREAK_EVEN_PRICE |
| `tp_index` | int | CHECK_AND_CLOSE_TP |

### Regole lotti (bridge `apply_lot_rules`)

| TP nel segnale | `trades` | `fixed_lot` |
|----------------|----------|-------------|
| 0 (OPEN_NOW) | 1 | 0.20 |
| 1 TP | 1 | 0.20 |
| 2+ TP | N | 0.10 ciascuno |

`OPEN_NOW` (GOLD naked): mercato subito, senza SL/TP. Il messaggio successivo è `UPDATE_OPEN` con livelli.

---

## Azioni EA

| action | Comportamento EA |
|--------|------------------|
| `NONE` | Ignora |
| `OPEN` | Apri `trades` posizioni (magic_base+1..N), SL/TP da JSON |
| `OPEN_NOW` | 1 ordine a mercato, senza SL/TP |
| `UPDATE_OPEN` | Modifica SL/TP su posizioni aperte; se servono più trade, apri/chiudi per allineare a `trades` |
| `UPDATE_TP` | Modifica TP posizioni del canale/simbolo |
| `UPDATE_SL` | Modifica SL (FOREX) |
| `CHECK_AND_CLOSE` | Chiudi se esiste posizione symbol+direction |
| `CLOSE_ALL_SYMBOL` | Chiudi tutte le posizioni del simbolo (magic del canale) |
| `BREAK_EVEN_PRICE` | Sposta SL a `be_price` |
| `CLOSE_HALF_BE` | Chiudi metà volume + BE sul resto (ORO: `60 PIPS CLOSE OR BREKIVEN`) |
| `CHECK_AND_BE` | Se TP1 non chiuso, sposta SL a entry |
| `CHECK_AND_CLOSE_TP` | Chiudi trade con `tp_index` se ancora aperto |

### Entry range

Se `entry_range` è `[lo, hi]` il parser **non** calcola la media in `entry` (resta `null`).

L'EA valuta **subito** al ricevimento del segnale:

| Condizione | Azione |
|------------|--------|
| Prezzo ∈ [lo, hi] | Esegue a mercato (`ENTRY_IN_RANGE`) |
| Prezzo fuori range ma distanza ≤ `InpRangeTolerancePoints` (default **150** ≈ 15 pip su XAUUSD) | Esegue comunque (`ENTRY_TOLERANCE`) |
| Prezzo troppo lontano | **Non esegue** — log `SIGNAL_CANCELLED` + riga in `MQL5\Files\tradingo_signal_stats.csv` |

`InpRangeTolerancePoints` è in **punti MT5** del simbolo (`_Point`). Per XAUUSD 2 decimali: 100 punti ≈ 1.0$, 200 punti ≈ 2.0$.

Non c'è più attesa passiva del prezzo nel range.

### STARK `is_add_signal` / `inherit_from_first`

- `is_add_signal=true` → lotto × 0.5 (`InpAddLotFactor`, default 0.5)
- `inherit_from_first=true` → copia SL e `tp_levels` dalla prima posizione aperta dello stesso canale/simbolo

### Break-even automatico

Se `InpAutoBreakEvenOnTp1=true`, quando una posizione con magic `magic_base+1` chiude in profitto (TP1), sposta SL delle altre posizioni dello stesso segnale a prezzo di apertura.

---

## Parametri EA consigliati

| Parametro | Default | Uso |
|-----------|---------|-----|
| `InpSignalsPath` | `C:\TG_TradinGo\signals\` | Cartella JSON |
| `InpUseAbsolutePath` | true | false = sotto `MQL5\Files\` |
| `InpSymbolSuffix` | `""` | Suffisso broker (`m`, `.pro`) |
| `InpLotMultiplier` | 1.0 | Scala lotti per amici |
| `InpMaxSlippagePoints` | 50 | Slippage |
| `InpPollMs` | 500 | Intervallo lettura file |
| `InpRangeTolerancePoints` | 150 | Max distanza (punti) dal range per entrare comunque |
| `InpLogCancelledSignals` | true | Scrive `tradingo_signal_stats.csv` |
| `InpChannels` | `gold,forex,oro,stark` | File da monitorare |

---

## Recupero EA vecchio sulla VPS

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\find_tradingo_ea.ps1
```

Confronta l'output con `tg_tradingo/mql5/TG_TradinGoEA.mq5` in repo. **Non** distribuire l'EA vecchio se non documentato: usare la versione in repo.

---

## Prompt per Claude (se vuoi rigenerare)

Usa questo blocco come system/task prompt; allega `EA_SPEC.md` e i fixture in `docs/fixtures/signal_ch*.example.json`.

```
Scrivi TG_TradinGoEA.mq5 per MetaTrader 5 che:
1. Legge periodicamente signal_ch_{gold,forex,oro,stark}.json da InpSignalsPath
2. Deduplica con campo timestamp
3. Implementa tutte le action in EA_SPEC.md
4. Usa magic_base+i per trade split, fixed_lot × InpLotMultiplier
5. OPEN_NOW = mercato; UPDATE_OPEN aggiorna SL/TP e splitta se trades>1
6. entry_range = attendi prezzo nel range prima di OPEN
7. Un solo file .mq5, include Trade.mqh, niente DLL esterne
8. Log su Experts con prefisso [TradinGo]
```

La versione in `tg_tradingo/mql5/TG_TradinGoEA.mq5` è già allineata a questa specifica.
