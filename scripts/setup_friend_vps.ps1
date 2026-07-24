# Setup TG TradinGo su VPS amico (Windows)
#
# Configura (opzionale) WireGuard client, cartella segnali, share SMB per
# Contabo, copia EA in MQL5\Experts, junction per variante A.
#
# Esegui come Administrator sulla VPS amico:
#   powershell -ExecutionPolicy Bypass -File .\setup_friend_vps.ps1 -Mode WriteShare
#
# Varianti:
#   WriteShare (B, consigliata) — Contabo scrive via VPN su \\amico\tradingo
#   ReadShare  (A)              — amico legge \\Contabo\TGSignals via junction
#
# ASCII-only for Windows PowerShell 5.1 compatibility.

[CmdletBinding()]
param(
    [ValidateSet("WriteShare", "ReadShare", "EaOnly", "Status")]
    [string]$Mode = "WriteShare",

    [string]$FriendVpnIp = "10.8.0.2",
    [string]$ContaboVpnIp = "10.8.0.1",
    [string]$ContaboEndpoint = "144.91.76.28:51820",
    [string]$ContaboPublicKey = "",
    [string]$FriendPrivateKey = "",
    [string]$ListenShareName = "tradingo",
    [string]$ContaboShareUnc = "\\10.8.0.1\TGSignals",

    # Path to TG_TradinGoEA.mq5 (USB / download / repo copy)
    [string]$EaSourcePath = "",

    # Optional: force terminal hash under %APPDATA%\MetaQuotes\Terminal\<HASH>
    [string]$TerminalHash = "",

    [string]$WorkRoot = "C:\TG_TradinGo_Friend",
    [switch]$SkipWireGuard,
    [switch]$SkipFirewall,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    OK  $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "    !!  $Message" -ForegroundColor Yellow
}

