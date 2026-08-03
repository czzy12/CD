@echo off
setlocal
cd /d "%~dp0"
set "SPIKE_PYTHON=D:\Investigator PDF\.venvs\cd-bankflow-web-spike-isolated\Scripts\python.exe"
if not exist "%SPIKE_PYTHON%" set "SPIKE_PYTHON=python"
"%SPIKE_PYTHON%" gui_web_spike_app.py
endlocal
