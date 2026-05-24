param(
    [string]$ServiceName = "TradinGOPlatformDashboard",
    [int]$Port = 8502
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$App = Join-Path $RepoRoot "dashboard\app.py"
$TaskName = $ServiceName
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"cd '$RepoRoot'; streamlit run '$App' --server.port $Port --server.address 0.0.0.0`""
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "Administrator" -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Force | Out-Null

New-NetFirewallRule -DisplayName "TradinGO Platform Dashboard $Port" `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -ErrorAction SilentlyContinue | Out-Null

Write-Host "Installed scheduled task $TaskName and firewall rule for TCP $Port"
