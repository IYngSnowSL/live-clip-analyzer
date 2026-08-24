@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "GIT=git"
where git >nul 2>nul
if errorlevel 1 (
    if exist "D:\Git\cmd\git.exe" (
        set "GIT=D:\Git\cmd\git.exe"
        echo [INFO] git was not found in PATH. Using D:\Git\cmd\git.exe
        echo.
    ) else (
        echo [ERROR] git.exe not found in PATH and not found in D:\Git\cmd
        pause
        exit /b 1
    )
)

echo ============================================
echo 1. GIT VERSION
echo ============================================
"%GIT%" --version
echo.

echo ============================================
echo 2. REPO STATUS
echo ============================================
"%GIT%" status
echo.

echo ============================================
echo 3. REMOTES
echo ============================================
"%GIT%" remote -v
echo.

echo ============================================
echo 4. LOCAL BRANCH AND UPSTREAM
echo ============================================
"%GIT%" branch -vv
echo.

echo ============================================
echo 5. RECENT COMMITS
echo ============================================
"%GIT%" log --oneline -5
echo.

echo ============================================
echo 6. TAGS
echo ============================================
"%GIT%" tag
echo.

echo ============================================
echo 7. PATH
echo ============================================
echo %PATH%
echo.

if exist "D:\Git\usr\bin\ssh.exe" (
    echo ============================================
    echo 8. GITHUB SSH TEST ^(timeout 10s^)
    echo ============================================
    "D:\Git\usr\bin\ssh.exe" -o BatchMode=yes -o ConnectTimeout=10 -T git@github.com
    echo.
)

echo Diagnostic finished. Please copy the output above.
pause
