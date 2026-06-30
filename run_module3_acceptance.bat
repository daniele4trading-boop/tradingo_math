@echo off
cd /d C:\StatArb
call "%~dp0ensure_module3_deps.bat"
if errorlevel 1 exit /b 1
call "%~dp0python_env.bat"
%STATARB_PY% tests\test_module3_engine.py
echo.
echo === LOG FILE ===
type state\statarb_logs\module3_acceptance.txt
exit /b %ERRORLEVEL%
