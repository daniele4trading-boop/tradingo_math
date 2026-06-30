@echo off
setlocal
cd /d C:\StatArb
call "%~dp0python_env.bat"

echo ============================================
echo StatArb UI - diagnostica
echo ============================================
echo Python: %STATARB_PY%
%STATARB_PY% --version
echo.

%STATARB_PY% -m pip show streamlit >nul 2>&1
if errorlevel 1 (
  echo [WARN] streamlit non installato - installazione...
  %STATARB_PY% -m pip install streamlit
  if errorlevel 1 (
    echo [FAIL] pip install streamlit fallito
    exit /b 1
  )
)

%STATARB_PY% -m streamlit --version
echo.

set "PYTHONPATH=C:\StatArb"
%STATARB_PY% -c "import sys; sys.path.insert(0,'C:\\StatArb'); import ui.services; print('import ui.services OK')"
if errorlevel 1 (
  echo [FAIL] import ui.services fallito
  exit /b 1
)

netstat -an | findstr ":8520" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo [WARN] porta 8520 gia' in uso
  netstat -an | findstr ":8520"
)

echo.
echo Diagnostica OK. Avvia con: run_ui.bat
exit /b 0
