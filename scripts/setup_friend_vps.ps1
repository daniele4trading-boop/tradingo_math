#requires -Version 5.1
<#
.SYNOPSIS
  Gamehosting / friend VPS: WireGuard client + SMB share + EA copy.

.DESCRIPTION
  Contabo = WireGuard SERVER (10.8.0.1). This host = CLIENT (default 10.8.0.2).

  Modes:
    WriteShare  - Contabo writes signals to this PC SMB share (recommended)
    PullShare   - this PC maps Contabo share and copies signals locally

  Run in Windows PowerShell as Administrator (not cmd.exe).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\setup_friend_vps.ps1 -Mode WriteShare -FriendVpnIp 10.8.0.2 -ContaboEndpoint 144.91.76.28:51820 -ContaboPublicKey "KEY=" -EaSourcePath "C:\Temp\TG_TradinGoEA.mq5"
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("WriteShare", "PullShare")]
    [string]$Mode = "WriteShare",

    [string]$FriendVpnIp = "10.8.0.2",
    [string]$ContaboVpnIp = "10.8.0.1",
    [string]$ContaboEndpoint = "",
    [string]$ContaboPublicKey = "",
    [int]$ListenPort = 51820,

    [string]$ListenShareName = "tradingo",
    [string]$ListenSharePath = "C:\TG_TradinGo_Signals",
    [string]$ListenShareUser = "TradingoShare",
    [SecureString]$ListenSharePassword,

    [string]$ContaboShareUnc = "",
    [string]$ContaboShareUser = "",
    [SecureString]$ContaboSharePassword,
    [string]$LocalSignalsPath = "C:\TG_TradinGo_Signals",
    [int]$PollSeconds = 2,

    [string]$WorkRoot = "C:\TG_FriendSetup",
    [string]$EaSourcePath = "",
    [string]$TerminalHash = "",
    [switch]$SkipWireGuardInstall,
    [switch]$SkipShare,
    [switch]$SkipEaCopy,
    [switch]$SkipFirewall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) { Write-Host "[INFO]  $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "[OK]    $Message" -ForegroundColor Green }
function Write-WarnLine([string]$Message) { Write-Host "[WARN]  $Message" -ForegroundColor Yellow }
function Write-ErrLine([string]$Message) { Write-Host "[ERROR] $Message" -ForegroundColor Red }

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script as Administrator (right-click PowerShell -> Run as administrator)."
    }
}

