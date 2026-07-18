# Mappa canali TG TradinGo — luglio 2026

Canali operativi richiesti dall'utente e regole di esecuzione proposte.

## Tabella canali

| ID config | Nome Telegram | telegram_id | Parser | Stato |
|-----------|---------------|-------------|--------|-------|
| CH_GOLD | Sala GOLD VIP | -1003302540529 | `sala_gold` | Attivo, parser OK |
| CH_FOREX | Sala FOREX VIP | -1002890661441 | `sala_vip` | **Da verificare ID** (era "Sala VIP") |
| CH_ORO | Sala ORO VIP | -1003950995427 | `placeholder` | Parser da costruire |
| CH_STARK | Sala Stark | -1002073368935 | `sala_stark` | Attivo, parser OK |
| CH_MOMO | In momo Veritas VIP | -1003448619258 | `placeholder` | Parser da costruire |
| CH_IVAN | Ivan Trades | -1002489153466 | `placeholder` | Disabilitato (no accesso VIP) |

> Eseguire `python resolve_channels.py` sulla VPS per confermare i nomi esatti e gli ID,
> soprattutto **Sala FOREX VIP** (potrebbe differire da "Sala VIP" -1002890661441).

---

## Regole esecuzione per canale

### 1. Sala GOLD VIP (`CH_GOLD`)

| Parametro | Valore |
|-----------|--------|
| Simbolo | XAUUSD |
| Modalità lotto | `risk_percent` 0.5% |
| Trade | 2 (split 60% / 40%) |
| Magic | 12001, 12002 |
| TP | TP1 + TP2 nel messaggio |
| BE | Auto su TP1 → SL a entry |
| Flusso | `OPEN_NOW` naked → `UPDATE_OPEN` con SL/TP |

**Parser:** `sala_gold` — già implementato.

---

### 2. Sala FOREX VIP (`CH_FOREX`)

| Parametro | Valore |
|-----------|--------|
| Simboli | Forex (EURUSD, GBPUSD, NZDJPY, …) |
| Modalità lotto | **Fisso** 0.20 forex / 0.05 XAUUSD |
| Trade | 1 |
| Magic | 13001 |
| TP/SL | Spesso assenti all'apertura, arrivano con `Modified` |
| BE | Manuale via messaggio SL a pareggio |

**Parser:** `sala_vip` — da estendere per formato **inglese** (`Sell - Modified`, `Moved TP`).

---

### 3. Sala ORO VIP (`CH_ORO`)

| Parametro | Valore proposto |
|-----------|-----------------|
| Simbolo | XAUUSD (oro) |
| Modalità lotto | `risk_percent` 0.5% |
| Trade | 2 (60/40) |
| Magic | 14101, 14102 |
| TP/BE | Da definire dopo analisi dump 13-17 lug |

**Parser:** da costruire (`sala_oro`) — analizzare messaggi reali.

---

### 4. Sala Stark (`CH_STARK`)

| Parametro | Valore |
|-----------|--------|
| Simboli | XAUUSD, forex |
| Modalità lotto | `risk_percent` 0.5% |
| Trade | fino a 3 (split 50/40/10) |
| Magic | 14001, 14002, 14003 |
| TP | Spesso solo TP1 nel messaggio |
| BE | Auto su TP1 |
| Add | `is_add_signal` → lotto × 0.5 |

**Parser:** `sala_stark` — già implementato.

---

### 5. In momo Veritas VIP (`CH_MOMO`)

| Parametro | Valore proposto |
|-----------|-----------------|
| Simboli | FX, indici, oro (da dump) |
| Modalità lotto | `risk_percent` 0.5% (da confermare) |
| Trade | 1 iniziale, espandibile |
| Magic | 16001+ |
| Note | Mix **analisi** + **segnali operativi** — serve filtro rumore |

**Parser:** da costruire (`momo_veritas`).

---

### 6. Ivan Trades (`CH_IVAN`) — predisposizione

| Parametro | Valore |
|-----------|--------|
| enabled | `false` |
| telegram_id | -1002489153466 (canale pubblico trovato; VIP TBD) |
| Parser | `placeholder` fino ad accesso |

Abilitare quando disponibile il canale VIP con segnali strutturati.

---

## Scarico messaggi 13-17 luglio 2026

Sulla VPS:

```powershell
cd C:\StatArb
git pull origin cursor/tg-tradingo-hardening-8e22

copy C:\StatArb\tg_tradingo\fetch_date_range.py C:\TG_TradinGo\
copy C:\StatArb\tg_tradingo\resolve_channels.py C:\TG_TradinGo\
copy C:\StatArb\tg_tradingo\bridge_core.py C:\TG_TradinGo\

cd C:\TG_TradinGo
python resolve_channels.py

python fetch_date_range.py --from 2026-07-13 --to 2026-07-17 --parser-dry-run
```

Output: `C:\TG_TradinGo\logs\signals_20260713_20260717.txt`

Push per analisi cloud:

```powershell
cd C:\StatArb
copy C:\TG_TradinGo\logs\signals_20260713_20260717.txt tg_tradingo\docs\fixtures\
git add tg_tradingo/docs/fixtures/signals_20260713_20260717.txt
git commit -m "Add channel signal dump Jul 13-17 2026"
git push origin cursor/tg-tradingo-channel-audit
```

---

## Migrazione da vecchi CH1-CH4

| Vecchio | Nuovo | Azione |
|---------|-------|--------|
| CH1 Zanni | — | Rimosso |
| CH2 Gold | CH_GOLD | Rinomina signal file, magic invariato |
| CH3 Sala VIP | CH_FOREX | Verificare se è Sala FOREX VIP |
| CH4 Stark | CH_STARK | Rinomina signal file |
| — | CH_ORO, CH_MOMO, CH_IVAN | Nuovi |

Aggiornare `tradingo_config.json` produzione e path EA `signal_ch*.json` di conseguenza.
