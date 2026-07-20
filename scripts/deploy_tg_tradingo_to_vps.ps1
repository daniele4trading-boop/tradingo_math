# Deploy tg_tradingo dalla repo (C:\StatArb) alla produzione (C:\TG_TradinGo)
#
# - Backup automatico timestampato prima di ogni deploy
# - NON sovrascrive: tradingo_config.json, signals/*.json runtime, state/*.json
# - NON avvia/ferma il bridge (richiede conferma manuale)
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1 -DryRun
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1 -SkipBackup

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\StatArb",
    [string]$ProdRoot = "C:\TG_TradinGo",
    [switch]$DryRun,
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"

$src = Join-Path $RepoRoot "tg_tradingo"
$dst = $ProdRoot
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path $ProdRoot "_backups"
$backupDir = Join-Path $backupRoot "backup_$timestamp"

# File da deployare (codice + script avvio)
$deployFiles = @(
    "tradingo_bridge.py",
    "bridge_core.py",
    "dump_channels.py",
    "sample_channels.py",
    "fetch_apr21.py",
    "start_tradingo.bat",
    "requirements.txt",
    "README.md",
    "AGENTS.md",
    "INVENTORY.md"
)

# File/cartelle MAI sovrascritti in produzione
$neverOverwrite = @(
    "tradingo_config.json",
    "signals\signal_ch_gold.json",
    "signals\signal_ch_forex.json",
    "signals\signal_ch_oro.json",
    "signals\signal_ch_stark.json",
    "signals\signal_ch_ivan.json",
    "state\bridge_state.json",
    "state\processed_messages.json"
)

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-BridgeRunning {
    $procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "tradingo_bridge\.py" }
    return @($procs).Count -gt 0
}

function Ensure-ConfigStatePath {
    param([string]$ConfigPath)

    if (-not (Test-Path $ConfigPath)) { return }

    try {
        $raw = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        Write-Host "WARN: impossibile leggere $ConfigPath per merge path state" -ForegroundColor Yellow
        return
    }

    if (-not $raw.paths) { $raw | Add-Member -NotePropertyName paths -NotePropertyValue (@{}) }

    $statePath = "C:\TG_TradinGo\state"
    if ($raw.paths.state -and ($raw.paths.state -eq $statePath)) {
        Write-Host "OK tradingo_config.json: paths.state gia' presente"
        return
    }

    if ($DryRun) {
        Write-Host "[DRY-RUN] Aggiungerei paths.state = $statePath in tradingo_config.json"
        return
    }

    $raw.paths.state = $statePath
    $json = $raw | ConvertTo-Json -Depth 10
    Set-Content -Path $ConfigPath -Value $json -Encoding UTF8
    Write-Host "OK tradingo_config.json: aggiunto paths.state = $statePath" -ForegroundColor Green
}

# ── Validazione ──────────────────────────────────────────────────────────────

Write-Step "Validazione percorsi"

if (-not (Test-Path $src)) {
    Write-Error "Cartella repo mancante: $src`nEsegui prima: cd C:\StatArb && git pull"
}

$missing = @()
foreach ($f in $deployFiles) {
    if (-not (Test-Path (Join-Path $src $f))) {
        $missing += $f
    }
}
if ($missing.Count -gt 0) {
    Write-Error "File mancanti in $src :`n  - $($missing -join "`n  - ")`nEsegui git pull su C:\StatArb"
}

Write-Host "Repo:       $src"
Write-Host "Produzione: $dst"
if ($DryRun) { Write-Host "MODALITA': DRY-RUN (nessuna modifica)" -ForegroundColor Yellow }
if ($SkipBackup) { Write-Host "MODALITA': SKIP BACKUP" -ForegroundColor Yellow }

# ── Backup ─────────────────────────────────────────────────────────────────────

Write-Step "Backup produzione"

if (-not (Test-Path $dst)) {
    Write-Host "Cartella produzione non esiste, verra' creata: $dst"
}
elseif (-not $SkipBackup) {
  $toBackup = @()
  foreach ($f in $deployFiles) {
    $prodFile = Join-Path $dst $f
    if (Test-Path $prodFile) { $toBackup += $f }
  }
  # backup anche config (solo copia, non deploy)
  if (Test-Path (Join-Path $dst "tradingo_config.json")) {
    $toBackup += "tradingo_config.json"
  }

  if ($toBackup.Count -eq 0) {
    Write-Host "Nessun file esistente da backuppare (primo deploy?)"
  }
  else {
    if ($DryRun) {
      Write-Host "[DRY-RUN] Backup in: $backupDir"
      foreach ($f in $toBackup) { Write-Host "  - $f" }
    }
    else {
      New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
      foreach ($f in $toBackup) {
        $from = Join-Path $dst $f
        $to = Join-Path $backupDir $f
        $parent = Split-Path $to -Parent
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item $from $to -Force
        Write-Host "  backup: $f"
      }
      Write-Host "Backup salvato in: $backupDir" -ForegroundColor Green
    }
  }
}

