#!/bin/bash
# 清理项目多余文件

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

echo "开始清理项目..."
echo "========================================"

# 1. Python 缓存文件
echo ""
echo "清理 Python 缓存文件..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true
find . -type f -name "*.pyd" -delete 2>/dev/null || true
echo "✓ Python 缓存文件已清理"

# 2. 测试覆盖率文件
echo ""
echo "清理测试覆盖率文件..."
rm -rf .coverage .coverage.* htmlcov/ 2>/dev/null || true
echo "✓ 测试覆盖率文件已清理"

# 3. 构建产物
echo ""
echo "清理构建产物..."
rm -rf dist/ build/ *.egg-info/ *.egg 2>/dev/null || true
echo "✓ 构建产物已清理"

# 4. mypy 缓存
echo ""
echo "清理 mypy 缓存..."
rm -rf .mypy_cache/ 2>/dev/null || true
echo "✓ mypy 缓存已清理"

# 5. pytest 缓存
echo ""
echo "清理 pytest 缓存..."
rm -rf .pytest_cache/ 2>/dev/null || true
echo "✓ pytest 缓存已清理"

# 6. 临时文件
echo ""
echo "清理临时文件..."
find . -type f -name "*.tmp" -delete 2>/dev/null || true
find . -type f -name "*.log" -delete 2>/dev/null || true
find . -type f -name ".DS_Store" -delete 2>/dev/null || true
find . -type f -name "Thumbs.db" -delete 2>/dev/null || true
echo "✓ 临时文件已清理"

# 7. 可选：清理 IDE 配置（取消注释以启用）
# echo ""
# echo "清理 IDE 配置..."
# rm -rf .idea/ .vscode/ 2>/dev/null || true
# echo "✓ IDE 配置已清理"

# 8. 可选：清理旧版本代码（取消注释以启用）
# 注意：mijiaAPI 是旧版本代码，如需清理请取消注释
# echo ""
# echo "清理旧版本代码..."
# rm -rf mijiaAPI/ 2>/dev/null || true
# echo "✓ 旧版本代码已清理"

echo ""
echo "========================================"
echo "✅ 清理完成！"
