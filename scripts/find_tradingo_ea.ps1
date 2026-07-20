# Cerca TG_TradinGoEA.mq5 sulla VPS Windows
# Esegui sulla VPS come Administrator:
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\find_tradingo_ea.ps1

$ErrorActionPreference = "SilentlyContinue"
$names = @("TG_TradinGoEA.mq5", "TG_TradinGoEA.ex5", "TG_tradingoEA.mq5")

Write-Host "=== Ricerca EA TradinGo ===" -ForegroundColor Cyan

foreach ($name in $names) {
    Write-Host "`n--- $name ---" -ForegroundColor Yellow
    $roots = @(
        "C:\TG_TradinGo",
        "C:\StatArb",
        "C:\Program Files",
        "C:\Program Files (x86)",
        "$env:APPDATA\MetaQuotes\Terminal"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem -Path $root -Recurse -Filter $name -ErrorAction SilentlyContinue |
            Select-Object FullName, Length, LastWriteTime
    }
}

Write-Host "`n--- Terminali MT5 (hash cartelle) ---" -ForegroundColor Yellow
$termRoot = "$env:APPDATA\MetaQuotes\Terminal"
if (Test-Path $termRoot) {
    Get-ChildItem $termRoot -Directory | ForEach-Object {
        $hash = $_.Name
        $experts = Join-Path $_.FullName "MQL5\Experts"
        $files   = Join-Path $_.FullName "MQL5\Files"
        $ea = Get-ChildItem $experts -Filter "*TradinGo*" -ErrorAction SilentlyContinue
        $sig = Get-ChildItem $files -Filter "signal_ch_*.json" -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            TerminalHash = $hash
            ExpertsPath  = $experts
            TradinGoEA   = ($ea | ForEach-Object { $_.Name }) -join ", "
            SignalFiles  = ($sig | ForEach-Object { $_.Name }) -join ", "
        }
    } | Format-Table -AutoSize
}

Write-Host "`n--- Segnali in C:\TG_TradinGo\signals ---" -ForegroundColor Yellow
$sigDir = "C:\TG_TradinGo\signals"
if (Test-Path $sigDir) {
    Get-ChildItem $sigDir -Filter "signal_ch_*.json" |
        Select-Object Name, Length, LastWriteTime
} else {
    Write-Host "Cartella non trovata: $sigDir"
}

Write-Host "`nFatto. Confronta con tg_tradingo\mql5\TG_TradinGoEA.mq5 in repo." -ForegroundColor Green
