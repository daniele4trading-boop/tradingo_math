@echo off
title TG TradinGo Bridge
cd /d C:\TG_TradinGo

echo ============================================
echo  TG TradinGo Bridge - Avvio
echo ============================================
echo.

:: Controlla Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Python non trovato nel PATH.
    echo Installa Python e riprova.
    pause
    exit /b 1
)

:: Controlla Telethon
python -c "import telethon" >nul 2>&1
if errorlevel 1 (
    echo Telethon non trovato. Installazione...
    pip install telethon
)

:: Crea cartelle se non esistono
if not exist "C:\TG_TradinGo\logs"    mkdir "C:\TG_TradinGo\logs"
if not exist "C:\TG_TradinGo\signals" mkdir "C:\TG_TradinGo\signals"

echo Avvio bridge...
echo Log: C:\TG_TradinGo\logs\
echo.

:: Avvia con auto-restart gestito dal Python stesso
python tradingo_bridge.py

echo.
echo Bridge terminato.
pause
