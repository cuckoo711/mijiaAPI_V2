#!/usr/bin/env python3
"""清理项目多余文件（跨平台）

默认删除（对应 ``make clean``）：
- Python 缓存 (__pycache__, *.pyc, *.pyo, *.pyd)
- 工具缓存 (.mypy_cache/, .pytest_cache/)
- 临时文件 (*.tmp, *.log, .DS_Store, Thumbs.db)

加 --all 时额外删除（对应 ``make clean-all``）：
- 测试覆盖率产物 (.coverage, .coverage.*, htmlcov/)
- 构建产物 (dist/, build/, *.egg-info/, *.egg) —— 仅限仓库根目录

安全约束：
- 遍历时跳过 .git / .venv / node_modules 等目录，绝不动依赖树内部文件。
- 构建产物只在仓库根目录匹配，因此前端产物 web/dist 默认保留
  （它是服务端要发布的静态资源）。需要一并删除时加 --include-web-dist。
- 加 --dry-run 可先预览将要删除的内容。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, List


def _configure_stdout() -> None:
    """让输出在 GBK 等窄编码终端上不至于直接崩掉。

    中文 Windows 控制台的 stdout 默认是 GBK，编码不了 ``✓``/``⚠``/``✅``
    这类符号，会在清理中途抛 UnicodeEncodeError（脚本已删了一部分文件才崩）。
    正文一律用 GBK 可编码的中文与 ASCII 标记，这里再兜一层 errors="replace"，
    避免将来引入的任何字符重现这个问题。
    """
    stream = getattr(sys, "stdout", None)
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(errors="replace")
    except (OSError, ValueError):  # pragma: no cover - 取决于终端实现
        pass


# 遍历时整棵跳过的目录：依赖树、版本库与工具自有数据。
PRUNE_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "ENV",
        "__pypackages__",
        "node_modules",
        ".narrafork",
        ".worktrees",
        ".idea",
        ".vscode",
    }
)

# 递归清理（会走遍仓库，但受 PRUNE_DIRS 限制）
RECURSIVE_DIR_NAMES = ("__pycache__", ".mypy_cache", ".pytest_cache")
RECURSIVE_FILE_PATTERNS = ("*.pyc", "*.pyo", "*.pyd", "*.tmp", "*.log", ".DS_Store", "Thumbs.db")

# 仅在仓库根目录清理：避免误删 node_modules/<pkg>/dist 和 web/dist
ROOT_DIR_PATTERNS = ("build", "dist", "htmlcov", "*.egg-info")
ROOT_FILE_PATTERNS = (".coverage", ".coverage.*", "*.egg")


def get_project_root() -> Path:
    """获取项目根目录（本文件位于 deploy/scripts/）"""
    return Path(__file__).resolve().parents[2]


class Cleaner:
    """收集并删除目标路径，统一处理 dry-run 与错误提示。"""

    def __init__(self, root: Path, dry_run: bool = False) -> None:
        self.root = root
        self.dry_run = dry_run
        self.count = 0

    def _rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def remove(self, path: Path) -> None:
        verb = "将删除" if self.dry_run else "删除"
        kind = "目录" if path.is_dir() else "文件"
        try:
            if not self.dry_run:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            print(f"  {verb}{kind}: {self._rel(path)}")
            self.count += 1
        except OSError as exc:
            print(f"  [!] 无法删除 {self._rel(path)}: {exc}")

    def report(self, description: str, removed: int) -> None:
        if removed == 0:
            print(f"  [OK] 没有需要清理的 {description}")
        else:
            print(f"  [OK] 处理了 {removed} 个项目")


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch(name, pattern) for pattern in patterns)


def clean_recursive(cleaner: Cleaner, keep_dirs: frozenset[Path]) -> int:
    """剪枝遍历仓库，清理缓存目录与临时文件。"""
    print("\n清理 Python / 工具缓存与临时文件...")
    before = cleaner.count

    for current, dirnames, filenames in os.walk(cleaner.root, topdown=True):
        current_path = Path(current)

        # 就地修改 dirnames 以阻止 os.walk 继续下探。
        pruned: List[str] = []
        for dirname in sorted(dirnames):
            full = current_path / dirname
            if dirname in PRUNE_DIRS or full in keep_dirs:
                continue
            if dirname in RECURSIVE_DIR_NAMES:
                cleaner.remove(full)
                continue  # 已删除，不再下探
            pruned.append(dirname)
        dirnames[:] = pruned

        for filename in sorted(filenames):
            if _matches_any(filename, RECURSIVE_FILE_PATTERNS):
                cleaner.remove(current_path / filename)

    removed = cleaner.count - before
    cleaner.report("缓存与临时文件", removed)
    return removed


def clean_root_artifacts(cleaner: Cleaner) -> int:
    """清理仓库根目录的构建产物与覆盖率产物。"""
    print("\n清理构建产物与覆盖率产物（仅仓库根目录）...")
    before = cleaner.count

    for entry in sorted(cleaner.root.iterdir()):
        if entry.is_dir():
            if _matches_any(entry.name, ROOT_DIR_PATTERNS):
                cleaner.remove(entry)
        elif _matches_any(entry.name, ROOT_FILE_PATTERNS):
            cleaner.remove(entry)

    removed = cleaner.count - before
    cleaner.report("构建产物", removed)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="清理项目多余文件")
    parser.add_argument(
        "--all",
        action="store_true",
        dest="clean_all",
        help="额外删除根目录的构建产物与覆盖率报告（dist/ build/ htmlcov/ .coverage）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要删除的内容，不实际删除",
    )
    parser.add_argument(
        "--include-web-dist",
        action="store_true",
        help="同时删除前端构建产物 web/dist（删除后需重新 npm run build）",
    )
    args = parser.parse_args()

    _configure_stdout()
    root = get_project_root()
    cleaner = Cleaner(root, dry_run=args.dry_run)

    web_dist = root / "web" / "dist"
    keep_dirs = frozenset() if args.include_web_dist else frozenset({web_dist})

    print(f"项目根目录: {root}")
    if args.dry_run:
        print("模式: dry-run（不会删除任何文件）")
    print("=" * 60)

    clean_recursive(cleaner, keep_dirs)
    if args.clean_all:
        clean_root_artifacts(cleaner)

    if args.include_web_dist and web_dist.is_dir():
        print("\n清理前端构建产物...")
        cleaner.remove(web_dist)
        print("  提示: 重新构建请执行 cd web && npm run build")
    elif web_dist.is_dir():
        print(f"\n保留前端构建产物: {web_dist.relative_to(root)}（--include-web-dist 可删除）")

    print("\n" + "=" * 60)
    verb = "将清理" if args.dry_run else "已清理"
    print(f"[DONE] 完成！{verb} {cleaner.count} 个文件/目录")


if __name__ == "__main__":
    main()
