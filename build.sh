#!/bin/bash

# Linux/macOS 构建脚本

set -e

echo "========================================"
echo "mijia-server 多平台构建脚本"
echo "========================================"

# 检查 Python
if ! command -v python &> /dev/null; then
    echo "错误: 未找到 Python"
    exit 1
fi

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo "错误: 未找到 Node.js"
    exit 1
fi

# 获取平台信息
PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case $ARCH in
    x86_64|amd64)
        ARCH="x64"
        ;;
    aarch64|arm64)
        ARCH="arm64"
        ;;
    i386|i686)
        ARCH="x86"
        ;;
esac

echo "当前平台: $PLATFORM ($ARCH)"

# 安装 PyInstaller
echo "安装 PyInstaller..."
pip install pyinstaller

# 清理构建目录
echo "清理构建目录..."
rm -rf build dist __pycache__

# 构建前端
echo "构建前端..."
cd web
npm ci
npm run build
cd ..

# 构建可执行文件
echo "构建可执行文件..."
pyinstaller --clean --noconfirm mijia-server.spec

# 创建压缩包
echo "创建压缩包..."
cd dist
if [ "$PLATFORM" = "linux" ]; then
    tar -czf "mijia-server-${PLATFORM}-${ARCH}.tar.gz" mijia-server
    ARCHIVE="mijia-server-${PLATFORM}-${ARCH}.tar.gz"
elif [ "$PLATFORM" = "darwin" ]; then
    tar -czf "mijia-server-${PLATFORM}-${ARCH}.tar.gz" mijia-server
    ARCHIVE="mijia-server-${PLATFORM}-${ARCH}.tar.gz"
fi
cd ..

echo "========================================"
echo "构建完成!"
echo "输出文件: dist/${ARCHIVE}"
echo "========================================"
