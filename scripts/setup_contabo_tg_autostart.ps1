#requires -Version 5.1
<#
.SYNOPSIS
  Contabo: disable old trading autostart + register TG TradinGo reboot stack.

.DESCRIPTION
  Keeps / creates:
    - Tailscale (service — already)
    - TG_TradinGo_EnsureFriendSmb (SMB remap — already if registered)
    - TG_TradinGo_BridgeAtLogon  (start_tradingo.bat after delay)
    - TG_TradinGo_VantageMT5AtLogon (optional path to terminal64.exe)

  Optionally disables Scheduled Tasks matching -DisableNamePatterns.

.EXAMPLE
  # 1) Inventory first (see list_contabo_autostart.ps1), then:
  powershell -ExecutionPolicy Bypass -File .\setup_contabo_tg_autostart.ps1 `
    -VantageTerminalExe "C:\Program Files\Vantage International MT5\terminal64.exe" `
    -DisableNamePatterns @('StatArb','quantlab','old_bridge','module')
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$BridgeBat = "C:\TG_TradinGo\start_tradingo.bat",
    [string]$VantageTerminalExe = "",
    [string]$XmTerminalExe = "",
    [int]$BridgeDelaySec = 45,
    [int]$Mt5DelaySec = 20,
    [string[]]$DisableNamePatterns = @(),
    [switch]$DisableXmAutostart,
    [switch]$RegisterBridge,
    [switch]$RegisterVantage,
    [switch]$RegisterXm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Write-Ok([string]$m) { Write-Host "[OK]   $m" -ForegroundColor Green }
function Write-WarnLine([string]$m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }

# --- disable old tasks by name pattern ---
if ($DisableNamePatterns.Count -gt 0) {
    $tasks = Get-ScheduledTask -ErrorAction SilentlyContinue
    foreach ($t in $tasks) {
        $hit = $false
        foreach ($pat in $DisableNamePatterns) {
            if ($t.TaskName -like "*$pat*" -or $t.TaskPath -like "*$pat*") { $hit = $true; break }
        }
        # never disable our TG tasks
        if ($t.TaskName -like 'TG_TradinGo_*') { continue }
        if (-not $hit) { continue }
        if ($PSCmdlet.ShouldProcess($t.TaskName, "Disable Scheduled Task")) {
            Disable-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction SilentlyContinue | Out-Null
            Write-Ok "Disabled task: $($t.TaskPath)$($t.TaskName)"
        }
    }
}

function Register-LogonCmdTask {
    param(
        [string]$TaskName,
        [string]$Command,
        [string]$Arguments,
        [int]$DelaySec
    )
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    $arg = $Arguments
    if ($DelaySec -gt 0) {
        # cmd /c timeout then start — works without PowerShell profile issues
        $arg = "/c timeout /t $DelaySec /nobreak >nul & `"$Command`" $Arguments"
        $Command = "$env:SystemRoot\System32\cmd.exe"
        # If Arguments already empty and Command is a bat:
        if ([string]::IsNullOrWhiteSpace($Arguments)) {
            $arg = "/c timeout /t $DelaySec /nobreak >nul & call `"$Command`""
            # Wait — Command was overwritten. Fix properly:
        }
    }
}

# Simpler registration helpers
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

    if ($DelaySec -gt 0) {
        $inner = if ($ExeArgs) { "`"$ExePath`" $ExeArgs" } else { "`"$ExePath`"" }
        $cmdArgs = "/c timeout /t $DelaySec /nobreak >nul & start `"`" $inner"
        $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $cmdArgs -WorkingDirectory $(if ($WorkDir) { $WorkDir } else { Split-Path $ExePath })
    }
    else {
        $action = New-ScheduledTaskAction -Execute $ExePath -Argument $ExeArgs -WorkingDirectory $(if ($WorkDir) { $WorkDir } else { Split-Path $ExePath })
    }
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Ok "Registered $TaskName (delay=${DelaySec}s)"
}

if ($RegisterBridge) {
    if (-not (Test-Path -LiteralPath $BridgeBat)) {
        throw "Bridge bat missing: $BridgeBat"
    }
    New-TgLogonTask -TaskName "TG_TradinGo_BridgeAtLogon" -ExePath $BridgeBat -DelaySec $BridgeDelaySec -WorkDir "C:\TG_TradinGo"
}

if ($RegisterVantage) {
    if ([string]::IsNullOrWhiteSpace($VantageTerminalExe)) {
        throw "Pass -VantageTerminalExe path to terminal64.exe"
    }
    New-TgLogonTask -TaskName "TG_TradinGo_VantageMT5AtLogon" -ExePath $VantageTerminalExe -DelaySec $Mt5DelaySec
}

if ($RegisterXm) {
    if ([string]::IsNullOrWhiteSpace($XmTerminalExe)) {
        throw "Pass -XmTerminalExe path to terminal64.exe"
    }
    New-TgLogonTask -TaskName "TG_TradinGo_XmMT5AtLogon" -ExePath $XmTerminalExe -DelaySec $Mt5DelaySec
}

# Remove XM from Startup folder if requested
if ($DisableXmAutostart) {
    $startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    Get-ChildItem $startup -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match 'XM|xm|MetaTrader'
    } | ForEach-Object {
        if ($PSCmdlet.ShouldProcess($_.FullName, "Remove Startup shortcut")) {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Ok "Removed Startup shortcut: $($_.Name)"
        }
    }
}

Write-Host ""
Write-Info "Current TG_* tasks:"
Get-ScheduledTask | Where-Object { $_.TaskName -like 'TG_TradinGo_*' } |
    Format-Table TaskName, State, TaskPath -AutoSize

Write-Host ""
Write-WarnLine "MT5 must have the chart+EA saved in the default profile (File -> Open Account / charts stay with EA)."
Write-WarnLine "AutoTrading ON is required after terminal start (MT5 usually restores it if left ON)."
Write-Info "Recommended order after reboot: Tailscale service -> logon -> SMB task -> Vantage MT5 -> bridge (+45s)."
