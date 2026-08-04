@echo off
setlocal
set "WORKBENCH_ROOT=%~dp0"
set "WORKBENCH_PYTHON=%WORKBENCH_ROOT%..\.venvs\cd-bankflow-webview2-spike\Scripts\pythonw.exe"
set "WORKBENCH_APP=%WORKBENCH_ROOT%gui_webview2_app.py"
if not exist "%WORKBENCH_PYTHON%" (
  echo Missing Python environment:
  echo %WORKBENCH_PYTHON%
  pause
  exit /b 1
)
cd /d "%WORKBENCH_ROOT%"
"%WORKBENCH_PYTHON%" "%WORKBENCH_APP%" %*
set "WORKBENCH_EXIT=%ERRORLEVEL%"
endlocal & exit /b %WORKBENCH_EXIT%
