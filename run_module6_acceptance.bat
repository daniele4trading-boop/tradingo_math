@echo off
cd /d C:\StatArb
call "%~dp0python_env.bat"
%STATARB_PY% tests\test_module6_ui.py
echo.
echo === LOG FILE ===
type state\statarb_logs\module6_acceptance.txt
exit /b %ERRORLEVEL%
