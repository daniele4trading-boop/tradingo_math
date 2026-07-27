#requires -Version 5.1
<#
.SYNOPSIS
  Contabo: disable old trading autostart + register TG TradinGo reboot stack.

.DESCRIPTION
  Creates at logon (after delay):
    - TG_TradinGo_BridgeAtLogon
    - TG_TradinGo_VantageMT5AtLogon (optional)
    - TG_TradinGo_XmMT5AtLogon (optional)

  Tailscale = Windows service (already).
  SMB remap = TG_TradinGo_EnsureFriendSmb (from ensure_friend_smb.ps1).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\list_contabo_autostart.ps1

  powershell -ExecutionPolicy Bypass -File .\setup_contabo_tg_autostart.ps1 `
    -RegisterBridge `
    -RegisterVantage `
    -VantageTerminalExe "C:\Program Files\Vantage International MT5\terminal64.exe" `
    -DisableNamePatterns @('StatArb','quantlab','module','scanner')
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$BridgeBat = "C:\TG_TradinGo\start_tradingo.bat",
    [string]$VantageTerminalExe = "",
    [string]$XmTerminalExe = "",
    [int]$BridgeDelaySec = 90,
    [int]$Mt5DelaySec = 20,
    [string[]]$DisableNamePatterns = @(),
    [switch]$DisableXmStartupShortcuts,
    [switch]$RegisterBridge,
    [switch]$RegisterVantage,
    [switch]$RegisterXm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Ok([string]$m) { Write-Host "[OK]   $m" -ForegroundColor Green }
function Write-WarnLine([string]$m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }

if ($DisableNamePatterns.Count -gt 0) {
    $tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue)
    foreach ($t in $tasks) {
        if ($t.TaskName -like 'TG_TradinGo_*') { continue }
        $hit = $false
        foreach ($pat in $DisableNamePatterns) {
            if ($t.TaskName -like "*$pat*" -or $t.TaskPath -like "*$pat*") {
                $hit = $true
                break
            }
        }
        if (-not $hit) { continue }
        if ($PSCmdlet.ShouldProcess($t.TaskName, "Disable Scheduled Task")) {
            Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue | Out-Null
            Write-Ok "Disabled task: $($t.TaskPath)$($t.TaskName)"
        }
    }
}

function New-TgLogonTask {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][string]$ExePath,
        [string]$ExeArgs = "",
        [int]$DelaySec = 0,
        [string]$WorkDir = ""
    )
    if (-not (Test-Path -LiteralPath $ExePath)) {
        throw "Not found: $ExePath"
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    $wd = if ($WorkDir) { $WorkDir } else { Split-Path -Parent $ExePath }
    if ($DelaySec -gt 0) {
        if ($ExePath -match '\.bat$|\.cmd$') {
            $cmdArgs = "/c timeout /t $DelaySec /nobreak >nul & call `"$ExePath`""
        }
        else {
            $extra = if ($ExeArgs) { " $ExeArgs" } else { "" }
            $cmdArgs = "/c timeout /t $DelaySec /nobreak >nul & start `"`" `"$ExePath`"$extra"
        }
        $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $cmdArgs -WorkingDirectory $wd
    }
    else {
        $action = New-ScheduledTaskAction -Execute $ExePath -Argument $ExeArgs -WorkingDirectory $wd
    }
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Ok "Registered $TaskName (delay=${DelaySec}s) -> $ExePath"
}

if ($RegisterBridge) {
    if (-not (Test-Path -LiteralPath $BridgeBat)) {
        throw "Bridge bat missing: $BridgeBat"
    }
    New-TgLogonTask -TaskName "TG_TradinGo_BridgeAtLogon" -ExePath $BridgeBat -DelaySec $BridgeDelaySec -WorkDir "C:\TG_TradinGo"
}

if ($RegisterVantage) {
    if ([string]::IsNullOrWhiteSpace($VantageTerminalExe)) {
        throw "Pass -VantageTerminalExe full path to terminal64.exe"
    }
    New-TgLogonTask -TaskName "TG_TradinGo_VantageMT5AtLogon" -ExePath $VantageTerminalExe -DelaySec $Mt5DelaySec
}

if ($RegisterXm) {
    if ([string]::IsNullOrWhiteSpace($XmTerminalExe)) {
        throw "Pass -XmTerminalExe full path to terminal64.exe"
    }
    New-TgLogonTask -TaskName "TG_TradinGo_XmMT5AtLogon" -ExePath $XmTerminalExe -DelaySec $Mt5DelaySec
}

if ($DisableXmStartupShortcuts) {
    $startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    Get-ChildItem $startup -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match 'XM|xm'
    } | ForEach-Object {
        if ($PSCmdlet.ShouldProcess($_.FullName, "Remove Startup shortcut")) {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Ok "Removed Startup shortcut: $($_.Name)"
        }
    }
}

Write-Host ""
Write-Info "TG_* scheduled tasks now:"
Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like 'TG_TradinGo_*' } |
    Format-Table TaskName, State -AutoSize

Write-Host ""
Write-WarnLine "Vantage: leave chart + EA attached, AutoTrading ON, save profile (default)."
Write-WarnLine "After reboot expect: Tailscale -> user logon -> SMB task -> MT5 (~20s) -> bridge (~45s)."
Write-Info "Today WITHOUT these tasks: bridge does NOT auto-start. Run setup before relying on reboot."
