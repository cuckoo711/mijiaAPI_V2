"""Reject missing, corrupt, or mislabelled native Android wheels before APK assembly."""

import hashlib
import json
from pathlib import Path
import struct
import zipfile

root = Path(__file__).resolve().parent / "wheels/dist"
records = []
for abi, elf_class, machine in [("armeabi_v7a", 1, 40), ("arm64_v8a", 2, 183), ("x86_64", 2, 62)]:
    for package, version in [("pydantic_core", "2.46.4"), ("pycryptodome", "3.23.0")]:
        wheels = list(root.glob(f"{package}-{version}-*-cp311-cp311-android_24_{abi}.whl"))
        assert len(wheels) == 1, f"Expected exactly one {package} wheel for {abi}, got {wheels}"
        wheel = wheels[0]
        with zipfile.ZipFile(wheel) as archive:
            assert archive.testzip() is None, wheel.name
            native = [name for name in archive.namelist() if name.endswith(".so")]
            assert native, wheel.name
            for name in native:
                header = archive.read(name)[:20]
                assert header[:4] == b"\x7fELF" and header[4] == elf_class and header[5] == 1, (
                    wheel.name,
                    name,
                )
                assert struct.unpack("<H", header[18:20])[0] == machine, (wheel.name, name)
        records.append(
            {
                "wheel": wheel.name,
                "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "abi": abi,
                "elf_bits": 32 if elf_class == 1 else 64,
                "native_libraries": len(native),
            }
        )
(root / "compatibility-build.json").write_text(
    json.dumps({"passed": True, "runtime_tested": False, "wheels": records}, indent=2)
)
print(json.dumps(records, indent=2))
