@echo off
title TG TradinGo Webapp
cd /d C:\TG_TradinGo

echo ============================================
echo  TG TradinGo Monitor Webapp - Avvio
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato nel PATH.
    pause
    exit /b 1
)

python -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo ERRORE: fastapi/uvicorn non installati.
    echo.
    echo Installa con:
    echo   pip install -r C:\TG_TradinGo\requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "C:\TG_TradinGo\webapp_config.json" (
    echo ERRORE: manca C:\TG_TradinGo\webapp_config.json
    echo.
    echo 1. copia webapp_config.example.json in webapp_config.json
    echo 2. genera hash password e secret: python -m webapp.hash_password
    echo 3. incolla i valori nel config
    echo.
    pause
    exit /b 1
)

:: Evita seconda istanza
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$n = @(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -EA SilentlyContinue | Where-Object { $_.CommandLine -match 'webapp\.app' }).Count; if ($n -gt 0) { Write-Host \"ERRORE: webapp gia' attiva ($n istanze).\"; exit 1 } else { exit 0 }"
if errorlevel 1 (
    pause
    exit /b 1
)

echo Avvio webapp su http://0.0.0.0:8600 (accesso via Tailscale)
python -m webapp.app

pause
