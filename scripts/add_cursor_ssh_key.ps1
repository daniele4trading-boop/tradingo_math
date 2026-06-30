# Aggiunge la chiave pubblica Cursor Cloud Agent per SSH sulla VPS Windows.
# Esegui in PowerShell come Amministratore:
#   powershell -ExecutionPolicy Bypass -File C:\StatArb\scripts\add_cursor_ssh_key.ps1

$cursorKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIINDZCEtLuu9iZwKZ37y0CbuhqzomXDq4g1M3n4UcYxN cursor-cloud-agent"
$adminKeysPath = "C:\ProgramData\ssh\administrators_authorized_keys"
$userKeysPath = Join-Path $env:USERPROFILE ".ssh\authorized_keys"
$sshDir = Join-Path $env:USERPROFILE ".ssh"

function Safe-TestPath {
    param([string]$Path)
    try {
        return Test-Path -LiteralPath $Path -ErrorAction Stop
    } catch {
        return $false
    }
}

function Repair-AdminSshPermissions {
    param([string]$Path)
    if (-not (Safe-TestPath $Path)) {
        return
    }
    icacls $Path /inheritance:r | Out-Null
    icacls $Path /grant:r "SYSTEM:F" | Out-Null
    icacls $Path /grant:r "Administrators:F" | Out-Null
}

function Repair-UserSshPermissions {
    if (-not (Safe-TestPath $sshDir)) {
        return
    }
    try {
        icacls $sshDir /inheritance:r | Out-Null
        icacls $sshDir /grant:r "SYSTEM:(OI)(CI)F" | Out-Null
        icacls $sshDir /grant:r "Administrators:(OI)(CI)F" | Out-Null
        icacls $sshDir /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
        if (Safe-TestPath $userKeysPath) {
            icacls $userKeysPath /inheritance:r | Out-Null
            icacls $userKeysPath /grant:r "SYSTEM:F" | Out-Null
            icacls $userKeysPath /grant:r "Administrators:F" | Out-Null
            icacls $userKeysPath /grant:r "${env:USERNAME}:F" | Out-Null
        }
        Write-Host "OK: permessi .ssh ripristinati per $env:USERNAME"
    } catch {
        Write-Warning "Impossibile ripristinare permessi .ssh: $_"
    }
}

function Add-KeyIfMissing {
    param(
        [string]$Path,
        [string]$KeyLine,
        [bool]$Required = $true
    )
    $dir = Split-Path $Path -Parent
    try {
        if (-not (Safe-TestPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        if (-not (Safe-TestPath $Path)) {
            New-Item -ItemType File -Path $Path -Force | Out-Null
        }
        $content = @(Get-Content -LiteralPath $Path -ErrorAction Stop)
        if ($content -match "cursor-cloud-agent") {
            Write-Host "OK: chiave cursor-cloud-agent gia presente in $Path"
            return $true
        }
        Add-Content -LiteralPath $Path -Value $KeyLine -Encoding ascii
        Write-Host "OK: chiave aggiunta in $Path"
        return $true
    } catch {
        if ($Required) {
            Write-Error "Errore su $Path : $_"
        } else {
            Write-Warning "Saltato $Path (non necessario per Administrator): $_"
        }
        return $false
    }
}

# Per Administrator su Windows OpenSSH usa administrators_authorized_keys (obbligatorio).
$null = Add-KeyIfMissing -Path $adminKeysPath -KeyLine $cursorKey -Required $true
Repair-AdminSshPermissions -Path $adminKeysPath

# Backup opzionale: .ssh\authorized_keys (non usato da sshd per il gruppo Administrators).
Repair-UserSshPermissions
$null = Add-KeyIfMissing -Path $userKeysPath -KeyLine $cursorKey -Required $false

$sshd = Get-Service sshd -ErrorAction SilentlyContinue
if ($sshd) {
    if ($sshd.Status -ne "Running") {
        Start-Service sshd
        Write-Host "OK: servizio sshd avviato"
    } else {
        Write-Host "OK: servizio sshd gia in esecuzione"
    }
    Set-Service sshd -StartupType Automatic
} else {
    Write-Warning "Servizio sshd non trovato. Installa OpenSSH Server."
}

$port = 22
$configPath = "C:\ProgramData\ssh\sshd_config"
if (Safe-TestPath $configPath) {
    $match = Select-String -Path $configPath -Pattern '^\s*Port\s+(\d+)' | Select-Object -First 1
    if ($match) {
        $port = $match.Matches[0].Groups[1].Value
    }
}

Write-Host ""
Write-Host "=== Stato chiave (admin) ==="
if (Safe-TestPath $adminKeysPath) {
    Get-Content -LiteralPath $adminKeysPath | ForEach-Object { Write-Host "  $_" }
} else {
    Write-Warning "File admin non leggibile: $adminKeysPath"
}

Write-Host ""
Write-Host "=== Configura in Cursor (Remote SSH) ==="
Write-Host "Host statarb-vps"
Write-Host "    HostName 144.91.76.28"
Write-Host "    User Administrator"
Write-Host "    Port $port"
Write-Host ""
Write-Host "Test da un altro PC:"
Write-Host "  ssh -p $port Administrator@144.91.76.28"
