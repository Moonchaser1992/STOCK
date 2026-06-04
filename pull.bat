@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Sync Stock Screener Results
echo ========================================
echo.
echo Pulling latest results...
git pull --no-rebase
echo.
echo ========================================
echo Done. Press any key to close.
pause > nul
