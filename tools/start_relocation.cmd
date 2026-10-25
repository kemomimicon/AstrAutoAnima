@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0."
if errorlevel 1 goto failed
set "PYTHONUTF8=1"
python "relocate_install.py"
if errorlevel 1 goto failed
exit /b 0
:failed
echo Unable to run the source tool. Use the standalone Windows EXE instead.
pause
exit /b 1
