@echo off
setlocal
echo Richiede PowerShell come Amministratore...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0add_cursor_ssh_key.ps1"
pause
