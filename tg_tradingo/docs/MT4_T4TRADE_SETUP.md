# MT4 T4Trade — setup Contabo (JSON come le altre installazioni MT5)

Il parser e le regole restano nel **bridge Python**. L’EA MT4 legge gli stessi
`signal_ch_*.json` già scritti per Vantage / Gamehosting / iFunds.

Contratto: [`EA_SPEC.md`](EA_SPEC.md) (bridge **2.14**).  
EA: `tg_tradingo/mql4/TG_TradinGoEA.mq4` versione **1.00**.

## Path Contabo

| Ruolo | Path |
|-------|------|
| Terminal MT4 T4Trade | `...\Terminal\893F70E9EF760D3B32BDD358B27B8555\` |
| Experts | `...\MQL4\Experts\` |
| Files (sandbox EA) | `...\MQL4\Files\` |
| Segnali (consigliato) | `...\MQL4\Files\tradingo\` |
| Terminal MT5 iFunds (solo scrittura JSON per ora) | `...\Terminal\2CF3572F498D78B167929E1A97715940\MQL5\` |

## 1. Cartella segnali (junction consigliata)

Da PowerShell Admin su Contabo:

```powershell
$mt4Files = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\893F70E9EF760D3B32BDD358B27B8555\MQL4\Files"
$mt5Ifunds = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\2CF3572F498D78B167929E1A97715940\MQL5\Files"
New-Item -ItemType Directory -Force -Path $mt4Files | Out-Null
New-Item -ItemType Directory -Force -Path $mt5Ifunds | Out-Null

# Opzione A: bridge scrive direttamente in queste cartelle (vedi mt5_instances sotto)
New-Item -ItemType Directory -Force -Path (Join-Path $mt4Files "tradingo") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $mt5Ifunds "tradingo") | Out-Null
```

L’EA MT4 usa `InpSignalsPath=tradingo\` e `InpUseAbsolutePath=false` (come Gamehosting).

## 2. `tradingo_config.json` — aggiungi due istanze

Non committare il file di produzione. Aggiungi a `mt5_instances` (il nome dell’array resta storico; vale anche per MT4):

```json
{
  "name": "Contabo_T4Trade_MT4",
  "enabled": true,
  "signals_path": "C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\893F70E9EF760D3B32BDD358B27B8555\\MQL4\\Files\\tradingo"
},
{
  "name": "Contabo_iFunds_MT5",
  "enabled": true,
  "signals_path": "C:\\Users\\Administrator\\AppData\\Roaming\\MetaQuotes\\Terminal\\2CF3572F498D78B167929E1A97715940\\MQL5\\Files\\tradingo"
}
```

Dopo il restart del bridge, i JSON e l’heartbeat compaiono in entrambe le cartelle
anche se iFunds non ha ancora un conto loggato. Quando fai login + attach EA MT5,
parte subito.

## 3. Compilare e attaccare l’EA MT4

1. Copia `TG_TradinGoEA.mq4` in `MQL4\Experts\` (il deploy script lo fa se presenti i path).
2. MetaEditor → Compile (F7).
3. Chart qualsiasi → attach EA → Load preset  
   `mql4/presets/TG_TradinGo_T4Trade_Reale.set` (lotti **0.01**).
4. AutoTrading ON. Allow live trading.

Per disabilitare oro-vip e stark solo su MT4:  
`InpChannels=gold,forex,ivan` (non tocca il bridge globale).

## 4. Smoke test

1. Verifica file: `...\MQL4\Files\tradingo\signal_ch_*.json` e `tradingo_heartbeat.json`.
2. Log Experts: `[TradinGo] EA v1.00 (MT4) started`.
3. Opzionale: scrivi un OPEN di prova con lotto 0.01 e poi `CLOSE_ALL_SYMBOL`.

## Limitazioni v1.00 MT4

- Stesse azioni JSON del MT5 (OPEN*, UPDATE_*, CLOSE_*, BE, CLOSE_SELECTIVE, …).
- Niente journal MAE/MFE / guard DD iFunds / single-instance lock (restano sull’EA MT5).
- Heartbeat gate sì (`InpHeartbeatMaxAgeSec`).
- Stats: `MQL4\Files\tradingo_signal_stats.csv`.
