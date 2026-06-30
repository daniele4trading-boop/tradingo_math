@echo off
set "STATARB_PY=python"
if exist "%~dp0.venv\Scripts\python.exe" (
  set "STATARB_PY=%~dp0.venv\Scripts\python.exe"
)
