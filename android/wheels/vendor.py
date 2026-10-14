"""Resolve Android requirements once, then assemble APKs without package-network access."""

from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--platform",
        "android_24_arm64_v8a",
        "--python-version",
        "3.11",
        "--abi",
        "cp311",
        "--implementation",
        "cp",
        "--find-links",
        str(root / "wheels/dist"),
        "--dest",
        str(root / "wheels/dist"),
        "-r",
        str(root / "requirements.txt"),
    ],
    check=True,
)
