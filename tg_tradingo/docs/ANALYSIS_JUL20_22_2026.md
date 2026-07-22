# Analisi quantitativa TG TradinGo — 20–22 luglio 2026

Report prodotto dall’agente cloud il **2026-07-22**.  
Fonti: log bridge/EA/MT5 dalla conversazione precedente; **nessun** `tradingo_signal_stats.csv` scaricabile (SSH VPS senza chiave in questo ambiente).

Stack nel periodo: bridge **v2.02**, EA **v2.03→v2.05**. Dopo questo PR: bridge **v2.03**, EA **v2.06**.

---

## Limitazioni dati

| Fonte | Stato |
|-------|--------|
| `tradingo_signal_stats.csv` | Non disponibile (path VPS `MQL5\Files\`) |
| Log bridge `C:\TG_TradinGo\logs\tradingo_YYYYMMDD.log` | Non scaricabili via SSH (Permission denied publickey) |
| History MT5 con comment `TG-*` | Non esportata |
| Analisi usata | Log incollati + sintesi agente precedente |

Per chiudere win-rate / PnL $ / slippage per canale sulla VPS:

```powershell
cd C:\StatArb\tg_tradingo
python analyze_signal_stats.py --stats "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\AE2CC2E013FDE1E3CDF010AA51C60400\MQL5\Files\tradingo_signal_stats.csv" --bridge-log C:\TG_TradinGo\logs\tradingo_20260721.log
```

---

## Classifica copy automatico (non pips marketing)

| # | Canale | Esecuzione | Parser | Allineamento pips TG | Note PnL stimato |
|---|--------|------------|--------|----------------------|------------------|
| 1 | **STARK** | Alta (13 OPEN EA) | Buono | Alto se OPEN ok | Scalp positivi; **2× err 10016** il 22/07 15:00 |
| 2 | **IVAN** | Alta (28 OPEN EA, multi-TP) | Buono (gap METÀ SIZE) | Medio-alto | ~70% cicli; Meta size 0.05 ok |
| 3 | **GOLD** | Media (16 OPEN EA) | Gap BE / partial closure | Medio | Rumore da stack + BE mancante |
| 4 | **ORO** | Bassa (~7–8 OPEN vs ~18–21 cancel) | Buono | Basso | Recap canale (+530 / +320 pips) non replicabile |
| 5 | **FOREX** | Nessuna (0 OPEN) | Pending NEW ORDER | N/A | Solo `UPDATE_TP` orfani |

---

## Conteggi per canale (da log)

### GOLD
- Bridge: OPEN **5**, UPDATE_OPEN **6**, OPEN_NOW **7**, CLOSE_HALF_BE **3**
- EA: **16** `Opened TG-GOLD-*` (7 OPEN_NOW, 9 DIRECT)
- Cancel: **1** (22/07 08:39 SELL range 4120–4130, distanza 303 pt)
- Segnali persi gestione: `Partial closure break Even` (×≥4), `break Even` standalone (×≥2)

### FOREX
- Bridge OPEN: **0**
- Solo UPDATE_TP (NZDJPY, XAUUSDpm)

### ORO
- Bridge OPEN: **~52** righe (include edit/duplicati)
- EA OPEN: **~7–8**; CANCELLED_RANGE: **~18–21** unici
- WinError 5 su `signal_ch_oro.json`: **3** (`21/07 16:32`, `21:15`, `22/07 02:32`)
- Gap vs TG: canale “+530 pips / 9 win”, “320 pips / 4 TP” — bot ne prende pochi (tolleranza 150)

### STARK
- Bridge OPEN: **26**; EA OPEN: **13** lot 0.20
- Fail: **2** Invalid stops / **10016** (22/07 15:00:08, 15:01:17)

### IVAN
- Bridge OPEN: **14** (~7 setup MSG+EDIT); CHECK_AND_BE **10**; CLOSE_ALL **2**
- EA: **28** OPEN (20×0.10, 8×0.05 Meta size)
- Gap: `METÀ SAZIE` / `SIZE` del 22/07 13:20 → lotto pieno 4×0.10

---

## Segnali persi vs messaggi Telegram (sintesi)

| Canale | Messaggio | Effetto |
|--------|-----------|---------|
| GOLD | `Partial closure break Even` | Nessun JSON (bug substring) |
| GOLD | `break Even` | Ignorato da `ignore_pats` |
| GOLD | Sell limit gold … | Non supportato |
| IVAN | `METÀ SAZIE` / accenti | `lot_factor` restava 1.0 |
| ORO | Range lontano >150 pt | SIGNAL_CANCELLED (canale spesso in TP) |
| STARK | SL/TP troppo stretti | Open fail 10016 |
| FOREX | NEW ORDER senza Modified TP | Nessun OPEN nel periodo |

---

## Fix implementati in questo PR (bridge v2.03 / EA v2.06)

1. GOLD: `PARTIAL CLOSURE` → `CLOSE_HALF_BE`; `break even` standalone / TP1+BE → `CHECK_AND_BE`
2. IVAN: `METÀ/MEZZA/META SIZE|SAZIE` (accent-fold) → `lot_factor=0.5`
3. Bridge: retry atomico 5× su WinError 5 / PermissionError
4. EA: `AdjustStopsToMinDistance` pre-OrderSend; `InpOroRangeTolerancePoints=250`
5. Deploy: copia anche `TG_TradinGoEA.mq5` in `C:\TG_TradinGo\mql5` e Experts (compile manuale)

---

## Deploy consigliato (VPS)

```powershell
cd C:\StatArb
git fetch origin
git checkout cursor/tg-tradingo-hardening-8e22   # o main dopo merge
git pull
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
# Riavvio bridge
C:\TG_TradinGo\start_tradingo.bat
```

Poi MetaEditor: apri `TG_TradinGoEA.mq5` → **F7** → un solo grafico EA (`InpClearSignalAfterProcess=true`).
