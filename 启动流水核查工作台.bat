@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 流水核查工作台 - 独立调试入口
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

where python >nul 2>&1
if errorlevel 1 goto use_py_launcher

echo [流水核查] 启动独立工作台：%CD%\gui_verification_app.py
python gui_verification_app.py
goto finished

:use_py_launcher
where py >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3，并确保 python 或 py 已加入 PATH。
    pause
    exit /b 1
)
echo [流水核查] 使用 py -3 启动独立工作台：%CD%\gui_verification_app.py
py -3 gui_verification_app.py

:finished
set "exit_code=%errorlevel%"
if not "%exit_code%"=="0" echo [错误] 工作台已退出，退出码：%exit_code%
echo [流水核查] 窗口已关闭。按任意键退出调试终端。
pause
exit /b %exit_code%