function Write-Info([string]$Message) {
    Write-Host "    --  $Message"
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Mt5Terminals {
    $root = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    if (-not (Test-Path $root)) { return @() }
    Get-ChildItem $root -Directory | ForEach-Object {
        $hash = $_.Name
        # Skip Common / Community helpers if present as odd names; keep 32-hex hashes
        if ($hash -notmatch '^[A-F0-9]{32}$') { return }
        [PSCustomObject]@{
            Hash        = $hash
            Root        = $_.FullName
            ExpertsPath = (Join-Path $_.FullName "MQL5\Experts")
            FilesPath   = (Join-Path $_.FullName "MQL5\Files")
        }
    }
}

function Resolve-Terminal {
    param([string]$Hash)
    $all = @(Get-Mt5Terminals)
    if ($Hash) {
        $t = $all | Where-Object { $_.Hash -eq $Hash } | Select-Object -First 1
        if (-not $t) { throw "Terminal hash not found: $Hash" }
        return $t
    }
    if ($all.Count -eq 0) {
        Write-Warn "No MT5 terminal under $env:APPDATA\MetaQuotes\Terminal"
        Write-Info "Install/open MetaTrader 5 once, then re-run."
        return $null
    }
    if ($all.Count -gt 1) {
        Write-Warn "Multiple MT5 terminals found — pick one with -TerminalHash"
        $all | Format-Table Hash, ExpertsPath -AutoSize | Out-Host
        throw "Pass -TerminalHash <HASH>"
    }
    return $all[0]
}

function Ensure-Dir([string]$Path) {
    if ($WhatIf) {
        Write-Info "WhatIf: mkdir $Path"
        return
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Get-WgExe {
    $candidates = @(
        "${env:ProgramFiles}\WireGuard\wireguard.exe",
        "${env:ProgramFiles(x86)}\WireGuard\wireguard.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function New-WgKeyPair {
    $wg = Get-WgExe
    if (-not $wg) { return $null }
    $dir = Split-Path $wg -Parent
    $wgTool = Join-Path $dir "wg.exe"
    if (-not (Test-Path $wgTool)) { return $null }
    $priv = (& $wgTool genkey).Trim()
    $pub = ($priv | & $wgTool pubkey).Trim()
    return @{ Private = $priv; Public = $pub }
}

function Install-WireGuardClient {
    param(
        [string]$PrivateKey,
        [string]$AddressCidr,
        [string]$PeerPublicKey,
        [string]$Endpoint,
        [string]$OutConf
    )
    if (-not $PeerPublicKey) {
        Write-Warn "ContaboPublicKey missing — writing PLACEHOLDER conf; edit before Activate."
        $PeerPublicKey = "REPLACE_WITH_CONTABO_PUBLIC_KEY"
    }
    if (-not $PrivateKey) {
        $pair = New-WgKeyPair
        if ($pair) {
            $PrivateKey = $pair.Private
            Write-Ok "Generated friend keypair. PublicKey (give to Contabo peer):"
            Write-Host "         $($pair.Public)" -ForegroundColor Magenta
        } else {
            $PrivateKey = "REPLACE_WITH_FRIEND_PRIVATE_KEY"
            Write-Warn "WireGuard wg.exe not found — conf uses placeholders."
        }
    }

    $conf = @"
[Interface]
PrivateKey = $PrivateKey
Address = $AddressCidr
DNS = 1.1.1.1

[Peer]
PublicKey = $PeerPublicKey
Endpoint = $Endpoint
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25
"@
    if ($WhatIf) {
        Write-Info "WhatIf: write $OutConf"
        return
    }
    Ensure-Dir (Split-Path $OutConf -Parent)
    Set-Content -Path $OutConf -Value $conf -Encoding Ascii
    Write-Ok "WireGuard conf: $OutConf"
    Write-Info "Import in WireGuard GUI (Import tunnel(s) from file) and Activate."
    Write-Info "On Contabo add Peer PublicKey + AllowedIPs = $FriendVpnIp/32"
}

function Test-VpnPing([string]$Ip) {
    Write-Step "Ping Contabo VPN $Ip"
    $r = Test-Connection -ComputerName $Ip -Count 4 -ErrorAction SilentlyContinue
    if (-not $r) {
        Write-Warn "Ping failed — activate WireGuard and re-run -Mode Status"
        return
    }
    $avg = ($r | Measure-Object -Property ResponseTime -Average).Average
    Write-Ok ("VPN RTT avg ~{0:n0} ms (min={1} max={2})" -f $avg, `
        ($r | Measure-Object ResponseTime -Minimum).Minimum, `
        ($r | Measure-Object ResponseTime -Maximum).Maximum)
}

function Install-Ea {
    param([string]$Source, [string]$ExpertsPath)
    if (-not $Source) {
        Write-Warn "No -EaSourcePath — skip EA copy. Place TG_TradinGoEA.mq5 manually in:"
        Write-Info $ExpertsPath
        return
    }
    if (-not (Test-Path $Source)) {
        throw "EA source not found: $Source"
    }
    Ensure-Dir $ExpertsPath
    $dest = Join-Path $ExpertsPath "TG_TradinGoEA.mq5"
    if ($WhatIf) {
        Write-Info "WhatIf: copy $Source -> $dest"
        return
    }
    Copy-Item -Path $Source -Destination $dest -Force
    Write-Ok "EA copied to $dest"
    Write-Info "Open MetaEditor -> F7 compile -> attach EA on ONE chart (AutoTrading ON)"
}

function Ensure-WriteShare {
    param(
        [string]$LocalSignalsDir,
        [string]$ShareName,
        [string]$FilesTradingoPath
    )
    Ensure-Dir $LocalSignalsDir

    # Prefer local folder under WorkRoot, then junction into MQL5\Files\tradingo
    # so Contabo writes UNC and EA reads local relative path.
    if (-not $WhatIf) {
        if (Test-Path $FilesTradingoPath) {
            $item = Get-Item $FilesTradingoPath -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                Write-Info "Junction already present: $FilesTradingoPath"
            } else {
                # If non-empty real dir, leave it; else replace with junction
                $kids = @(Get-ChildItem $FilesTradingoPath -Force -ErrorAction SilentlyContinue)
                if ($kids.Count -eq 0) {
                    Remove-Item $FilesTradingoPath -Force
                    cmd /c mklink /J "$FilesTradingoPath" "$LocalSignalsDir" | Out-Null
                    Write-Ok "Junction $FilesTradingoPath -> $LocalSignalsDir"
                } else {
                    Write-Warn "Files\tradingo exists with content — using it as signals dir"
                    $LocalSignalsDir = $FilesTradingoPath
                }
            }
        } else {
            Ensure-Dir (Split-Path $FilesTradingoPath -Parent)
            cmd /c mklink /J "$FilesTradingoPath" "$LocalSignalsDir" | Out-Null
            Write-Ok "Junction $FilesTradingoPath -> $LocalSignalsDir"
        }
    }

    # SMB share for Contabo bridge write
    $existing = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue
    if ($WhatIf) {
        Write-Info "WhatIf: New-SmbShare $ShareName -> $LocalSignalsDir"
    } elseif ($existing) {
        Write-Info "Share $ShareName already exists -> $($existing.Path)"
    } else {
        New-SmbShare -Name $ShareName -Path $LocalSignalsDir -FullAccess "Everyone" | Out-Null
        Write-Ok "SMB share \\$env:COMPUTERNAME\$ShareName -> $LocalSignalsDir"
        Write-Warn "Tighten ACL later (not Everyone). Contabo path: \\$FriendVpnIp\$ShareName"
    }

    if (-not $SkipFirewall -and -not $WhatIf) {
        # Prefer blocking public SMB; allow local/private. WireGuard usually private.
        Write-Info "Ensure Windows Firewall does NOT expose SMB to the public Internet."
        Write-Info "SMB should only work over WireGuard (10.8.0.0/24)."
    }

    # Seed NONE json stubs
    $channels = @("gold", "forex", "oro", "stark", "ivan")
    foreach ($ch in $channels) {
        $f = Join-Path $LocalSignalsDir ("signal_ch_{0}.json" -f $ch)
        if (-not (Test-Path $f) -and -not $WhatIf) {
            Set-Content -Path $f -Value "{`n  `"action`": `"NONE`"`n}`n" -Encoding Ascii
        }
    }
    Write-Ok "Signal stubs ready in $LocalSignalsDir"
}

function Ensure-ReadShareJunction {
    param(
        [string]$ContaboUnc,
        [string]$FilesTradingoPath
    )
    Write-Step "Variant A: junction to Contabo share $ContaboUnc"
    if (-not (Test-Path $ContaboUnc)) {
        Write-Warn "Cannot reach $ContaboUnc yet (VPN/share). Junction will still be created."
    }
    Ensure-Dir (Split-Path $FilesTradingoPath -Parent)
    if ($WhatIf) {
        Write-Info "WhatIf: mklink /J $FilesTradingoPath $ContaboUnc"
        return
    }
    if (Test-Path $FilesTradingoPath) {
        $item = Get-Item $FilesTradingoPath -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Write-Info "Junction already exists: $FilesTradingoPath"
            return
        }
        Remove-Item $FilesTradingoPath -Recurse -Force
    }
    cmd /c mklink /J "$FilesTradingoPath" "$ContaboUnc" | Out-Null
    Write-Ok "Junction $FilesTradingoPath -> $ContaboUnc"
}

function Write-EaParamsFile {
    param(
        [string]$OutDir,
        [string]$ModeName
    )
    $path = Join-Path $OutDir "EA_PARAMS.txt"
    $body = @"
TG TradinGo EA — friend VPS params ($ModeName)

InpUseAbsolutePath = false
InpSignalsPath     = tradingo\
InpChannels        = gold,forex,oro,stark,ivan
InpLotMultiplier   = 0.5   (start low on demo)
InpPollMs          = 500
InpIgnoreExistingOnInit = true

After compile (F7), log must show: EA v2.09 started
Attach on ONE chart only. AutoTrading ON.

Contabo bridge (variant WriteShare / B) add to mt5_instances:
  "signals_path": "\\\\$FriendVpnIp\\$ListenShareName"

Latency tip: EA poll ($InpPollMs) dominates; VPN write is usually tens of ms.
"@
    if ($WhatIf) {
        Write-Info "WhatIf: write $path"
        return
    }
    Ensure-Dir $OutDir
    Set-Content -Path $path -Value $body -Encoding Ascii
    Write-Ok "Params cheat-sheet: $path"
}

function Write-LagProbe {
    param([string]$OutDir, [string]$ProbePath)
    $script = Join-Path $OutDir "measure_signal_lag.ps1"
    $content = @"
# Poll a signal JSON and print lag vs bridge timestamp (UTC)
param([string]`$Path = "$ProbePath", [int]`$SleepMs = 200)
`$prev = ""
Write-Host "Watching `$Path (Ctrl+C to stop)"
while (`$true) {
  if (Test-Path `$Path) {
    `$raw = Get-Content `$Path -Raw -ErrorAction SilentlyContinue
    if (`$raw -and `$raw -ne `$prev -and `$raw -match '"timestamp"\s*:\s*"([^"]+)"') {
      `$ts = [datetime]::Parse(`$Matches[1]).ToUniversalTime()
      `$now = [datetime]::UtcNow
      `$ms = (`$now - `$ts).TotalMilliseconds
      `$act = if (`$raw -match '"action"\s*:\s*"([^"]+)"') { `$Matches[1] } else { "?" }
      Write-Host ("{0:u}  lag={1,6:n0} ms  action={2}" -f `$now, `$ms, `$act)
      `$prev = `$raw
    }
  }
  Start-Sleep -Milliseconds `$SleepMs
}
"@
    if ($WhatIf) {
        Write-Info "WhatIf: write $script"
        return
    }
    Set-Content -Path $script -Value $content -Encoding Ascii
    Write-Ok "Lag probe: $script"
}

function Show-Status {
    Write-Step "Status"
    $wg = Get-WgExe
    if ($wg) { Write-Ok "WireGuard installed: $wg" } else { Write-Warn "WireGuard not installed" }

    Test-VpnPing $ContaboVpnIp

    $terms = @(Get-Mt5Terminals)
    if ($terms.Count -eq 0) {
        Write-Warn "No MT5 terminals found"
    } else {
        Write-Ok ("MT5 terminals: {0}" -f $terms.Count)
        foreach ($t in $terms) {
            $ea = Get-ChildItem $t.ExpertsPath -Filter "*TradinGo*" -ErrorAction SilentlyContinue
            $tr = Join-Path $t.FilesPath "tradingo"
            $sig = @()
            if (Test-Path $tr) {
                $sig = Get-ChildItem $tr -Filter "signal_ch_*.json" -ErrorAction SilentlyContinue
            }
            Write-Info ("{0}  EA=[{1}]  tradingo_json={2}" -f $t.Hash, `
                (($ea | ForEach-Object Name) -join ","), $sig.Count)
        }
    }

    $share = Get-SmbShare -Name $ListenShareName -ErrorAction SilentlyContinue
    if ($share) {
        Write-Ok "Share $ListenShareName -> $($share.Path)"
    } else {
        Write-Info "Share $ListenShareName not present (ok for ReadShare/EaOnly)"
    }
}

