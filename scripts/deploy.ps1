param(
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

Push-Location $RepoRoot
try {
    git pull origin main
    if (-not $NoRestart) {
        & "$PSScriptRoot\stop_all.ps1"
        Start-Sleep -Seconds 3
        & "$PSScriptRoot\start_all.ps1"
    }
} finally {
    Pop-Location
}
