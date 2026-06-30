@echo off
cd /d C:\StatArb
call "%~dp0python_env.bat"
set PYTHONPATH=C:\StatArb
%STATARB_PY% launch\cli.py --no-execute
pause
