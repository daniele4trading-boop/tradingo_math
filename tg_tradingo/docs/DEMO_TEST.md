# Checklist test demo TG TradinGo

## Regole lotti (tutte le sale attive)

| TP nel segnale | Trade | Lotto per trade | Totale esposizione |
|----------------|-------|-----------------|-------------------|
| 1 TP | 1 | **0.20** | 0.20 |
| 2 TP | 2 | **0.10** ciascuno | 0.20 |
| 3 TP | 3 | **0.10** ciascuno | 0.30 |

Eccezione **OPEN_NOW** (GOLD naked): 1 trade × 0.20 a mercato, SL/TP arrivano con UPDATE_OPEN.

## TP per sala (da dump 13-17 lug)

| Sala | TP tipici | Trade demo |
|------|-----------|------------|
| Sala GOLD VIP | **2** (raro 3) | 2 × 0.10 |
| Sala FOREX VIP | **1** | 1 × 0.20 |
| Sala ORO VIP | **1 o 2** | 0.20 o 2 × 0.10 |
| Sala Stark | **1** | 1 × 0.20 |
| IvanTrades VIP | TBD | TBD |

## 1. Aggiorna repo e deploy

```powershell
cd C:\StatArb
git pull origin cursor/tg-tradingo-hardening-8e22
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
```

## 2. IvanTrades - VIP (ID confermato)

`telegram_id: -1002112242007`

In `tradingo_config.json` → canale `CH_IVAN`:

```json
"telegram_id": -1002112242007,
"enabled": false
```

Lasciare `enabled: false` finché non arriva il primo segnale operativo e non costruiamo il parser.
Per campionare messaggi Ivan senza abilitare il bridge:

```powershell
python fetch_date_range.py --from 2026-07-20 --to 2026-07-20 --channel CH_IVAN
```

(serve `CH_IVAN` nel config con telegram_id corretto)

## 3. Aggiorna config produzione

Partire da `tradingo_config.example.json` (nuova struttura CH_GOLD / CH_FOREX / …) e **unire** solo `telegram` api_id/api_hash e path esistenti dal config attuale.

File JSON segnale EA (uno per canale):

- `signal_ch_gold.json`
- `signal_ch_forex.json`
- `signal_ch_oro.json`
- `signal_ch_stark.json`
- `signal_ch_ivan.json`

## 4. MT5 demo

1. Conto **demo** con almeno 5 000 €
2. EA `TG_TradinGoEA.mq5` su chart qualsiasi
3. `SignalsBasePath` = `C:\TG_TradinGo\signals\`
4. Verificare che l'EA legga `use_fixed_lot`, `fixed_lot`, `trades`

## 5. Avvio bridge (solo dopo conferma)

```bat
C:\TG_TradinGo\start_tradingo.bat
```

## 6. Verifica manuale

Per ogni canale, quando arriva un segnale:

1. Controlla log `C:\TG_TradinGo\logs\tradingo_YYYYMMDD.log`
2. Controlla JSON in `signals\signal_ch_*.json`
3. Su MT5 demo: posizioni con lotto corretto e magic atteso

| Sala | Magic attesi |
|------|--------------|
| GOLD | 12001, 12002 (2 TP) |
| FOREX | 13001 |
| ORO | 14101, 14102 (se 2 TP) |
| STARK | 14001 |
| IVAN | 17001 |

## 7. Test parser offline

```powershell
cd C:\StatArb\tg_tradingo
pip install -r requirements.txt
python -m pytest tests/ -v
```

## 8. Rollback

```powershell
Copy-Item "C:\TG_TradinGo\_backups\backup_*\*" "C:\TG_TradinGo" -Recurse -Force
```
