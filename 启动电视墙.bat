@echo off
chcp 65001 >nul 2>&1
title 📺 IPTV 电视墙服务器
echo.
echo ╔══════════════════════════════════╗
echo ║  📺 正在启动电视墙服务器...       ║
echo ╚══════════════════════════════════╝
echo.

cd /d "%~dp0"

:: 尝试用系统 Python
where python >nul 2>&1
if %errorlevel%==0 (
    start http://127.0.0.1:18888/iptv.html
    python iptv-proxy.py
    goto :end
)

:: 尝试用 python3
where python3 >nul 2>&1
if %errorlevel%==0 (
    start http://127.0.0.1:18888/iptv.html
    python3 iptv-proxy.py
    goto :end
)

echo ❌ 没有找到 Python！
echo 请先安装 Python: https://www.python.org/downloads/
echo 安装时记得勾选 "Add Python to PATH"
pause

:end
