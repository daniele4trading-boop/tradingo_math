# Pubblica su git lo snapshot messaggi Telegram (signal_last_24h.txt)
# così l'agente cloud puo' leggerlo direttamente dalla repo.
#
# Prerequisito:
#   cd C:\TG_TradinGo
#   python sample_last_24h.py --parser-dry-run --include-unknown
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\push_signal_snapshot_to_repo.ps1
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\push_signal_snapshot_to_repo.ps1 -Branch cursor/tg-tradingo-channel-audit

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\StatArb",
    [string]$ProdRoot = "C:\TG_TradinGo",
    [int]$Hours = 24,
    [string]$Branch = "cursor/tg-tradingo-channel-audit",
    [switch]$SkipGenerate
)

$ErrorActionPreference = "Stop"

$srcCandidates = @(
    (Join-Path $ProdRoot "logs\signal_last_${Hours}h.txt"),
    (Join-Path $ProdRoot "logs\signal_last_24h.txt")
)

$dstDir  = Join-Path $RepoRoot "tg_tradingo\docs\fixtures"
$dstFile = Join-Path $dstDir "signal_last_24h.txt"

Write-Host "==> Aggiorna file sampler in produzione" -ForegroundColor Cyan
$deploySampler = @("sample_last_24h.py", "bridge_core.py")
foreach ($name in $deploySampler) {
    $from = Join-Path $RepoRoot "tg_tradingo\$name"
    if (Test-Path $from) {
        Copy-Item $from (Join-Path $ProdRoot $name) -Force
        Write-Host "OK deploy $name -> $ProdRoot"
    }
}

Write-Host "==> Generazione snapshot (se necessario)" -ForegroundColor Cyan
if (-not $SkipGenerate) {
    $sampler = Join-Path $ProdRoot "sample_last_24h.py"
    if (-not (Test-Path $sampler)) {
        $sampler = Join-Path $RepoRoot "tg_tradingo\sample_last_24h.py"
        Copy-Item $sampler (Join-Path $ProdRoot "sample_last_24h.py") -Force
    }
    Push-Location $ProdRoot
    python $sampler --hours $Hours --parser-dry-run --include-unknown
    Pop-Location
}

$src = $null
foreach ($c in $srcCandidates) {
    if (Test-Path $c) { $src = $c; break }
}
if (-not $src) {
    Write-Error "Snapshot non trovato. Cercato:`n  $($srcCandidates -join "`n  ")"
}

Write-Host "==> Copia in repo" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
Copy-Item $src $dstFile -Force
Write-Host "OK $dstFile"

Write-Host "==> Git push" -ForegroundColor Cyan
Push-Location $RepoRoot
git fetch origin
$branchExists = git rev-parse --verify $Branch 2>$null
if ($LASTEXITCODE -ne 0) {
    git checkout -b $Branch
} else {
    git checkout $Branch
    git pull origin $Branch 2>$null
}

git add $dstFile
$status = git status --porcelain
if (-not $status) {
    Write-Host "Nessuna modifica da committare (file identico)."
    Pop-Location
    exit 0
}

$ts = Get-Date -Format "yyyy-MM-dd HH:mm"
git commit -m "Add Telegram signal snapshot last ${Hours}h ($ts UTC VPS)"
git push -u origin $Branch
Pop-Location

Write-Host ""
Write-Host "Fatto. Branch: $Branch" -ForegroundColor Green
Write-Host "File: tg_tradingo/docs/fixtures/signal_last_24h.txt"
Write-Host ""
Write-Host "All'agente cloud puoi dire:"
Write-Host "  Leggi tg_tradingo/docs/fixtures/signal_last_24h.txt dal branch $Branch"
