"""Regression checks for ELF validation inside Python archive assets."""
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from check_page_size import inspect_elf, scan


def elf(alignment, machine=183):
    data = bytearray(120)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, machine)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HH', data, 54, 56, 1)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0, 0, 0, 120, 120, alignment)
    return bytes(data)


class PageSizeTest(unittest.TestCase):
    def test_both_64_bit_machines_require_16k(self):
        for machine in (62, 183):
            self.assertFalse(inspect_elf(elf(4096, machine))['passed'])
            self.assertTrue(inspect_elf(elf(16384, machine))['passed'])

    def test_nested_python_extension_is_checked(self):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, 'w') as archive:
            archive.writestr('pydantic_core/native.so', elf(4096))
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory)/'app.apk'
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr('lib/arm64-v8a/runtime.so', elf(16384))
                archive.writestr('assets/chaquopy/requirements-arm64-v8a.imy', nested.getvalue())
            result = scan(apk)
            self.assertEqual(len(result['libraries']), 2)
            self.assertFalse(result['passed'])


if __name__ == '__main__':
    unittest.main()
