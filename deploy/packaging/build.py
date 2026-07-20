#!/usr/bin/env python3
"""Build mijia-server executables via PyInstaller.

Can be run from the repository root:
  python deploy/packaging/build.py
or from this directory:
  python build.py
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
ROOT_DIR = PACKAGING_DIR.parents[1]
SPEC_FILE = PACKAGING_DIR / "mijia-server.spec"


def get_platform_info() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if machine in ("x86_64", "amd64"):
        arch = "x64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    elif machine in ("i386", "i686", "x86"):
        arch = "x86"
    else:
        arch = machine

    return system, arch


def clean_build_dirs() -> None:
    for dir_name in ("build", "dist", "__pycache__"):
        dir_path = ROOT_DIR / dir_name
        if dir_path.exists():
            print(f"清理目录: {dir_path}")
            shutil.rmtree(dir_path)


def build_frontend() -> None:
    web_dir = ROOT_DIR / "web"
    if not web_dir.exists():
        print("警告: web 目录不存在，跳过前端构建")
        return

    print("构建前端...")
    subprocess.run(["npm", "ci"], cwd=web_dir, check=True)
    subprocess.run(["npm", "run", "build"], cwd=web_dir, check=True)


def build_executable() -> None:
    print("构建可执行文件...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(SPEC_FILE),
        ],
        cwd=ROOT_DIR,
        check=True,
    )


def main() -> None:
    print("=" * 60)
    print("mijia-server 多平台构建脚本")
    print("=" * 60)

    system, arch = get_platform_info()
    print(f"当前平台: {system} ({arch})")
    print(f"仓库根目录: {ROOT_DIR}")

    try:
        import PyInstaller  # noqa: F401

        print(f"PyInstaller 版本: {PyInstaller.__version__}")
    except ImportError:
        print("错误: 请先安装 PyInstaller")
        print("运行: pip install pyinstaller")
        sys.exit(1)

    clean_build_dirs()
    build_frontend()
    build_executable()

    dist_dir = ROOT_DIR / "dist"
    output_file = dist_dir / ("mijia-server.exe" if system == "windows" else "mijia-server")

    print("=" * 60)
    print("构建完成!")
    if output_file.exists():
        print(f"输出文件: {output_file}")
        print(f"文件大小: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    print("=" * 60)


if __name__ == "__main__":
    main()
