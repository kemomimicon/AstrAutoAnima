@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0."
if errorlevel 1 goto :failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tools\bootstrap_windows.ps1"
if errorlevel 1 goto :failed
exit /b 0
:failed
echo Deployment failed. Keep this window for diagnostics.
pause
exit /b 1
