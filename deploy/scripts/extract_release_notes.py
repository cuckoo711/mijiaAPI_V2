#!/usr/bin/env python3
"""从 CHANGELOG.md 提取指定版本的段落，作为 GitHub Release 描述。

用法：
    python deploy/scripts/extract_release_notes.py v3.2.2 [--changelog CHANGELOG.md]

匹配规则：找到 ``## v3.2.2`` 或 ``## 3.2.2`` 打头的一段（允许后缀 ``- 日期``），
提取到下一个 ``##`` 之前的所有内容。找不到时以退出码 1 返回，并把默认提示写到 stdout。

输出到 stdout；如果未找到并想强制不报错，加 ``--allow-missing``：
    python deploy/scripts/extract_release_notes.py v3.2.2 --allow-missing
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_notes(changelog: str, version: str) -> str | None:
    """在 CHANGELOG 中查找 ``version`` 对应的段落。

    Args:
        changelog: CHANGELOG.md 全文
        version: 版本字符串，可带或不带前导 ``v``，例如 ``v3.2.2`` 或 ``3.2.2``

    Returns:
        提取到的 markdown 段落（不含起始的 ``## 标题`` 行本身），或 None 表示未找到
    """
    normalized = version[1:] if version.startswith("v") else version
    # 允许标题为 ``## v3.2.2`` / ``## 3.2.2``，后面可选 " - 2026-07-05"
    # 注意用 ``[ \t]`` 而非 ``\s``，避免 ``\s`` 跨行匹配到下一段内容
    pattern = re.compile(
        rf"^##[ \t]+v?{re.escape(normalized)}[ \t]*(?:-[^\n]*)?$",
        re.MULTILINE,
    )
    match = pattern.search(changelog)
    if not match:
        return None

    start = match.end()
    # 查找下一个 ``## `` 起始的段落作为终点
    next_match = re.search(r"^##\s+", changelog[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(changelog)
    body = changelog[start:end].strip()
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="要提取的版本，如 v3.2.2 或 3.2.2")
    parser.add_argument(
        "--changelog",
        default="CHANGELOG.md",
        help="CHANGELOG 文件路径（相对当前目录），默认 CHANGELOG.md",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="找不到对应版本时不返回非 0，仅输出提示",
    )
    args = parser.parse_args()

    changelog_path = Path(args.changelog)
    if not changelog_path.exists():
        print(f"CHANGELOG 文件不存在: {changelog_path}", file=sys.stderr)
        return 2

    content = changelog_path.read_text(encoding="utf-8")
    body = extract_notes(content, args.version)
    if body is None:
        print(
            f"未在 {changelog_path} 中找到 {args.version} 对应的段落。请检查 CHANGELOG.md",
            file=sys.stderr,
        )
        if args.allow_missing:
            # 输出一个通用提示，避免 CI 用空 body
            print(f"版本 {args.version} 未在 CHANGELOG.md 中记录。")
            return 0
        return 1

    sys.stdout.write(body)
    if not body.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
