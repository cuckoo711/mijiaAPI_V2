"""Build the two native dependencies with a pinned Chaquopy cross-compiler."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess

CHAQUOPY_COMMIT = "884ec5f14591d69844e20c9dc6a6a9c5d1ba0a41"
parser = argparse.ArgumentParser()
parser.add_argument("--chaquopy-source", type=Path, required=True)
parser.add_argument("--abis", nargs="+", default=["armeabi-v7a", "arm64-v8a", "x86", "x86_64"])
parser.add_argument("--source-cache", type=Path)
args = parser.parse_args()
os.environ.setdefault("SOURCE_DATE_EPOCH", "315532800")
chaquopy = args.chaquopy_source.resolve()
if (chaquopy / ".source-sha").exists():
    revision = (chaquopy / ".source-sha").read_text().strip()
else:
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=chaquopy, text=True
    ).strip()
assert revision == CHAQUOPY_COMMIT, "Review the cross-compiler before changing its pinned revision"
driver = chaquopy / "server/pypi/build-wheel.py"
text = driver.read_text()
text = text.replace(
    "                if link_filename != filename:",
    '                if link_filename != filename and not exists(f"{reqs_lib_dir}/{link_filename}"):',
)
text = text.replace(
    '"CARGO_BUILD_TARGET": tool_prefix,',
    '"CARGO_BUILD_TARGET": "armv7-linux-androideabi" if self.abi == "armeabi-v7a" else tool_prefix,',
)
old = '        run(f"rustup target add {tool_prefix}")'
new = """        # The caller installs official Rust components for all requested targets.
        config = Path(self.host_env) / "pyo3-cross.txt"
        config.write_text("\\n".join([
            "implementation=CPython", "version=" + self.python, "shared=true", "abi3=false",
            "lib_name=python" + self.python, "lib_dir=" + self.host_env + "/chaquopy/lib",
            "pointer_width=" + ("32" if self.abi in ["armeabi-v7a", "x86"] else "64"),
        ]) + "\\n")
        env["PYO3_CONFIG_FILE"] = str(config.resolve())"""
if old in text:
    text = text.replace(old, new).replace('            "PYO3_NO_PYTHON": "1",', "")
driver.write_text(text)
assert 'env["PYO3_CONFIG_FILE"]' in driver.read_text()

root = Path(__file__).resolve().parent
output = root / "dist"
output.mkdir(exist_ok=True)
for package in ["pycryptodome", "pydantic-core"]:
    recipe = root / "recipes" / package
    if args.source_cache:
        # Only use the explicitly prepared source directory, never an arbitrary wheel.
        source = (args.source_cache / package).resolve()
        assert source.is_dir()
        staged_recipe = chaquopy / "server/pypi/packages" / ("mijia-" + package)
        staged_recipe.mkdir(exist_ok=True)
        meta = (recipe / "meta.yaml").read_text()
        meta += f"\nsource:\n  path: {source}\n"
        if "  host:" not in meta:
            if "requirements:" in meta:
                meta = meta.replace("requirements:", "requirements:\n  host:\n    - python")
            else:
                meta += "\nrequirements:\n  host:\n    - python\n"
        (staged_recipe / "meta.yaml").write_text(meta)
        recipe = staged_recipe
    for abi in args.abis:
        if any(output.glob(f"{package.replace('-', '_')}-*{abi.replace('-', '_')}.whl")):
            continue
        subprocess.run(
            [str(driver), "--python", "3.11", "--abi", abi, str(recipe)],
            cwd=driver.parent,
            check=True,
        )
        for wheel in (driver.parent / "dist" / package).glob(f"*{abi.replace('-', '_')}.whl"):
            shutil.copy2(wheel, output / wheel.name)
