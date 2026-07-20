#!/usr/bin/env python3
"""清理项目多余文件

删除以下内容：
- Python 缓存文件 (__pycache__, *.pyc, *.pyo)
- 测试覆盖率文件 (.coverage, htmlcov/)
- 构建产物 (dist/, build/, *.egg-info/)
- mypy 缓存 (.mypy_cache/)
- pytest 缓存 (.pytest_cache/)
- IDE 配置 (.idea/, .vscode/)
- 临时文件 (*.tmp, *.log, .DS_Store)
"""

import shutil
from pathlib import Path
from typing import List


def get_project_root() -> Path:
    """获取项目根目录（本文件位于 deploy/scripts/）"""
    return Path(__file__).resolve().parents[2]


def clean_patterns(root: Path, patterns: List[str], description: str) -> int:
    """清理匹配模式的文件和目录
    
    Args:
        root: 项目根目录
        patterns: 要清理的模式列表
        description: 清理内容描述
        
    Returns:
        清理的文件/目录数量
    """
    count = 0
    print(f"\n清理 {description}...")
    
    for pattern in patterns:
        # 查找匹配的文件和目录
        for item in root.rglob(pattern):
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                    print(f"  删除目录: {item.relative_to(root)}")
                else:
                    item.unlink()
                    print(f"  删除文件: {item.relative_to(root)}")
                count += 1
            except Exception as e:
                print(f"  ⚠️  无法删除 {item.relative_to(root)}: {e}")
    
    if count == 0:
        print(f"  ✓ 没有需要清理的 {description}")
    else:
        print(f"  ✓ 清理了 {count} 个项目")
    
    return count


def main():
    """主函数"""
    root = get_project_root()
    print(f"项目根目录: {root}")
    print("=" * 60)
    
    total_count = 0
    
    # 1. Python 缓存文件
    total_count += clean_patterns(
        root,
        ["__pycache__", "*.pyc", "*.pyo", "*.pyd"],
        "Python 缓存文件"
    )
    
    # 2. 测试覆盖率文件
    total_count += clean_patterns(
        root,
        [".coverage", ".coverage.*", "htmlcov"],
        "测试覆盖率文件"
    )
    
    # 3. 构建产物
    total_count += clean_patterns(
        root,
        ["dist", "build", "*.egg-info", "*.egg"],
        "构建产物"
    )
    
    # 4. mypy 缓存
    total_count += clean_patterns(
        root,
        [".mypy_cache"],
        "mypy 缓存"
    )
    
    # 5. pytest 缓存
    total_count += clean_patterns(
        root,
        [".pytest_cache"],
        "pytest 缓存"
    )
    
    # 6. IDE 配置（可选，注释掉以保留）
    # total_count += clean_patterns(
    #     root,
    #     [".idea", ".vscode"],
    #     "IDE 配置"
    # )
    
    # 7. 临时文件
    total_count += clean_patterns(
        root,
        ["*.tmp", "*.log", ".DS_Store", "Thumbs.db"],
        "临时文件"
    )
    
    # 8. 旧版本文件（可选）
    # 注意：mijiaAPI 是旧版本代码，如需清理请取消注释
    # total_count += clean_patterns(
    #     root,
    #     ["mijiaAPI"],
    #     "旧版本代码"
    # )
    
    print("\n" + "=" * 60)
    print(f"✅ 清理完成！共清理 {total_count} 个文件/目录")


if __name__ == "__main__":
    main()
