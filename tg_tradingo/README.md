# TG TradinGo — Guida Setup & Operativa

## Struttura cartelle

```
C:\TG_TradinGo\
  tradingo_bridge.py      ← Bridge Python (Telegram → JSON)
  tradingo_config.json    ← Configurazione centralizzata
  start_tradingo.bat      ← Avvio bridge
  mql5/TG_TradinGoEA.mq5  ← EA MQL5 (JSON → MT5 trades)
  logs\
    tradingo_YYYYMMDD.log
  signals\
    signal_ch1.json       ← CH1 Zanni VIP
    signal_ch2.json       ← CH2 Sala Gold VIP
    signal_ch3.json       ← CH3 placeholder
    signal_ch4.json       ← CH4 placeholder
```

---

## 1. Installazione Python

```bat
pip install telethon
```

La sessione Telegram riusa il file esistente:
`C:\TelegramBridge\telegram_bridge_session.session`

---

## 2. Configurazione canali (tradingo_config.json)

### Aggiungere un canale
1. Aprire `tradingo_config.json`
2. Aggiungere un oggetto nell'array `"channels"` con:
   - `"id"`: identificativo (es. "CH3")
   - `"telegram_id"`: ID numerico del canale Telegram
   - `"parser"`: nome del parser da usare
   - `"enabled"`: true/false
3. Nessuna modifica al codice Python richiesta

### Parsers disponibili
| Parser            | Canale        | Stato     |
|-------------------|---------------|-----------|
| `zanni_vip`       | CH1           | ✅ Attivo |
| `sala_gold`       | CH2           | ✅ Attivo |
| `generic_placeholder` | CH3/CH4  | ⏳ Da mappar|

---

## 3. Avvio sistema

1. Avviare MT5 con `TG_TradinGoEA.mq5` su qualsiasi chart
2. Configurare `SignalsBasePath` nell'EA = `C:\TG_TradinGo\signals\`
3. Eseguire `start_tradingo.bat` sulla VPS

---

## 4. Multi-broker (copy su altri MT5)

Nel file `tradingo_config.json`, aggiungere istanze MT5 nell'array `mt5_instances`:

```json
"mt5_instances": [
  {
    "name": "TradinGo_Local",
    "enabled": true,
    "signals_path": "C:\\TG_TradinGo\\signals"
  },
  {
    "name": "Friend_VPS_Broker2",
    "enabled": true,
    "signals_path": "\\\\192.168.1.100\\signals"
  }
]
```

Il bridge scriverà i segnali in **tutti i percorsi abilitati** simultaneamente.
Su ogni VPS remote serve l'EA configurato con il percorso locale corrispondente.

---

## 5. Magic Numbers schema

| Canale | Trade 1 | Trade 2 | Trade 3 |
|--------|---------|---------|---------|
| CH1    | 11001   | 11002   | 11003   |
| CH2    | 12001   | 12002   | —       |
| CH3    | 13001   | —       | —       |
| CH4    | 14001   | —       | —       |

---

## 6. Formato segnali JSON (signal_ch1.json esempio)

```json
{
  "action": "OPEN",
  "direction": "SELL",
  "symbol": "XAUUSD",
  "entry": 5026.0,
  "tp_levels": [5022.0, 5020.0, 5016.0],
  "sl": 5036.0,
  "trades": 3,
  "risk_percent": 1.0,
  "use_fixed_lot": false,
  "be_enabled": true,
  "be_trigger": "TP1",
  "be_level": "entry",
  "magic_base": 11000,
  "channel_id": "CH1",
  "channel_name": "Zanni VIP Signals",
  "timestamp": "2026-04-13T10:00:00Z",
  "raw_message": "SELL XAUUSD 5026 TP1: 5022 TP2: 5020 TP3: 5016 SL: 5036"
}
```

### Azioni supportate
- `OPEN` — apre nuovi trade
- `CLOSE_ALL` — chiude tutte le posizioni del canale (CH1: "chiudo manuale")
- `BREAK_EVEN` — sposta SL a livello entry (CH2: "tp1 hit + break even")
- `NONE` — nessuna azione (stato iniziale file)

---

## 7. Aggiungere parser per CH3/CH4

Quando arrivano esempi di segnali reali:

1. Aggiungere funzione `parser_ch3(text, channel_cfg)` in `tradingo_bridge.py`
2. Registrarla nel dizionario `PARSERS`:
   ```python
   PARSERS = {
       "zanni_vip": parser_zanni_vip,
       "sala_gold": parser_sala_gold,
       "ch3_parser": parser_ch3,   ← aggiunto
   }
   ```
3. Nel `tradingo_config.json`, impostare `"parser": "ch3_parser"` e `"enabled": true`

---

## 8. Log

I log giornalieri si trovano in `C:\TG_TradinGo\logs\tradingo_YYYYMMDD.log`

Livelli:
- `INFO` — segnali ricevuti/scritti
- `DEBUG` — messaggi ignorati (solo con VerboseLog=true)
- `ERROR` — errori parsing/scrittura file
