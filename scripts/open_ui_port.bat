@echo off
setlocal
echo Aggiunge regola firewall inbound TCP 8520 (StatArb UI)...
netsh advfirewall firewall add rule name="StatArb UI 8520" dir=in action=allow protocol=TCP localport=8520
if errorlevel 1 (
  echo ERRORE: esegui come Amministratore
  pause
  exit /b 1
)
echo OK. Da cellulare: http://144.91.76.28:8520
pause
