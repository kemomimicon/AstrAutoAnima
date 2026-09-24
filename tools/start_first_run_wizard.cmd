@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0first_run_wizard.py"
) else (
    python "%~dp0first_run_wizard.py"
)
if errorlevel 1 pause
