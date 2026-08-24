@echo off
setlocal
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Git not found. Please install Git first.
    pause
    exit /b 1
)

if not exist ".git" (
    git init
)

git add .
git commit -m "release: v0.2.0 DeepSeek UI and clip export" >nul 2>nul

git branch -M main

git remote get-url origin >nul 2>nul
if errorlevel 1 (
    if "%~1"=="" (
        echo.
        echo [INFO] origin remote is not set.
        echo        Run this script with your repo URL:
        echo.
        echo        push_to_github.bat https://github.com/^<YOUR_NAME^>/live-clip-analyzer.git
        echo.
        pause
        exit /b 0
    )
    git remote add origin %~1
)

git push -u origin main
