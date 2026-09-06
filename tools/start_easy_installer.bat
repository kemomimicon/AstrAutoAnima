@echo off
setlocal
cd /d "%~dp0.."
py -3 tools\easy_installer.py
if errorlevel 1 python tools\easy_installer.py
if errorlevel 1 pause