function Ensure-Dir([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Get-WireGuardExe {
    $candidates = @(
        "${env:ProgramFiles}\WireGuard\wireguard.exe",
        "${env:ProgramFiles(x86)}\WireGuard\wireguard.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    return $null
}

function Install-WireGuardIfNeeded {
    if ($SkipWireGuardInstall) {
        Write-WarnLine "SkipWireGuardInstall set"
        return
    }
    $wg = Get-WireGuardExe
    if ($wg) {
        Write-Ok "WireGuard already installed: $wg"
        return
    }
    Write-Info "Downloading WireGuard installer..."
    $tmp = Join-Path $env:TEMP "WireGuard-installer.exe"
    $url = "https://download.wireguard.com/windows-client/wireguard-installer.exe"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
    Write-Info "Installing WireGuard (silent)..."
    $p = Start-Process -FilePath $tmp -ArgumentList "/S" -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $null -eq (Get-WireGuardExe)) {
        throw "WireGuard installer exit $($p.ExitCode). Install manually from https://www.wireguard.com/install/ then re-run."
    }
    Start-Sleep -Seconds 2
    if (-not (Get-WireGuardExe)) {
        throw "WireGuard not found after install. Reboot and re-run, or install manually."
    }
    Write-Ok "WireGuard installed"
}

function New-WireGuardKeyPair {
    $wg = Get-WireGuardExe
    if (-not $wg) { throw "wireguard.exe not found" }
    $dir = Split-Path -Parent $wg
    $gen = Join-Path $dir "wg.exe"
    if (-not (Test-Path -LiteralPath $gen)) {
        throw "wg.exe not found next to wireguard.exe. Open WireGuard GUI once, then re-run."
    }
    $priv = (& $gen genkey).Trim()
    if ([string]::IsNullOrWhiteSpace($priv)) { throw "wg genkey failed" }
    $pub = ($priv | & $gen pubkey).Trim()
    if ([string]::IsNullOrWhiteSpace($pub)) { throw "wg pubkey failed" }
    return @{ PrivateKey = $priv; PublicKey = $pub }
}

function Resolve-TerminalCommonFiles {
    if ($TerminalHash) {
        $p = Join-Path $env:APPDATA ("MetaQuotes\Terminal\" + $TerminalHash + "\MQL5\Experts")
        if (-not (Test-Path -LiteralPath $p)) {
            throw ("TerminalHash folder not found: " + $p)
        }
        return $p
    }
    $root = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    if (-not (Test-Path -LiteralPath $root)) {
        throw "MetaQuotes Terminal folder not found under AppData. Open MT5 once, then re-run."
    }
    # Force array: a single DirectoryInfo has no .Count under Set-StrictMode
    $dirs = @(Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "MQL5\Experts") })
    if ($dirs.Count -eq 0) {
        throw "No MT5 terminal with MQL5\Experts found. Open MT5 once."
    }
    if ($dirs.Count -gt 1) {
        Write-WarnLine "Multiple MT5 terminals found. Pass -TerminalHash with one of:"
        $dirs | ForEach-Object { Write-Host ("  " + $_.Name) }
        throw "Pass -TerminalHash HASH (folder name under MetaQuotes\Terminal)."
    }
    return (Join-Path $dirs[0].FullName "MQL5\Experts")
}

function Set-ShareAcl([string]$Path, [string]$UserName) {
    $acl = Get-Acl -LiteralPath $Path
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $UserName, "Modify", "ContainerInherit,ObjectInherit", "None", "Allow"
    )
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Ensure-LocalUser([string]$UserName, [SecureString]$Password) {
    $existing = Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Ok ("Local user exists: " + $UserName)
        if ($Password) {
            Set-LocalUser -Name $UserName -Password $Password
            Write-Info "Password updated for share user"
        }
        return
    }
    if (-not $Password) {
        $Password = Read-Host ("Create password for local user " + $UserName) -AsSecureString
    }
    New-LocalUser -Name $UserName -Password $Password -PasswordNeverExpires -UserMayNotChangePassword -AccountNeverExpires |
        Out-Null
    Write-Ok ("Created local user: " + $UserName)
}

function Ensure-SmbShare {
    param(
        [string]$Name,
        [string]$Path,
        [string]$UserName,
        [SecureString]$Password
    )
    Ensure-Dir $Path
    Ensure-LocalUser -UserName $UserName -Password $Password
    Set-ShareAcl -Path $Path -UserName $UserName

    $share = Get-SmbShare -Name $Name -ErrorAction SilentlyContinue
    if (-not $share) {
        if ($PSCmdlet.ShouldProcess($Name, "New-SmbShare")) {
            New-SmbShare -Name $Name -Path $Path -FullAccess $UserName -Description "TG TradinGo signals" | Out-Null
            Write-Ok ("SMB share created: \\" + $env:COMPUTERNAME + "\" + $Name + " -> " + $Path)
        }
    }
    else {
        Write-Ok ("SMB share already exists: " + $Name)
        Grant-SmbShareAccess -Name $Name -AccountName $UserName -AccessRight Full -Force -ErrorAction SilentlyContinue | Out-Null
    }

    if (-not $SkipFirewall) {
        $ruleName = "TG-TradinGo-SMB-445"
        if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 |
                Out-Null
            Write-Ok "Firewall rule: TCP 445 inbound"
        }
    }
}

