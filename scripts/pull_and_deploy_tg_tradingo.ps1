# Recover dirty C:\StatArb tree, pull TG TradinGo branch, deploy to C:\TG_TradinGo.
#
# Fixes the common VPS failure:
#   - local edits block git pull
#   - untracked analyze_signal_stats.py blocks merge
#   - second bridge instance => Telethon "database is locked"
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\pull_and_deploy_tg_tradingo.ps1
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\pull_and_deploy_tg_tradingo.ps1 -Branch cursor/tg-tradingo-hardening-8e22
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\pull_and_deploy_tg_tradingo.ps1 -StopBridge

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\StatArb",
    [string]$Branch = "cursor/tg-tradingo-hardening-8e22",
    [switch]$StopBridge,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Get-BridgeProcesses {
    return @(
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match "tradingo_bridge\.py" }
    )
}

function Stop-BridgeProcesses {
    $procs = Get-BridgeProcesses
    if ($procs.Count -eq 0) {
        Write-Host "No tradingo_bridge.py process found."
        return
    }
    foreach ($p in $procs) {
        Write-Host "Stopping PID $($p.ProcessId): $($p.CommandLine)"
        if (-not $DryRun) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 2
    $left = Get-BridgeProcesses
    if ($left.Count -gt 0) {
        Write-Host "WARN: $($left.Count) bridge process(es) still alive" -ForegroundColor Yellow
    }
    else {
        Write-Host "OK all bridge processes stopped" -ForegroundColor Green
    }
}

Write-Step "Repo check"
if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    Write-Error "Not a git repo: $RepoRoot"
}
Set-Location $RepoRoot
Write-Host "RepoRoot: $RepoRoot"
Write-Host "Branch:   $Branch"

Write-Step "Bridge processes (session lock check)"
$running = Get-BridgeProcesses
Write-Host "Running bridge instances: $($running.Count)"
if ($StopBridge -or $running.Count -gt 1) {
    if ($running.Count -gt 1) {
        Write-Host "Multiple bridge instances detected (causes database is locked). Stopping all." -ForegroundColor Yellow
    }
    Stop-BridgeProcesses
}
elseif ($running.Count -eq 1) {
    Write-Host "One bridge still running. Pass -StopBridge to kill it before deploy/restart." -ForegroundColor Yellow
}

Write-Step "Stash local changes (including untracked)"
$status = git status --porcelain
if ($status) {
    Write-Host $status
    if ($DryRun) {
        Write-Host "[DRY-RUN] Would: git stash push -u -m ..."
    }
    else {
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        git stash push -u -m "vps-auto-stash-before-$Branch-$stamp"
        if ($LASTEXITCODE -ne 0) {
            Write-Error "git stash failed"
        }
        Write-Host "OK stashed local/untracked changes" -ForegroundColor Green
    }
}
else {
    Write-Host "Working tree clean"
}

Write-Step "Fetch + hard reset to origin/$Branch"
if ($DryRun) {
    Write-Host "[DRY-RUN] Would fetch and reset --hard origin/$Branch"
}
else {
    git fetch origin $Branch
    if ($LASTEXITCODE -ne 0) { Write-Error "git fetch failed" }

    $current = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($current -ne $Branch) {
        git checkout -B $Branch "origin/$Branch"
        if ($LASTEXITCODE -ne 0) { Write-Error "git checkout failed" }
    }
    else {
        git reset --hard "origin/$Branch"
        if ($LASTEXITCODE -ne 0) { Write-Error "git reset --hard failed" }
    }
    git clean -fd -- tg_tradingo/analyze_signal_stats.py 2>$null
    Write-Host "OK HEAD = $(git rev-parse --short HEAD) on $Branch" -ForegroundColor Green
}

Write-Step "Deploy to C:\TG_TradinGo"
$deploy = Join-Path $RepoRoot "scripts\deploy_tg_tradingo_to_vps.ps1"
if (-not (Test-Path $deploy)) {
    Write-Error "Deploy script missing: $deploy"
}
if ($DryRun) {
    & powershell -ExecutionPolicy Bypass -File $deploy -DryRun
}
else {
    & powershell -ExecutionPolicy Bypass -File $deploy
    if ($LASTEXITCODE -ne 0) { Write-Error "Deploy failed" }
}

Write-Step "Next steps"
Write-Host "1) Close any remaining bridge window (Ctrl+C)."
Write-Host "2) Start ONE instance: C:\TG_TradinGo\start_tradingo.bat"
Write-Host "3) Confirm banner shows: TG TradinGo Bridge v2.03"
Write-Host "4) MetaEditor F7 on TG_TradinGoEA.mq5 (EA v2.06), reattach on one chart only."
Write-Host ""
Write-Host "If you need stashed VPS local edits back:"
Write-Host "  cd C:\StatArb"
Write-Host "  git stash list"
Write-Host "  git stash show -p stash@{0}"
