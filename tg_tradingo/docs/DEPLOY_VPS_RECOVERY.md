# Deploy VPS — recovery (git pull bloccato / database locked)

## Sintomi tipici

1. `git pull` fallisce: *local changes would be overwritten* / untracked `analyze_signal_stats.py`
2. `deploy_tg_tradingo_to_vps.ps1` → `MissingEndCurlyBrace` (script vecchio o encoding PS 5.1)
3. Bridge banner ancora **v2.02**
4. `sqlite3.OperationalError: database is locked` sulla session Telethon = **due istanze** del bridge

## Comando unico consigliato

Nella PowerShell sulla VPS:

```powershell
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\pull_and_deploy_tg_tradingo.ps1 -StopBridge
```

Poi **una sola** finestra:

```bat
C:\TG_TradinGo\start_tradingo.bat
```

Verifica nel log: `TG TradinGo Bridge v2.03`.

## Passi manuali equivalenti

```powershell
# 1) Ferma TUTTE le istanze bridge
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'tradingo_bridge\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 2) Salva modifiche locali e allinea al branch
cd C:\StatArb
git stash push -u -m "vps-local-before-hardening"
git fetch origin cursor/tg-tradingo-hardening-8e22
git checkout -B cursor/tg-tradingo-hardening-8e22 origin/cursor/tg-tradingo-hardening-8e22
git reset --hard origin/cursor/tg-tradingo-hardening-8e22

# 3) Deploy (non tocca tradingo_config.json)
powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1

# 4) Riavvio bridge (una istanza)
C:\TG_TradinGo\start_tradingo.bat
```

## EA

Dopo deploy, MetaEditor → `TG_TradinGoEA.mq5` → **F7** → un solo grafico EA.

**Deve loggare `EA v2.07 started`.** Se vedi `v2.04` / `v2.05`, stai ancora sul `.ex5` vecchio (non compilato).

### Anti-replay (obbligatorio prima di riattaccare un EA vecchio)

Se l'EA non è ancora v2.07, azzera i JSON a mano (altrimenti riesegue OPEN vecchi):

```powershell
$dir = "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\AE2CC2E013FDE1E3CDF010AA51C60400\MQL5\Files"
foreach ($f in "gold","forex","oro","stark","ivan") {
  Set-Content -Path (Join-Path $dir "signal_ch_$f.json") -Value '{"action":"NONE"}' -Encoding UTF8
}
```

Con **v2.07** (`InpIgnoreExistingOnInit=true`) lo fa l'EA all'init.
