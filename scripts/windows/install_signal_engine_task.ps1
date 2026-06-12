param(
    [string]$RepoDir = "C:\TradinGO_Research",
    [string]$TaskName = "TradinGoSignalEngine",
    [string]$TerminalPath = "C:\Program Files\Ultima Markets MT5 Terminal\terminal64.exe",
    [string]$ApiBaseUrl = "http://127.0.0.1:8080",
    [string]$AdminApiKey = "dev-local-admin-key",
    [string]$Symbol = "XAUUSD",
    [int]$PollSeconds = 60
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $RepoDir)) {
    throw "RepoDir not found: $RepoDir"
}

if (!(Test-Path $TerminalPath)) {
    throw "MT5 terminal not found: $TerminalPath"
}

Set-Location $RepoDir

$RuntimeDir = Join-Path $RepoDir "runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$ReportDir = Join-Path $RepoDir "reports"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$Launcher = Join-Path $RuntimeDir "start_signal_engine.bat"
$LogPath = Join-Path $LogDir "signal_engine.log"
$JournalPath = Join-Path $ReportDir "live_signal_journal.csv"

$launcherBody = @"
@echo off
cd /d $RepoDir
python -m tradingo_core.signal_engine --loop --symbol $Symbol --terminal-path "$TerminalPath" --api-base-url $ApiBaseUrl --admin-api-key $AdminApiKey --journal-csv "$JournalPath" --poll-seconds $PollSeconds --risk-pct 0.005 --min-score 65 --min-sweep-volume-z 0.4 --min-displacement-range-atr 0.7 --min-displacement-volume-z 0.0 --max-retest-volume-z 1.2 --sl-buffer-atr 0.05 --rr 2 >> "$LogPath" 2>&1
"@

Set-Content -Path $Launcher -Value $launcherBody -Encoding ASCII

try {
    schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
} catch {
    # Task may not exist on first install.
}
schtasks /Create /TN $TaskName /SC ONSTART /RL HIGHEST /TR $Launcher /F | Out-Host
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
Set-ScheduledTask -TaskName $TaskName -Settings $Settings | Out-Null
schtasks /Run /TN $TaskName | Out-Host

Start-Sleep -Seconds 5

$proc = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -like "python*" -and $_.CommandLine -like "*tradingo_core.signal_engine*"
}

if ($proc) {
    Write-Output "Signal engine task installed and running. PID=$($proc.ProcessId)"
    exit 0
}

Write-Output "Signal engine task installed but process is not running. Last log lines:"
Get-Content $LogPath -Tail 80 -ErrorAction SilentlyContinue
exit 1