function Write-ClientConf {
    param(
        [string]$OutConf,
        [string]$PrivateKey,
        [string]$AddressCidr,
        [string]$PeerPublicKey,
        [string]$Endpoint,
        [string]$AllowedIps,
        [int]$PersistentKeepalive = 25
    )
    if ([string]::IsNullOrWhiteSpace($Endpoint)) {
        throw "Pass -ContaboEndpoint HOST:PORT (example: 144.91.76.28:51820)"
    }
    if ([string]::IsNullOrWhiteSpace($PeerPublicKey)) {
        throw "Pass -ContaboPublicKey with Contabo WireGuard server public key"
    }
    $lines = @(
        "[Interface]"
        ("PrivateKey = " + $PrivateKey)
        ("Address = " + $AddressCidr)
        ("ListenPort = " + $ListenPort)
        ""
        "[Peer]"
        ("PublicKey = " + $PeerPublicKey)
        ("Endpoint = " + $Endpoint)
        ("AllowedIPs = " + $AllowedIps)
        ("PersistentKeepalive = " + $PersistentKeepalive)
    )
    $text = ($lines -join "`r`n") + "`r`n"
    if ($PSCmdlet.ShouldProcess($OutConf, "Write WireGuard client config")) {
        Set-Content -LiteralPath $OutConf -Value $text -Encoding Ascii
        Write-Ok ("Wrote " + $OutConf)
    }
    else {
        Write-Info ("WhatIf would write " + $OutConf)
    }
}