# --- main ---

Write-Host "TG TradinGo friend VPS setup" -ForegroundColor Cyan
Write-Host "Mode=$Mode  FriendVpn=$FriendVpnIp  ContaboVpn=$ContaboVpnIp"

if ($Mode -ne "Status" -and -not (Test-IsAdmin)) {
    throw "Run elevated (Administrator) for share/firewall/junction steps."
}

Ensure-Dir $WorkRoot
$confDir = Join-Path $WorkRoot "wireguard"
$localSignals = Join-Path $WorkRoot "signals"

if ($Mode -eq "Status") {
    Show-Status
    exit 0
}

$terminal = Resolve-Terminal -Hash $TerminalHash

if (-not $SkipWireGuard -and $Mode -ne "EaOnly") {
    Write-Step "WireGuard client conf"
    $wgExe = Get-WgExe
    if (-not $wgExe) {
        Write-Warn "Install WireGuard for Windows first:"
        Write-Info "https://www.wireguard.com/install/"
        Write-Info "Then re-run this script."
    }
    $confPath = Join-Path $confDir "tg-friend.conf"
    Install-WireGuardClient `
        -PrivateKey $FriendPrivateKey `
        -AddressCidr "$FriendVpnIp/24" `
        -PeerPublicKey $ContaboPublicKey `
        -Endpoint $ContaboEndpoint `
        -OutConf $confPath
}

if ($terminal) {
    Write-Step "MT5 terminal $($terminal.Hash)"
    Write-Info $terminal.Root
    Install-Ea -Source $EaSourcePath -ExpertsPath $terminal.ExpertsPath
    $filesTradingo = Join-Path $terminal.FilesPath "tradingo"

    if ($Mode -eq "WriteShare") {
        Write-Step "Variant B: local signals + SMB write share for Contabo"
        Ensure-WriteShare -LocalSignalsDir $localSignals `
            -ShareName $ListenShareName `
            -FilesTradingoPath $filesTradingo
        Write-LagProbe -OutDir $WorkRoot `
            -ProbePath (Join-Path $localSignals "signal_ch_oro.json")
    } elseif ($Mode -eq "ReadShare") {
        Ensure-ReadShareJunction -ContaboUnc $ContaboShareUnc `
            -FilesTradingoPath $filesTradingo
        Write-LagProbe -OutDir $WorkRoot `
            -ProbePath (Join-Path $filesTradingo "signal_ch_oro.json")
    }

    Write-EaParamsFile -OutDir $WorkRoot -ModeName $Mode
}

Write-Step "Done — next steps"
Write-Host @"

1) Activate WireGuard tunnel (import $WorkRoot\wireguard\tg-friend.conf)
2) On Contabo: add peer PublicKey, AllowedIPs=$FriendVpnIp/32
3) ping $ContaboVpnIp
4) Compile EA (F7), attach on one chart, AutoTrading ON
5) Contabo tradingo_config.json mt5_instances (WriteShare):
     "signals_path": "\\\\$FriendVpnIp\\$ListenShareName"
6) Measure lag:
     powershell -ExecutionPolicy Bypass -File $WorkRoot\measure_signal_lag.ps1
7) Re-check anytime:
     powershell -ExecutionPolicy Bypass -File $($MyInvocation.MyCommand.Path) -Mode Status

Expected lag (WriteShare): VPN RTT + write (~10-80 ms) + EA poll (upto InpPollMs, default 500).
Typical end-to-end ~0.2-1.0 s; if many seconds, VPN/SMB is unhealthy.

"@
