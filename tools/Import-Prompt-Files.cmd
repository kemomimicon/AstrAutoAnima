@echo off
setlocal DisableDelayedExpansion
set "PYTHONUTF8=1"
set "AAA_IMPORT_COUNT=0"
:collect
if "%~1"=="" goto run
if %AAA_IMPORT_COUNT% GEQ 64 goto too_many
set /a AAA_IMPORT_COUNT+=1 >nul
set "AAA_IMPORT_FILE_%AAA_IMPORT_COUNT%=%~f1"
shift
goto collect
:run
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 -B "%~dp0online_prompt_importer.py" --files-from-env
if errorlevel 1 pause
exit /b
:python_fallback
python -B "%~dp0online_prompt_importer.py" --files-from-env
if errorlevel 1 pause
exit /b
:too_many
echo Please select at most 64 files per import.
pause
exit /b 1
