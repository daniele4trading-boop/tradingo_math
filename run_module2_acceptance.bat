@echo off
cd /d C:\StatArb
python tests\test_module2_scanner.py
echo.
echo === LOG FILE ===
type state\statarb_logs\module2_acceptance.txt
exit /b %ERRORLEVEL%
