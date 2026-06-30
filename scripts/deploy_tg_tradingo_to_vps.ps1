# Deploy tg_tradingo dalla repo alla VPS C:\TG_TradinGo
# NON sovrascrive tradingo_config.json ne' signals/*.json runtime

$ErrorActionPreference = "Stop"
$src = "C:\StatArb\tg_tradingo"
$dst = "C:\TG_TradinGo"

if (-not (Test-Path $src)) { Write-Error "Repo path mancante: $src" }

New-Item -ItemType Directory -Path $dst -Force | Out-Null
New-Item -ItemType Directory -Path "$dst\logs" -Force | Out-Null
New-Item -ItemType Directory -Path "$dst\signals" -Force | Out-Null

$files = @(
    "tradingo_bridge.py",
    "dump_channels.py",
    "sample_channels.py",
    "fetch_apr21.py",
    "start_tradingo.bat",
    "README.md",
    "AGENTS.md"
)

foreach ($f in $files) {
    $from = Join-Path $src $f
    if (Test-Path $from) {
        Copy-Item $from (Join-Path $dst $f) -Force
        Write-Host "OK $f"
    }
}

if (-not (Test-Path "$dst\tradingo_config.json")) {
    Copy-Item (Join-Path $src "tradingo_config.example.json") "$dst\tradingo_config.json"
    Write-Host "WARN: creato tradingo_config.json da example — compila api_id/api_hash"
}

Write-Host "Deploy completato in $dst"
