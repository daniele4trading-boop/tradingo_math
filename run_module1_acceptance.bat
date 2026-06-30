@echo off
cd /d C:\StatArb
python tests\test_module1_symbols.py
echo.
echo === LOG FILE ===
type state\statarb_logs\module1_acceptance.txt
exit /b %ERRORLEVEL%
