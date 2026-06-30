# Importa C:\TG_TradinGo nella repo git (tg_tradingo/).
# Esegui dalla VPS: powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\import_tg_tradingo_to_repo.ps1

$ErrorActionPreference = "Stop"
$src = "C:\TG_TradinGo"
$dst = "C:\StatArb\tg_tradingo"
$fixtures = Join-Path $dst "docs\fixtures"

if (-not (Test-Path $src)) {
    Write-Error "Cartella sorgente mancante: $src"
}

New-Item -ItemType Directory -Path $dst -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dst "signals") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dst "logs") -Force | Out-Null
New-Item -ItemType Directory -Path $fixtures -Force | Out-Null

$copyFiles = @(
    "tradingo_bridge.py",
    "dump_channels.py",
    "sample_channels.py",
    "fetch_apr21.py",
    "start_tradingo.bat",
    "README.md"
)

foreach ($name in $copyFiles) {
    $from = Join-Path $src $name
    if (Test-Path $from) {
        Copy-Item $from (Join-Path $dst $name) -Force
        Write-Host "OK $name"
    }
}

# Bridge + fixture grandi (sempre sovrascrive)
python C:\StatArb\scripts\copy_tg_bridge_once.py

$fixtureLogs = @(
    "signal_samples.txt",
    "signals_apr21.txt",
    "channel_dump.txt"
)
foreach ($name in $fixtureLogs) {
    $from = Join-Path $src "logs\$name"
    if (Test-Path $from) {
        Copy-Item $from (Join-Path $fixtures $name) -Force
        Write-Host "OK fixture $name"
    }
}

# Template segnali NONE
foreach ($n in 1..4) {
    $tpl = Join-Path $dst "signals\signal_ch$n.json.example"
    '{"action": "NONE"}' | Set-Content $tpl -Encoding utf8
}

Write-Host ""
Write-Host "Fatto. NON copiato tradingo_config.json (segreti)."
Write-Host "Usa tradingo_config.example.json nella repo e copialo sulla VPS."
