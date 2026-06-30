@echo off
cd /d C:\StatArb
call "%~dp0python_env.bat"
%STATARB_PY% tests\test_module4_execution.py
echo.
echo === LOG FILE ===
type state\statarb_logs\module4_acceptance.txt
exit /b %ERRORLEVEL%
