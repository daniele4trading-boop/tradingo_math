param(
    [string]$Target = "C:\Users\danie\OneDrive\DANIELE\TRADINGO 2026"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $Target "backup_$stamp"

if (-not (Test-Path $Target)) {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
}
New-Item -ItemType Directory -Path $dest -Force | Out-Null

$excludeDirs = @(".git", "__pycache__", ".venv", "venv")
$excludeFiles = @("*.log", "*.pid", "*.sqlite", ".env")

robocopy $RepoRoot $dest /E /XD $excludeDirs /XF $excludeFiles /R:2 /W:2 | Out-Host
$code = $LASTEXITCODE
if ($code -le 7) {
    Write-Host "Backup completed: $dest"
    exit 0
}
throw "Robocopy failed with code $code"
