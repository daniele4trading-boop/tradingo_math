# Deploy tg_tradingo from repo (C:\StatArb) to production (C:\TG_TradinGo)
#
# - Timestamped backup before each deploy
# - Does NOT overwrite: tradingo_config.json, signals/*.json runtime, state/*.json
# - Does NOT start/stop the bridge (manual restart required)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1 -DryRun
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\deploy_tg_tradingo_to_vps.ps1 -SkipBackup
#
# NOTE: ASCII-only comments/strings for Windows PowerShell 5.1 (UTF-8 without BOM
#       used to break parsing on em-dashes / box-drawing chars).

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

# Files to deploy (code + start script)
$deployFiles = @(
    "tradingo_bridge.py",
    "bridge_core.py",
    "bridge_journal.py",
    "dump_channels.py",
    "sample_channels.py",
    "sample_last_24h.py",
    "fetch_apr21.py",
    "fetch_date_range.py",
    "analyze_signal_stats.py",
    "analyze_journal.py",
    "resolve_channels.py",
    "start_tradingo.bat",
    "start_webapp.bat",
    "webapp_config.example.json",
    "requirements.txt",
    "README.md",
    "AGENTS.md",
    "INVENTORY.md"
)

# Folders copied recursively (code only, never runtime data)
$deployDirs = @(
    "webapp"
)

# EA source (copy only; MetaEditor F7 remains manual on VPS)
$eaSrcRelative = "mql5\TG_TradinGoEA.mq5"
$eaProdCopyDir = Join-Path $ProdRoot "mql5"
$eaTerminalExperts = @(
    "C:\Users\Administrator\AppData\Roaming\MetaQuotes\Terminal\AE2CC2E013FDE1E3CDF010AA51C60400\MQL5\Experts"
)

# Never overwrite these in production
$neverOverwrite = @(
    "tradingo_config.json",
    "webapp_config.json",
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
        Write-Host "WARN: cannot read $ConfigPath for state path merge" -ForegroundColor Yellow
        return
    }

    if (-not $raw.paths) { $raw | Add-Member -NotePropertyName paths -NotePropertyValue (@{}) }

    $statePath = "C:\TG_TradinGo\state"
    if ($raw.paths.state -and ($raw.paths.state -eq $statePath)) {
        Write-Host "OK tradingo_config.json: paths.state already set"
        return
    }

    if ($DryRun) {
        Write-Host "[DRY-RUN] Would set paths.state = $statePath in tradingo_config.json"
        return
    }

    $raw.paths.state = $statePath
    $json = $raw | ConvertTo-Json -Depth 10
    Set-Content -Path $ConfigPath -Value $json -Encoding UTF8
    Write-Host "OK tradingo_config.json: added paths.state = $statePath" -ForegroundColor Green
}

# --- Validation ---

Write-Step "Validate paths"

if (-not (Test-Path $src)) {
    Write-Error "Repo folder missing: $src`nRun first: cd C:\StatArb && git pull"
}

$missing = @()
foreach ($f in $deployFiles) {
    if (-not (Test-Path (Join-Path $src $f))) {
        $missing += $f
    }
}
if ($missing.Count -gt 0) {
    Write-Error "Missing files in $src :`n  - $($missing -join "`n  - ")`nRun git pull on C:\StatArb"
}

Write-Host "Repo:       $src"
Write-Host "Production: $dst"
if ($DryRun) { Write-Host "MODE: DRY-RUN (no changes)" -ForegroundColor Yellow }
if ($SkipBackup) { Write-Host "MODE: SKIP BACKUP" -ForegroundColor Yellow }

# --- Backup ---

Write-Step "Backup production"

if (-not (Test-Path $dst)) {
    Write-Host "Production folder missing, will be created: $dst"
}
elseif (-not $SkipBackup) {
    $toBackup = @()
    foreach ($f in $deployFiles) {
        $prodFile = Join-Path $dst $f
        if (Test-Path $prodFile) { $toBackup += $f }
    }
    if (Test-Path (Join-Path $dst "tradingo_config.json")) {
        $toBackup += "tradingo_config.json"
    }
    $eaProdExisting = Join-Path $eaProdCopyDir "TG_TradinGoEA.mq5"
    if (Test-Path $eaProdExisting) {
        $toBackup += "mql5\TG_TradinGoEA.mq5"
    }

    if ($toBackup.Count -eq 0) {
        Write-Host "No existing files to backup (first deploy?)"
    }
    else {
        if ($DryRun) {
            Write-Host "[DRY-RUN] Backup to: $backupDir"
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
            Write-Host "Backup saved: $backupDir" -ForegroundColor Green
        }
    }
}

# --- Runtime dirs ---

Write-Step "Runtime folders"

$runtimeDirs = @(
    (Join-Path $dst "logs"),
    (Join-Path $dst "signals"),
    (Join-Path $dst "state"),
    (Join-Path $dst "journal"),
    (Join-Path $dst "journal\bridge_events"),
    $eaProdCopyDir
)
# Never wipe existing journal files — only ensure folders exist.

foreach ($dir in $runtimeDirs) {
    if ($DryRun) {
        Write-Host "[DRY-RUN] mkdir $dir"
    }
    else {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "OK $dir"
    }
}

# --- Deploy code files ---

Write-Step "Deploy code files"

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

