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

:: Controlla dipendenze (non installa automaticamente in produzione)
python -c "import telethon" >nul 2>&1
if errorlevel 1 (
    echo ERRORE: Telethon non installato.
    echo.
    echo Installa le dipendenze una tantum con:
    echo   cd C:\StatArb\tg_tradingo
    echo   pip install -r requirements.txt
    echo.
    echo Oppure dalla cartella produzione:
    echo   pip install -r C:\StatArb\tg_tradingo\requirements.txt
    echo.
    pause
    exit /b 1
)

:: Crea cartelle se non esistono
if not exist "C:\TG_TradinGo\logs"    mkdir "C:\TG_TradinGo\logs"
if not exist "C:\TG_TradinGo\signals" mkdir "C:\TG_TradinGo\signals"
if not exist "C:\TG_TradinGo\state"   mkdir "C:\TG_TradinGo\state"

echo Avvio bridge...
echo Log:   C:\TG_TradinGo\logs\
echo State: C:\TG_TradinGo\state\
echo.

:: Avvia con auto-restart gestito dal Python stesso
python tradingo_bridge.py

echo.
echo Bridge terminato.
pause