# ── Cartelle runtime ───────────────────────────────────────────────────────────

Write-Step "Cartelle runtime"

$runtimeDirs = @(
    "$dst\logs",
    "$dst\signals",
    "$dst\state"
)

foreach ($dir in $runtimeDirs) {
    if ($DryRun) {
        Write-Host "[DRY-RUN] mkdir $dir"
    }
    else {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "OK $dir"
    }
}

# ── Deploy file ────────────────────────────────────────────────────────────────

Write-Step "Deploy file codice"

foreach ($f in $deployFiles) {
    $from = Join-Path $src $f
    $to = Join-Path $dst $f

    if ($DryRun) {
        Write-Host "[DRY-RUN] copy $f"
        continue
    }

    $parent = Split-Path $to -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    Copy-Item $from $to -Force
    Write-Host "OK $f"
}

# ── Config (solo se assente) + merge path state ───────────────────────────────

Write-Step "Configurazione"

$configProd = Join-Path $dst "tradingo_config.json"
$configExample = Join-Path $src "tradingo_config.example.json"

if (-not (Test-Path $configProd)) {
    if ($DryRun) {
        Write-Host "[DRY-RUN] Creerei tradingo_config.json da example"
    }
    elseif (Test-Path $configExample) {
        Copy-Item $configExample $configProd
        Write-Host "WARN: creato tradingo_config.json da example — compila api_id/api_hash" -ForegroundColor Yellow
    }
}
else {
    Write-Host "OK tradingo_config.json esistente — NON toccato"
}

Ensure-ConfigStatePath -ConfigPath $configProd

# ── Dipendenze Python (solo verifica, non install silenziosa) ─────────────────

Write-Step "Dipendenze Python"

$reqFile = Join-Path $dst "requirements.txt"
if (Test-Path $reqFile) {
    $pipCheck = & python -c "import telethon" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARN: Telethon non installato." -ForegroundColor Yellow
        Write-Host "      Esegui: pip install -r `"$reqFile`""
    }
    else {
        Write-Host "OK Telethon installato"
    }
}
else {
    Write-Host "WARN: requirements.txt non trovato in produzione"
}

# ── Bridge in esecuzione? ─────────────────────────────────────────────────────

Write-Step "Stato bridge"

if (Test-BridgeRunning) {
    Write-Host "ATTENZIONE: tradingo_bridge.py sembra in esecuzione." -ForegroundColor Yellow
    Write-Host "           I file .py sono stati aggiornati ma il processo attivo"
    Write-Host "           usa ancora il codice caricato in memoria."
    Write-Host ""
    Write-Host "           Per applicare le modifiche, dopo verifica:"
    Write-Host "           1) Chiudi la finestra del bridge (o Ctrl+C)"
    Write-Host "           2) Riavvia: C:\TG_TradinGo\start_tradingo.bat"
}
else {
    Write-Host "Bridge non in esecuzione."
    Write-Host "Avvio manuale: C:\TG_TradinGo\start_tradingo.bat"
}

# ── Riepilogo ─────────────────────────────────────────────────────────────────

Write-Step "Riepilogo"

Write-Host "Deploy completato in $dst"
Write-Host ""
Write-Host "NON modificati (by design):"
foreach ($f in $neverOverwrite) {
    Write-Host "  - $f"
}
Write-Host ""
Write-Host "Test parser (opzionale, dalla repo):"
Write-Host "  cd C:\StatArb\tg_tradingo"
Write-Host "  pip install -r requirements.txt"
Write-Host "  python -m pytest tests/ -v"
Write-Host ""

if (-not $DryRun -and -not $SkipBackup -and (Test-Path $backupDir)) {
    Write-Host "Rollback manuale (se serve):"
    Write-Host "  Copy-Item `"$backupDir\*`" `"$dst`" -Recurse -Force"
    Write-Host "  (escludi signals/ e state/ se non vuoi ripristinarli)"
}
