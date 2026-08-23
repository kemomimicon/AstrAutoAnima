@echo off
setlocal
cd /d "%~dp0"
py -3 prompt_pool_manager.py gui
if errorlevel 1 python prompt_pool_manager.py gui
pause
