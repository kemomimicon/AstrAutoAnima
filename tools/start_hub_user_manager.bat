@echo off
setlocal
cd /d "%~dp0"
py -3 hub_lite_user_manager.py gui
if errorlevel 1 python hub_lite_user_manager.py gui
pause
