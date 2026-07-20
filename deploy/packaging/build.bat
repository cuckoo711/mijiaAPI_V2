@echo off
REM Windows build wrapper — always runs from the repository root.
setlocal
cd /d "%~dp0..\.."

echo ========================================
echo mijia-server Windows 构建脚本
echo 仓库根目录: %CD%
echo ========================================

python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python
    pause
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Node.js
    pause
    exit /b 1
)

echo 安装 PyInstaller...
pip install pyinstaller pillow

echo 清理构建目录...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo 构建前端...
cd web
call npm ci
call npm run build
cd ..

echo 构建可执行文件...
pyinstaller --clean --noconfirm deploy\packaging\mijia-server.spec

echo ========================================
echo 构建完成!
echo 输出目录: dist\
echo ========================================
pause
