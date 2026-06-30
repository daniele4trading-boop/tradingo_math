@echo off
cd /d C:\StatArb
call "%~dp0python_env.bat"
set PYTHONPATH=C:\StatArb
echo Scheduler StatArb — Ctrl+C per fermare
%STATARB_PY% launch\cli.py --loop 15
