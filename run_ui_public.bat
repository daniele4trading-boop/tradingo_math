@echo off
setlocal
cd /d C:\StatArb
call "%~dp0python_env.bat"

echo ============================================
echo StatArb UI - accesso remoto (0.0.0.0:8520)
echo Apri: http://IP_VPS:8520
echo Esempio: http://144.91.76.28:8520
echo ============================================

%STATARB_PY% -m pip show streamlit >nul 2>&1
if errorlevel 1 (
  %STATARB_PY% -m pip install streamlit
)

set "PYTHONPATH=C:\StatArb"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"

%STATARB_PY% -m streamlit run ui\app.py ^
  --server.port 8520 ^
  --server.address 0.0.0.0 ^
  --server.headless true ^
  --browser.gatherUsageStats false

pause
