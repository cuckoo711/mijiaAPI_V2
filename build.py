#!/usr/bin/env python3
"""
多平台构建脚本
用于构建 mijia-server 可执行文件
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def get_platform_info():
    """获取当前平台信息"""
    system = platform.system().lower()
    machine = platform.machine().lower()

    # 规范化架构名称
    if machine in ('x86_64', 'amd64'):
        arch = 'x64'
    elif machine in ('aarch64', 'arm64'):
        arch = 'arm64'
    elif machine in ('i386', 'i686', 'x86'):
        arch = 'x86'
    else:
        arch = machine

    return system, arch


def clean_build_dirs():
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        dir_path = Path(dir_name)
        if dir_path.exists():
            print(f"清理目录: {dir_name}")
            shutil.rmtree(dir_path)


def build_frontend():
    """构建前端"""
    web_dir = Path('web')
    if not web_dir.exists():
        print("警告: web 目录不存在，跳过前端构建")
        return

    print("构建前端...")
    subprocess.run(['npm', 'ci'], cwd=web_dir, check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=web_dir, check=True)


def build_executable():
    """构建可执行文件"""
    print("构建可执行文件...")
    subprocess.run([
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        'mijia-server.spec'
    ], check=True)


def main():
    """主函数"""
    print("=" * 60)
    print("mijia-server 多平台构建脚本")
    print("=" * 60)

    # 获取平台信息
    system, arch = get_platform_info()
    print(f"当前平台: {system} ({arch})")

    # 检查 PyInstaller 是否安装
    try:
        import PyInstaller
        print(f"PyInstaller 版本: {PyInstaller.__version__}")
    except ImportError:
        print("错误: 请先安装 PyInstaller")
        print("运行: pip install pyinstaller")
        sys.exit(1)

    # 清理构建目录
    clean_build_dirs()

    # 构建前端
    build_frontend()

    # 构建可执行文件
    build_executable()

    # 获取输出文件路径
    if system == 'windows':
        output_file = dist_dir / 'mijia-server.exe'
    else:
        output_file = dist_dir / 'mijia-server'

    print("=" * 60)
    print("构建完成!")
    if output_file.exists():
        print(f"输出文件: {output_file}")
        print(f"文件大小: {output_file.stat().st_size / 1024 / 1024:.2f} MB")
    print("=" * 60)


if __name__ == '__main__':
    main()
