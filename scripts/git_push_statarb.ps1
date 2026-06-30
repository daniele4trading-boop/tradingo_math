# StatArb VPS — commit e push su GitHub (repo tradingo_system)
# Esegui dalla VPS: powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\git_push_statarb.ps1

$ErrorActionPreference = "Stop"
Set-Location C:\StatArb

$markers = @(
    "preflight.py",
    "accounts.json",
    "params.json",
    "core\config.py",
    "scanner\scanner.py",
    "engine\pair_engine.py",
    "execution\hedge.py",
    "risk\manager.py",
    "ui\app.py",
    "backtest\runner.py",
    "launch\pipeline.py",
    "tests\test_module8_launch.py",
    "CHECKLIST_LUNEDI.md"
)

Write-Host "=== Verifica progetto MT5 StatArb ==="
foreach ($m in $markers) {
    if (-not (Test-Path $m)) {
        Write-Host "FAIL: file mancante $m"
        exit 1
    }
    Write-Host "OK $m"
}

if (-not (Test-Path ".git")) {
    git init
    git remote add origin https://github.com/daniele4trading-boop/tradingo_system.git
}

$branch = "statarb-vps-mt5-modules-0-8"
git checkout -B $branch 2>$null
if ($LASTEXITCODE -ne 0) { git branch -M $branch }

git add -A
git status --short

git commit -m "StatArb MT5 modules 0-8 — VPS complete bootstrap" -m "Scanner, engine, execution, risk, Streamlit UI, backtest, launch orchestration, acceptance tests, and Monday checklist. Target: C:\StatArb on Windows VPS with Ultima/Vantage legs."

if ($LASTEXITCODE -ne 0) {
    Write-Host "Nessun nuovo commit (già aggiornato?) oppure errore commit."
}

git push -u origin $branch
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "PUSH OK — branch: $branch"
    Write-Host "PR: https://github.com/daniele4trading-boop/tradingo_system/compare/$branch"
}
