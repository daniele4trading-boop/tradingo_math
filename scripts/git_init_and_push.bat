@echo off
setlocal EnableExtensions
cd /d C:\StatArb

echo ============================================
echo  Init git repo C:\StatArb -^> tradingo_system
echo ============================================
echo.

if not exist ".git" (
  echo [1/6] git init...
  git init
  if errorlevel 1 goto :err
) else (
  echo [1/6] .git gia presente
)

echo [2/6] remote origin...
git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin https://github.com/daniele4trading-boop/tradingo_system.git
  echo Aggiunto remote origin
) else (
  echo Remote origin gia configurato:
  git remote -v
)

echo [3/6] branch statarb-vps-mt5-modules-0-8...
git checkout -B statarb-vps-mt5-modules-0-8
if errorlevel 1 goto :err

echo [4/6] git add (rispetta .gitignore)...
git add .
if errorlevel 1 goto :err

echo.
echo Staged:
git status -sb
echo.

echo [5/6] git commit...
git commit -m "Add TG TradinGo project and agent documentation"
if errorlevel 1 (
  echo WARN: commit fallito o niente da committare
)

echo [6/6] git push...
git push -u origin statarb-vps-mt5-modules-0-8
if errorlevel 1 (
  echo.
  echo PUSH FALLITO - cause comuni:
  echo   - serve login GitHub ^(PAT o gh auth^)
  echo   - branch remoto diverso: prova git pull --rebase origin statarb-vps-mt5-modules-0-8
  echo.
  goto :end
)

echo.
echo OK - push completato
git status -sb
goto :end

:err
echo ERRORE git - vedi messaggi sopra
exit /b 1

:end
pause
