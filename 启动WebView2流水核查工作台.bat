@echo off
setlocal
set "WORKBENCH_ROOT=%~dp0"
set "WORKBENCH_BOOTSTRAP=%WORKBENCH_ROOT%tools\start_webview2_workbench.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%WORKBENCH_BOOTSTRAP%" %*
set "WORKBENCH_EXIT=%ERRORLEVEL%"
endlocal & exit /b %WORKBENCH_EXIT%
