@echo off
REM Launcher del bridge per il Task Scheduler (nessuna console interattiva:
REM niente timeout/pause, guardia anti-doppia-istanza, output su log).
cd /d C:\TG_TradinGo
if not exist logs mkdir logs

powershell -NoProfile -ExecutionPolicy Bypass -Command "$n = @(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -EA SilentlyContinue | Where-Object { $_.CommandLine -match 'tradingo_bridge\.py' }).Count; exit $n"
if errorlevel 1 (
    echo [%date% %time%] Bridge gia' attivo: avvio ignorato>> logs\bridge_task.log
    exit /b 0
)

echo [%date% %time%] Avvio bridge da Task Scheduler>> logs\bridge_task.log
python tradingo_bridge.py >> logs\bridge_stdout.log 2>&1
echo [%date% %time%] Bridge terminato (exit %errorlevel%)>> logs\bridge_task.log
exit /b %errorlevel%
