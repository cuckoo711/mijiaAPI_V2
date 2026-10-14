"""Stage only application sources and built UI; never include operator data."""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess

root = Path(__file__).resolve().parent.parent
target = root / "android/app/build/generated/python"
assert target.resolve().is_relative_to((root / "android/app/build").resolve())
assert not target.is_symlink()
if target.exists():
    shutil.rmtree(target)
target.mkdir(parents=True, exist_ok=True)
for package in ("server", "mijiaAPI_V2"):
    for source in (root / package).rglob("*.py"):
        relative = source.relative_to(root)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
bundle = target / "mijia_android"
bundle.mkdir(exist_ok=True)
assert (root / "web/dist/index.html").is_file(), "Run npm ci && npm run build in web first"
shutil.copytree(root / "web/dist", bundle / "ui", dirs_exist_ok=True)
(bundle / "assets").mkdir(exist_ok=True)
shutil.copy2(root / "configs/server.toml.template", bundle / "assets/server.toml.template")
for name in ("LICENSE", "NOTICE", "DISCLAIMER.md"):
    if (root / name).is_file():
        shutil.copy2(root / name, bundle / "assets" / name)
manifest = {
    p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(target.rglob("*"))
    if p.is_file()
}
info = {
    "base_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip(),
    "source_tree_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
    "files": manifest,
}
(bundle / "assets/build-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
print(f"Staged application and frontend in {target}")
