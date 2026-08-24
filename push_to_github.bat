@echo off
setlocal
cd /d "%~dp0"

set "GIT=git"
where git >nul 2>nul
if errorlevel 1 (
    if exist "D:\Git\cmd\git.exe" (
        set "GIT=D:\Git\cmd\git.exe"
        echo [INFO] git not found in PATH. Using D:\Git\cmd\git.exe
    ) else (
        echo [ERROR] Git not found. Please install Git first.
        pause
        exit /b 1
    )
)

if not exist ".git" (
    "%GIT%" init
)

"%GIT%" add .
"%GIT%" commit -m "chore: add git diagnostic scripts" >nul 2>nul

"%GIT%" branch -M main

"%GIT%" remote get-url origin >nul 2>nul
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
    "%GIT%" remote add origin %~1
)

"%GIT%" push -u origin main
"%GIT%" push origin v0.2.0
