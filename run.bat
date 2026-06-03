@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Stock Screener
echo ========================================
echo.
echo Running... Please do not close this window.
echo.
python run.py
echo.
echo ========================================
echo Done. Press any key to close.
pause > nul
