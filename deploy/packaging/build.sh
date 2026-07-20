#!/bin/bash
# Linux/macOS build wrapper — always runs from the repository root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${ROOT_DIR}"

echo "========================================"
echo "mijia-server 多平台构建脚本"
echo "仓库根目录: ${ROOT_DIR}"
echo "========================================"

if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "错误: 未找到 Python"
    exit 1
fi
PYTHON_BIN="$(command -v python3 || command -v python)"

if ! command -v node &> /dev/null; then
    echo "错误: 未找到 Node.js"
    exit 1
fi

PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case $ARCH in
    x86_64|amd64) ARCH="x64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    i386|i686) ARCH="x86" ;;
esac
echo "当前平台: $PLATFORM ($ARCH)"

echo "安装 PyInstaller..."
"${PYTHON_BIN}" -m pip install pyinstaller pillow

echo "清理构建目录..."
rm -rf build dist

echo "构建前端..."
(cd web && npm ci && npm run build)

echo "构建可执行文件..."
"${PYTHON_BIN}" -m PyInstaller --clean --noconfirm deploy/packaging/mijia-server.spec

echo "创建压缩包..."
cd dist
if [ "$PLATFORM" = "linux" ] || [ "$PLATFORM" = "darwin" ]; then
    tar -czf "mijia-server-${PLATFORM}-${ARCH}.tar.gz" mijia-server
    ARCHIVE="mijia-server-${PLATFORM}-${ARCH}.tar.gz"
fi
cd "${ROOT_DIR}"

echo "========================================"
echo "构建完成!"
echo "输出文件: dist/${ARCHIVE:-mijia-server}"
echo "========================================"
