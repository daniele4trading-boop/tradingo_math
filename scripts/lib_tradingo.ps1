$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$RegistryPath = Join-Path $RepoRoot "config\systems_registry.json"
$ConfigPath = Join-Path $RepoRoot "config\systems_config.json"
$LogsDir = Join-Path $RepoRoot "logs"

if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir | Out-Null
}

function Get-TradinGORegistry {
    if (-not (Test-Path $RegistryPath)) {
        throw "Registry not found: $RegistryPath"
    }
    return Get-Content -Raw -Path $RegistryPath | ConvertFrom-Json
}

function Get-TradinGOConfig {
    if (-not (Test-Path $ConfigPath)) {
        return [PSCustomObject]@{ systems = @{} }
    }
    return Get-Content -Raw -Path $ConfigPath | ConvertFrom-Json
}

function Get-TradinGOSystem {
    param([string]$SystemId)
    $registry = Get-TradinGORegistry
    if ([string]::IsNullOrWhiteSpace($SystemId)) {
        return $registry.systems
    }
    $system = $registry.systems | Where-Object { $_.id -eq $SystemId } | Select-Object -First 1
    if (-not $system) {
        throw "Unknown system id: $SystemId"
    }
    return $system
}

function Get-TradinGOProcess {
    param($System)
    $match = $System.process_match
    if ([string]::IsNullOrWhiteSpace($match)) {
        $match = $System.entrypoint
    }
    if ([string]::IsNullOrWhiteSpace($match)) {
        return @()
    }
    $normalized = $match.Replace("\", "/").ToLowerInvariant()
    return @(Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -match "^(python|pythonw)\.exe$" -and
            $_.CommandLine -and
            $_.CommandLine.Replace("\", "/").ToLowerInvariant().Contains($normalized)
        })
}

function Start-TradinGOSystem {
    param($System)
    if ($System.enabled -eq $false) {
        Write-Host "SKIP disabled: $($System.id)"
        return
    }
    $running = Get-TradinGOProcess -System $System
    if ($running.Count -gt 0) {
        Write-Host "ALREADY RUNNING $($System.id): $($running.ProcessId -join ',')"
        return
    }
    if (-not (Test-Path $System.working_directory)) {
        Write-Warning "Working directory not found for $($System.id): $($System.working_directory)"
        return
    }

    $pidPath = Join-Path $LogsDir "$($System.id).pid"
    $outLog = Join-Path $LogsDir "$($System.id).out.log"
    $errLog = Join-Path $LogsDir "$($System.id).err.log"
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c $($System.start_command)" `
        -WorkingDirectory $System.working_directory `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru `
        -WindowStyle Minimized
    Set-Content -Path $pidPath -Value $proc.Id -Encoding ASCII
    Write-Host "STARTED $($System.id) PID=$($proc.Id)"
}

function Stop-TradinGOSystem {
    param($System)
    $running = Get-TradinGOProcess -System $System
    if ($running.Count -eq 0) {
        Write-Host "NOT RUNNING $($System.id)"
        return
    }
    foreach ($proc in $running) {
        Stop-Process -Id $proc.ProcessId -Force
        Write-Host "STOPPED $($System.id) PID=$($proc.ProcessId)"
    }
}

function Show-TradinGOStatus {
    param($System)
    $running = Get-TradinGOProcess -System $System
    if ($running.Count -eq 0) {
        [PSCustomObject]@{
            id = $System.id
            name = $System.name
            status = "stopped"
            pids = ""
            broker = $System.broker
            account = $System.account
            working_directory = $System.working_directory
        }
    } else {
        [PSCustomObject]@{
            id = $System.id
            name = $System.name
            status = "running"
            pids = ($running.ProcessId -join ",")
            broker = $System.broker
            account = $System.account
            working_directory = $System.working_directory
        }
    }
}
