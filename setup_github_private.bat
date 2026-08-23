@echo off
REM Initialize local git repo and optionally create a private GitHub repo via gh CLI.
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Git not found. Please install Git first.
    pause
    exit /b 1
)

git init
git add .
git commit -m "init: live clip analyzer"
git branch -M main

where gh >nul 2>nul
if errorlevel 1 (
    echo.
    echo [INFO] GitHub CLI (gh) not found. Please create a PRIVATE repo on https://github.com/new
    echo        then run the following commands manually:
    echo.
    echo        cd /d D:\GitRepository\live-clip-analyzer
    echo        git remote add origin https://github.com/^<YOUR_NAME^>/live-clip-analyzer.git
    echo        git push -u origin main
    echo.
    pause
    exit /b 0
)

gh repo create live-clip-analyzer --private --source=. --remote=origin --push
