#requires -Version 5.1
<#
.SYNOPSIS
  List Contabo autostart sources (Scheduled Tasks, Startup folders, Run keys).
#>
[CmdletBinding()]
param()

Write-Host ""
Write-Host "=== Scheduled Tasks (non-Microsoft, enabled or trading-related) ===" -ForegroundColor Cyan
Get-ScheduledTask | Where-Object {
    $_.TaskPath -notlike '\Microsoft\*' -or
    $_.TaskName -match 'TG_|TradinGo|StatArb|quant|python|MT5|MetaTrader|XM|Vantage|bridge|trading'
} | ForEach-Object {
    $i = $_ | Get-ScheduledTaskInfo
    [PSCustomObject]@{
        TaskName = $_.TaskName
        Path     = $_.TaskPath
        State    = $_.State
        LastRun  = $i.LastRunTime
        LastResult = $i.LastTaskResult
    }
} | Format-Table -AutoSize

Write-Host "=== Startup folders (shortcuts) ===" -ForegroundColor Cyan
$startupDirs = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp"
)
foreach ($d in $startupDirs) {
    Write-Host "-- $d"
    if (Test-Path $d) {
        Get-ChildItem $d -Force | ForEach-Object { "  $($_.Name) -> $($_.FullName)" }
    }
}

Write-Host ""
Write-Host "=== Run / RunOnce registry ===" -ForegroundColor Cyan
$runKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
)
foreach ($k in $runKeys) {
    Write-Host "-- $k"
    if (Test-Path $k) {
        Get-ItemProperty $k | Select-Object * -ExcludeProperty PS* | Format-List
    }
}

Write-Host "=== Tailscale / WireGuard services ===" -ForegroundColor Cyan
Get-Service -Name '*Tailscale*','*WireGuard*','*WireGuardTunnel*' -ErrorAction SilentlyContinue |
    Format-Table Name, Status, StartType -AutoSize

Write-Host "=== Python processes now ===" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Select-Object ProcessId, CommandLine | Format-List
