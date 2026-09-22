@echo off
setlocal
chcp 65001 >nul 2>&1

REM MiniYuxi CLI 启动器（Windows）
REM 优先使用项目虚拟环境 .venv，不存在则回退系统 python

set "CLI_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%CLI_PY%" set "CLI_PY=python"

"%CLI_PY%" "%~dp0cli.py" %*
endlocal
