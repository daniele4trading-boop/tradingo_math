@echo off
setlocal
cd /d C:\StatArb
call "%~dp0python_env.bat"

echo ============================================
echo StatArb UI
echo Apri nel browser sulla VPS (RDP):
echo   http://127.0.0.1:8520
echo.
echo Se accedi da un altro PC alla VPS usa:
echo   run_ui_public.bat
echo ============================================

%STATARB_PY% -m pip show streamlit >nul 2>&1
if errorlevel 1 (
  echo Installazione streamlit...
  %STATARB_PY% -m pip install streamlit
)

set "PYTHONPATH=C:\StatArb"
set "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"

%STATARB_PY% -m streamlit run ui\app.py ^
  --server.port 8520 ^
  --server.address 127.0.0.1 ^
  --server.headless true ^
  --browser.gatherUsageStats false

echo.
echo Streamlit terminato (exit %ERRORLEVEL%)
pause
