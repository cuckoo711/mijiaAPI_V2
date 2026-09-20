#!/bin/bash
# 清理项目多余文件
#
# 本脚本是 clean.py 的薄包装：清理规则只在 clean.py 里维护一份，
# 避免两份实现随时间漂移。参数原样透传，例如：
#   ./deploy/scripts/clean.sh --all
#   ./deploy/scripts/clean.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

if command -v uv >/dev/null 2>&1; then
    exec uv run python "$SCRIPT_DIR/clean.py" "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_DIR/clean.py" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "$SCRIPT_DIR/clean.py" "$@"
else
    echo "错误: 未找到 uv / python3 / python，无法执行清理" >&2
    exit 1
fi
