@echo off
setlocal
powershell.exe -NoLogo -NoProfile -File "%~dp0Open-AAA-Tunnel.ps1" %*
if errorlevel 1 echo If script policy blocks execution, use the official AutoDL GUI tunnel tool. Do not disable system-wide security.
pause
