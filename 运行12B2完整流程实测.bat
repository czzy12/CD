@echo off
set "ROOT=%~dp0"
set "PY=%ROOT%..\.venvs\cd-bankflow-webview2-spike\Scripts\python.exe"
if not exist "%PY%" (
  echo WebView2 python env not found:
  echo %PY%
  pause
  exit /b 1
)
"%PY%" "%ROOT%tools\run_12b2_flow_qa.py" --case-dir "%ROOT%..\MVP-input" --old-case "%ROOT%..\outputs\schema116-validation\case-129.json" --output "%ROOT%..\outputs\web-gui-12b2\flow-qa.json" --hold-open
echo.
echo Finished. Result file: ..\outputs\web-gui-12b2\flow-qa.json
pause
