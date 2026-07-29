@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
python gui_verification_app.py %*
set "exit_code=%errorlevel%"
if not "%exit_code%"=="0" pause
exit /b %exit_code%
