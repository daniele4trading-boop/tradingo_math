@echo off
cd /d C:\StatArb
call "%~dp0python_env.bat"
echo Using Python: %STATARB_PY%
%STATARB_PY% -m pip install -q scipy statsmodels
if errorlevel 1 (
  echo pip install failed — run manually: %STATARB_PY% -m pip install scipy statsmodels
  exit /b 1
)
