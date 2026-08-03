@echo off
setlocal
set "SPIKE_ROOT=%~dp0"
set "SPIKE_PYTHON=%SPIKE_ROOT%..\.venvs\cd-bankflow-webview2-spike\Scripts\pythonw.exe"
set "SPIKE_APP=%SPIKE_ROOT%gui_webview2_spike_app.py"
if not exist "%SPIKE_PYTHON%" (
  echo Missing Python environment:
  echo %SPIKE_PYTHON%
  pause
  exit /b 1
)
if not exist "%SPIKE_APP%" (
  echo Missing launcher:
  echo %SPIKE_APP%
  pause
  exit /b 1
)
cd /d "%SPIKE_ROOT%"
"%SPIKE_PYTHON%" "%SPIKE_APP%" %*
set "SPIKE_EXIT=%ERRORLEVEL%"
endlocal & exit /b %SPIKE_EXIT%