foreach ($d in $deployDirs) {
    $fromDir = Join-Path $src $d
    $toDir = Join-Path $dst $d
    if (-not (Test-Path $fromDir)) {
        Write-Host "SKIP folder (missing in repo): $d" -ForegroundColor Yellow
        continue
    }
    if ($DryRun) {
        Write-Host "[DRY-RUN] copy folder $d\ (recursive)"
        continue
    }
    New-Item -ItemType Directory -Path $toDir -Force | Out-Null
    Copy-Item (Join-Path $fromDir "*") $toDir -Recurse -Force
    Write-Host "OK $d\ (folder)"
}

# --- Deploy EA mq5 (no compile) ---

Write-Step "Deploy EA MQ5 (source copy; MetaEditor compile is manual)"

$eaFrom = Join-Path $src $eaSrcRelative
if (-not (Test-Path $eaFrom)) {
    Write-Host "WARN: EA not found in repo: $eaFrom" -ForegroundColor Yellow
}
else {
    $eaTargets = @()
    $eaTargets += (Join-Path $eaProdCopyDir "TG_TradinGoEA.mq5")
    foreach ($expertsDir in $eaTerminalExperts) {
        if (Test-Path $expertsDir) {
            $eaTargets += (Join-Path $expertsDir "TG_TradinGoEA.mq5")
        }
        else {
            Write-Host "SKIP Experts (missing folder): $expertsDir" -ForegroundColor Yellow
        }
    }

    foreach ($eaTo in $eaTargets) {
        if ($DryRun) {
            Write-Host "[DRY-RUN] copy EA -> $eaTo"
            continue
        }
        $parent = Split-Path $eaTo -Parent
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item $eaFrom $eaTo -Force
        Write-Host "OK EA -> $eaTo"
    }
    Write-Host "NOTE: open MetaEditor and compile (F7) TG_TradinGoEA.mq5, then reattach EA." -ForegroundColor Yellow

    # Preset .set files (Moneta etc.)
    $presetsSrc = Join-Path $src "mql5\presets"
    if (Test-Path $presetsSrc) {
        $presetsDst = Join-Path $dst "mql5\presets"
        if (-not $DryRun) {
            New-Item -ItemType Directory -Path $presetsDst -Force | Out-Null
            Copy-Item (Join-Path $presetsSrc "*.set") $presetsDst -Force -ErrorAction SilentlyContinue
            Write-Host "OK presets -> $presetsDst"
            foreach ($expertsDir in $eaTerminalExperts) {
                $termPresets = Join-Path (Split-Path (Split-Path $expertsDir -Parent) -Parent) "Presets"
                # Experts is ...\MQL5\Experts -> Presets is ...\MQL5\Presets
                $mql5 = Split-Path $expertsDir -Parent
                $termPresets = Join-Path $mql5 "Presets"
                if (Test-Path $mql5) {
                    New-Item -ItemType Directory -Path $termPresets -Force | Out-Null
                    Copy-Item (Join-Path $presetsSrc "*.set") $termPresets -Force -ErrorAction SilentlyContinue
                    Write-Host "OK presets -> $termPresets"
                }
            }
        }
        else {
            Write-Host "[DRY-RUN] copy presets *.set"
        }
    }
}

# --- Config (create only if missing) + merge state path ---

Write-Step "Configuration"

$configProd = Join-Path $dst "tradingo_config.json"
$configExample = Join-Path $src "tradingo_config.example.json"

if (-not (Test-Path $configProd)) {
    if ($DryRun) {
        Write-Host "[DRY-RUN] Would create tradingo_config.json from example"
    }
    elseif (Test-Path $configExample) {
        Copy-Item $configExample $configProd
        Write-Host "WARN: created tradingo_config.json from example - fill api_id/api_hash" -ForegroundColor Yellow
    }
}
else {
    Write-Host "OK tradingo_config.json exists - NOT modified"
}

Ensure-ConfigStatePath -ConfigPath $configProd

# --- Python deps check ---

Write-Step "Python dependencies"

$reqFile = Join-Path $dst "requirements.txt"
if (Test-Path $reqFile) {
    $pipCheck = & python -c "import telethon" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARN: Telethon not installed." -ForegroundColor Yellow
        Write-Host "      Run: pip install -r `"$reqFile`""
    }
    else {
        Write-Host "OK Telethon installed"
    }
}
else {
    Write-Host "WARN: requirements.txt not found in production"
}

# --- Bridge running? ---

Write-Step "Bridge status"

if (Test-BridgeRunning) {
    Write-Host "WARNING: tradingo_bridge.py appears to be running." -ForegroundColor Yellow
    Write-Host "         .py files were updated but the live process still uses old code."
    Write-Host ""
    Write-Host "         To apply changes:"
    Write-Host "         1) Close ALL bridge windows (or Ctrl+C). database-is-locked = 2 instances"
    Write-Host "         2) Restart: C:\TG_TradinGo\start_tradingo.bat"
}
else {
    Write-Host "Bridge not running."
    Write-Host "Start manually: C:\TG_TradinGo\start_tradingo.bat"
}

# --- Summary ---

Write-Step "Summary"

Write-Host "Deploy completed in $dst"
Write-Host ""
Write-Host "NOT modified (by design):"
foreach ($f in $neverOverwrite) {
    Write-Host "  - $f"
}
Write-Host ""
Write-Host "Optional parser test (from repo):"
Write-Host "  cd C:\StatArb\tg_tradingo"
Write-Host "  pip install -r requirements.txt"
Write-Host "  python -m pytest tests/ -v"
Write-Host ""

if (-not $DryRun -and -not $SkipBackup -and (Test-Path $backupDir)) {
    Write-Host "Manual rollback (if needed):"
    Write-Host "  Copy-Item `"$backupDir\*`" `"$dst`" -Recurse -Force"
    Write-Host "  (exclude signals/ and state/ if you do not want to restore them)"
}
