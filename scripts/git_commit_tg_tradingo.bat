@echo off
setlocal
cd /d C:\StatArb

echo === git status ===
git status -sb
echo.

echo === remote ===
git remote -v
echo.

echo === branch ===
git branch --show-current
echo.

echo === git add ===
git add tg_tradingo AGENTS.md .gitignore scripts/import_tg_tradingo_to_repo.ps1 scripts/deploy_tg_tradingo_to_vps.ps1 scripts/copy_tg_bridge_once.py
git status -sb
echo.

echo === git commit ===
git commit -m "Add TG TradinGo project and agent documentation"
echo.

echo === git push ===
git push -u origin HEAD
echo.

echo === fine ===
git status -sb
pause
