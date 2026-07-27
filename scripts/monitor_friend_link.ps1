#requires -Version 5.1
<#
.SYNOPSIS
  Monitor Contabo <-> Gamehosting link (Tailscale + SMB + bridge heartbeat).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\monitor_friend_link.ps1
  powershell -ExecutionPolicy Bypass -File .\monitor_friend_link.ps1 -LoopSeconds 30
#>
[CmdletBinding()]
param(
    [string]$FriendTailscaleIp = "100.74.9.8",
    [string]$ShareUnc = "\\100.74.9.8\tradingo",
    [string]$LocalHeartbeat = "C:\TG_TradinGo\signals\tradingo_heartbeat.json",
    [string]$RemoteHeartbeat = "\\100.74.9.8\tradingo\tradingo_heartbeat.json",
    [int]$MaxHeartbeatAgeSec = 120,
    [int]$LoopSeconds = 0
)

function Write-Ok([string]$m) { Write-Host "[OK]   $m" -ForegroundColor Green }
function Write-Bad([string]$m) { Write-Host "[FAIL] $m" -ForegroundColor Red }
function Write-Info([string]$m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }

function Get-HeartbeatAgeSec([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $j = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json
        $ts = [datetime]::Parse($j.ts_utc, $null, [System.Globalization.DateTimeStyles]::AssumeUniversal).ToUniversalTime()
        return [int]([datetime]::UtcNow - $ts).TotalSeconds
    }
    catch {
        return $null
    }
}

function Invoke-Check {
    $failed = 0
    Write-Host ""
    Write-Host ("=== Friend link check " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ===")

    $tsExe = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path -LiteralPath $tsExe) {
        $st = & $tsExe status 2>&1 | Out-String
        if ($st -match [regex]::Escape($FriendTailscaleIp)) {
            Write-Ok "Tailscale sees peer $FriendTailscaleIp"
        }
        else {
            Write-Bad "Tailscale status missing peer $FriendTailscaleIp"
            $failed++
        }
    }
    else {
        Write-Bad "tailscale.exe not found"
        $failed++
    }

    $ping = Test-Connection -ComputerName $FriendTailscaleIp -Count 2 -Quiet -ErrorAction SilentlyContinue
    if ($ping) { Write-Ok "ping $FriendTailscaleIp" }
    else { Write-Bad "ping $FriendTailscaleIp failed"; $failed++ }

    if (Test-Path -LiteralPath $ShareUnc) {
        Write-Ok "SMB share reachable: $ShareUnc"
    }
    else {
        Write-Bad "SMB share NOT reachable: $ShareUnc (net use / Tailscale / share service?)"
        $failed++
    }

    $ageLocal = Get-HeartbeatAgeSec $LocalHeartbeat
    if ($null -eq $ageLocal) {
        Write-Bad "Local heartbeat missing/unreadable: $LocalHeartbeat"
        $failed++
    }
    elseif ($ageLocal -gt $MaxHeartbeatAgeSec) {
        Write-Bad "Local heartbeat stale age=${ageLocal}s > $MaxHeartbeatAgeSec (bridge down?)"
        $failed++
    }
    else {
        Write-Ok "Local heartbeat age=${ageLocal}s"
    }

    $ageRemote = Get-HeartbeatAgeSec $RemoteHeartbeat
    if ($null -eq $ageRemote) {
        Write-Bad "Remote heartbeat missing/unreadable: $RemoteHeartbeat"
        $failed++
    }
    elseif ($ageRemote -gt $MaxHeartbeatAgeSec) {
        Write-Bad "Remote heartbeat stale age=${ageRemote}s > $MaxHeartbeatAgeSec"
        $failed++
    }
    else {
        Write-Ok "Remote heartbeat age=${ageRemote}s"
    }

    if ($failed -eq 0) {
        Write-Ok "Ponte Contabo <-> Gamehosting OK"
        return 0
    }
    Write-Bad "Ponte con problemi ($failed check falliti)"
    return 1
}

do {
    $code = Invoke-Check
    if ($LoopSeconds -le 0) { exit $code }
    Start-Sleep -Seconds $LoopSeconds
} while ($true)
