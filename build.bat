@echo off
REM Windows 构建脚本

echo ========================================
echo mijia-server Windows 构建脚本
echo ========================================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python
    pause
    exit /b 1
)

REM 检查 Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Node.js
    pause
    exit /b 1
)

REM 安装 PyInstaller
echo 安装 PyInstaller...
pip install pyinstaller

REM 清理构建目录
echo 清理构建目录...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM 构建前端
echo 构建前端...
cd web
call npm ci
call npm run build
cd ..

REM 构建可执行文件
echo 构建可执行文件...
pyinstaller --clean --noconfirm mijia-server.spec

echo ========================================
echo 构建完成!
echo 输出目录: dist\mijia-server
echo ========================================
pause
