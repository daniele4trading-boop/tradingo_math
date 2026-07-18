# Pubblica dump segnali per intervallo date su git (fixtures).
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\push_signal_dump_to_repo.ps1 -From 2026-07-13 -To 2026-07-17

[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\StatArb",
    [string]$ProdRoot = "C:\TG_TradinGo",
    [Parameter(Mandatory = $true)][string]$From,
    [Parameter(Mandatory = $true)][string]$To,
    [string]$Branch = "cursor/tg-tradingo-channel-audit",
    [switch]$SkipGenerate
)

$ErrorActionPreference = "Stop"

$fromTag = ([datetime]::Parse($From)).ToString("yyyyMMdd")
$toTag   = ([datetime]::Parse($To)).ToString("yyyyMMdd")
$fileName = "signals_${fromTag}_${toTag}.txt"
$src = Join-Path $ProdRoot "logs\$fileName"
$dst = Join-Path $RepoRoot "tg_tradingo\docs\fixtures\$fileName"

$tools = @("fetch_date_range.py", "resolve_channels.py", "bridge_core.py", "sample_last_24h.py")
foreach ($t in $tools) {
    $from = Join-Path $RepoRoot "tg_tradingo\$t"
    if (Test-Path $from) { Copy-Item $from (Join-Path $ProdRoot $t) -Force }
}

if (-not $SkipGenerate) {
    Push-Location $ProdRoot
    python fetch_date_range.py --from $From --to $To --parser-dry-run
    Pop-Location
}

if (-not (Test-Path $src)) { Write-Error "File mancante: $src" }

New-Item -ItemType Directory -Path (Split-Path $dst) -Force | Out-Null
Copy-Item $src $dst -Force

Push-Location $RepoRoot
git fetch origin
$exists = git rev-parse --verify $Branch 2>$null
if ($LASTEXITCODE -ne 0) { git checkout -b $Branch } else { git checkout $Branch }

git add $dst
git add tg_tradingo/docs/CHANNEL_MAP.md 2>$null
git add tg_tradingo/tradingo_config.example.json 2>$null
$status = git status --porcelain
if ($status) {
    git commit -m "Add signal dump $From to $To for channel mapping"
    git push -u origin $Branch
}
Pop-Location

Write-Host "Fatto: $dst su branch $Branch" -ForegroundColor Green
