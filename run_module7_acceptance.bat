@echo off
cd /d C:\StatArb
call "%~dp0python_env.bat"
%STATARB_PY% tests\test_module7_backtest.py
echo.
echo === LOG FILE ===
type state\statarb_logs\module7_acceptance.txt
exit /b %ERRORLEVEL%