function Convert-SecureStringToPlain([SecureString]$Secure) {
    if (-not $Secure) { return "" }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Install-PullJob {
    param(
        [string]$Unc,
        [string]$User,
        [SecureString]$Password,
        [string]$Dest,
        [int]$Seconds
    )
    if ([string]::IsNullOrWhiteSpace($Unc)) {
        throw 'PullShare mode requires -ContaboShareUnc (example: \\10.8.0.1\tradingo)'
    }
    Ensure-Dir $Dest
    $scripts = Join-Path $WorkRoot "scripts"
    Ensure-Dir $scripts
    $pullPs1 = Join-Path $scripts "pull_signals.ps1"

    $plainPass = Convert-SecureStringToPlain $Password
    $b64 = ""
    if ($plainPass) {
        $b64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($plainPass))
    }

    # Build child script as line array (no here-strings) for Windows PowerShell 5.1 safety
    $pullLines = @(
        "param("
        ("    [string]`$Unc = '" + $Unc.Replace("'", "''") + "',")
        ("    [string]`$User = '" + $User.Replace("'", "''") + "',")
        ("    [string]`$PasswordB64 = '" + $b64 + "',")
        ("    [string]`$Dest = '" + $Dest.Replace("'", "''") + "'")
        ")"
        "`$ErrorActionPreference = 'SilentlyContinue'"
        "if (`$PasswordB64 -and `$User) {"
        "    `$plain = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String(`$PasswordB64))"
        "    `$hostOnly = (`$Unc -replace '^\\\\\\\\','').Split('\')[0]"
        "    cmdkey /add:`$hostOnly /user:`$User /pass:`$plain | Out-Null"
        "}"
        "if (-not (Test-Path -LiteralPath `$Dest)) { New-Item -ItemType Directory -Path `$Dest -Force | Out-Null }"
        "if (Test-Path -LiteralPath `$Unc) {"
        "    Copy-Item -Path (Join-Path `$Unc '*') -Destination `$Dest -Force -ErrorAction SilentlyContinue"
        "}"
    )
    Set-Content -LiteralPath $pullPs1 -Value (($pullLines -join "`r`n") + "`r`n") -Encoding Ascii
    Write-Ok ("Wrote pull script: " + $pullPs1)

    $taskName = "TG_TradinGo_PullSignals"
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$pullPs1`""
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Seconds $Seconds) -RepetitionDuration ([TimeSpan]::MaxValue)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Write-Ok ("Scheduled task: " + $taskName + " every " + $Seconds + "s")
}

function Copy-EaToTerminal {
    if ($SkipEaCopy) {
        Write-WarnLine "SkipEaCopy set"
        return
    }
    if ([string]::IsNullOrWhiteSpace($EaSourcePath)) {
        Write-WarnLine "No -EaSourcePath: skip EA copy. Copy TG_TradinGoEA.mq5 manually into MQL5\Experts."
        return
    }
    if (-not (Test-Path -LiteralPath $EaSourcePath)) {
        throw ("EaSourcePath not found: " + $EaSourcePath)
    }
    $experts = Resolve-TerminalCommonFiles
    $dest = Join-Path $experts (Split-Path -Leaf $EaSourcePath)
    Copy-Item -LiteralPath $EaSourcePath -Destination $dest -Force
    Write-Ok ("EA copied to: " + $dest)
    Write-Info "Open MetaEditor, compile with F7, attach EA on one chart (AutoTrading ON)."
}

# --- main ---
Assert-Admin
Ensure-Dir $WorkRoot
Ensure-Dir (Join-Path $WorkRoot "wireguard")
Ensure-Dir (Join-Path $WorkRoot "keys")

Write-Host ""
Write-Host "=== TG TradinGo friend VPS setup ===" -ForegroundColor Magenta
Write-Host ("Mode          : " + $Mode)
Write-Host ("Friend VPN IP : " + $FriendVpnIp)
Write-Host ("Contabo VPN IP: " + $ContaboVpnIp)
Write-Host ("Endpoint      : " + $ContaboEndpoint)
Write-Host ""

Install-WireGuardIfNeeded

$keysDir = Join-Path $WorkRoot "keys"
$privFile = Join-Path $keysDir "friend_private.key"
$pubFile = Join-Path $keysDir "friend_public.key"

if ((Test-Path -LiteralPath $privFile) -and (Test-Path -LiteralPath $pubFile)) {
    $priv = (Get-Content -LiteralPath $privFile -Raw).Trim()
    $pub = (Get-Content -LiteralPath $pubFile -Raw).Trim()
    Write-Ok "Reusing existing WireGuard keypair"
}
else {
    $pair = New-WireGuardKeyPair
    $priv = $pair.PrivateKey
    $pub = $pair.PublicKey
    Set-Content -LiteralPath $privFile -Value $priv -Encoding Ascii
    Set-Content -LiteralPath $pubFile -Value $pub -Encoding Ascii
    Write-Ok ("Generated keys under " + $keysDir)
}

Write-Host ""
Write-Host "=== FRIEND PUBLIC KEY (send to Contabo admin) ===" -ForegroundColor Magenta
Write-Host $pub -ForegroundColor Yellow
Write-Host ""

$confPath = Join-Path $WorkRoot "wireguard\tg-friend.conf"
# Client tunnels only to Contabo VPN IP (not full tunnel)
Write-ClientConf -OutConf $confPath -PrivateKey $priv -AddressCidr ($FriendVpnIp + "/32") `
    -PeerPublicKey $ContaboPublicKey -Endpoint $ContaboEndpoint -AllowedIps ($ContaboVpnIp + "/32")

if ($Mode -eq "WriteShare" -and -not $SkipShare) {
    Ensure-SmbShare -Name $ListenShareName -Path $ListenSharePath -UserName $ListenShareUser -Password $ListenSharePassword
    Write-Info ("Contabo must write to: \\" + $FriendVpnIp + "\" + $ListenShareName)
    Write-Info ("Local folder: " + $ListenSharePath)
    Write-Info ("Share user: " + $ListenShareUser + " (create/password prompted if new)")
}
elseif ($Mode -eq "PullShare" -and -not $SkipShare) {
    Install-PullJob -Unc $ContaboShareUnc -User $ContaboShareUser -Password $ContaboSharePassword -Dest $LocalSignalsPath -Seconds $PollSeconds
}

Copy-EaToTerminal

$nextPath = Join-Path $WorkRoot "NEXT_STEPS.txt"
$uncExample = "\\\\" + $FriendVpnIp + "\\" + $ListenShareName
$nextLines = @(
    "NEXT STEPS"
    ""
    "1) Activate WireGuard tunnel: import " + $WorkRoot + "\wireguard\tg-friend.conf in WireGuard GUI, Activate."
    "2) On Contabo: add peer PublicKey, AllowedIPs=" + $FriendVpnIp + "/32"
    "3) ping " + $ContaboVpnIp
    "4) Compile EA (F7), attach on one chart, AutoTrading ON"
    "5) Contabo tradingo_config.json mt5_instances (WriteShare):"
    "     signals_path = " + $uncExample
    "   Then restart bridge."
    "6) EA InpSignalsPath should be the local share folder relative path or absolute, e.g. " + $ListenSharePath + "\"
    ""
    "Friend PublicKey:"
    $pub
)
Set-Content -LiteralPath $nextPath -Value (($nextLines -join "`r`n") + "`r`n") -Encoding Ascii

Write-Host ""
Write-Ok ("Setup finished. See " + $nextPath)
Write-WarnLine "Do NOT commit private keys or share passwords to git."
