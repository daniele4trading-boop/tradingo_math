param(
    [string]$RepoDir = "C:\TradinGO_Research",
    [string]$TaskName = "TradinGoAPI",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8080,
    [string]$DataDir = "",
    [string]$ApiKeys = "",
    [string]$AdminApiKeys = "",
    [switch]$AllowDevKey
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $RepoDir)) {
    throw "RepoDir not found: $RepoDir"
}

Set-Location $RepoDir

if ($DataDir -eq "") {
    $DataDir = Join-Path $RepoDir "runtime\api_state"
}

$RuntimeDir = Join-Path $RepoDir "runtime"
$LogDir = Join-Path $RuntimeDir "logs"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Launcher = Join-Path $RuntimeDir "start_api.bat"
$ApiLog = Join-Path $LogDir "api.log"

$devKeyLine = ""
if ($AllowDevKey) {
    $devKeyLine = "set TRADINGO_API_ALLOW_DEV_KEY=1"
}

$apiKeysLine = ""
if ($ApiKeys -ne "") {
    $apiKeysLine = "set TRADINGO_API_KEYS=$ApiKeys"
}

$adminKeysLine = ""
if ($AdminApiKeys -ne "") {
    $adminKeysLine = "set TRADINGO_ADMIN_API_KEYS=$AdminApiKeys"
}

$launcherBody = @"
@echo off
cd /d $RepoDir
$devKeyLine
$apiKeysLine
$adminKeysLine
set TRADINGO_API_DATA_DIR=$DataDir
python -m uvicorn tradingo_core.api_server:create_app --factory --host $HostAddress --port $Port --log-level info >> $ApiLog 2>&1
"@

Set-Content -Path $Launcher -Value $launcherBody -Encoding ASCII

schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
schtasks /Create /TN $TaskName /SC ONSTART /RL HIGHEST /TR $Launcher /F | Out-Host
schtasks /Run /TN $TaskName | Out-Host

Start-Sleep -Seconds 5

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "API task installed and listening on ${HostAddress}:${Port}"
    exit 0
}

Write-Output "API task installed but not listening yet. Last log lines:"
Get-Content $ApiLog -Tail 80 -ErrorAction SilentlyContinue
exit 1
