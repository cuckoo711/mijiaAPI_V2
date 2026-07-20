@echo off
chcp 65001 >nul
title 米家 API Server

echo ========================================
echo 米家 API Server 启动器
echo ========================================
echo.

REM Prefer configs/ (v3 layout); fall back to init when missing.
if not exist "configs\server\server.sqlite3" (
    echo 首次运行，正在初始化...
    echo.
    mijia-server-windows-x64.exe init
    echo.
)

echo 正在启动服务...
echo 启动后请访问: http://127.0.0.1:8123
echo.
echo 按 Ctrl+C 可停止服务
echo ========================================
echo.

mijia-server-windows-x64.exe run

pause
