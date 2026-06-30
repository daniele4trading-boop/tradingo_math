@echo off
cd /d C:\StatArb
call "%~dp0python_env.bat"
%STATARB_PY% -m pip install -q streamlit
echo streamlit installato/aggiornato.
