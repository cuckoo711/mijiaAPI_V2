"""Inspect every ELF, including Python extensions inside Chaquopy .imy ZIPs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile


def inspect_elf(data):
    bits, endian = data[4], data[5]
    assert endian == 1 and bits in (1, 2), 'Unsupported ELF encoding'
    machine = struct.unpack_from('<H', data, 18)[0]
    if bits == 2:
        offset = struct.unpack_from('<Q', data, 32)[0]
        size, count = struct.unpack_from('<HH', data, 54)
    else:
        offset = struct.unpack_from('<I', data, 28)[0]
        size, count = struct.unpack_from('<HH', data, 42)
    loads, relro = [], []
    for index in range(count):
        start = offset + index * size
        if bits == 2:
            kind, _, off, addr, _, _, mem, align = struct.unpack_from('<IIQQQQQQ', data, start)
        else:
            kind, off, addr, _, _, mem, _, align = struct.unpack_from('<IIIIIIII', data, start)
        if kind == 1:
            loads.append({'alignment': align, 'congruent': off % 16384 == addr % 16384})
        if kind == 0x6474e552:
            relro.append((addr + mem) % 16384 == 0)
    required = machine in (62, 183)
    aligned = bool(loads) and all(p['alignment'] >= 16384 and p['congruent'] for p in loads)
    return {'bits': 64 if bits == 2 else 32, 'machine': machine,
            'required_16k': required, 'load_segments': loads, 'relro_aligned': all(relro),
            # RELRO end is diagnostic: linkers may leave padding before the next
            # writable section. The runtime test verifies actual protection.
            'passed': not required or aligned}


def scan(path):
    records = []

    def visit(data, name, depth=0):
        if data.startswith(b'\x7fELF'):
            records.append({'path': name, **inspect_elf(data)})
        elif depth < 3 and data.startswith(b'PK\x03\x04'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for entry in archive.infolist():
                    if not entry.is_dir():
                        visit(archive.read(entry), name + '!' + entry.filename, depth + 1)

    visit(path.read_bytes(), path.name)
    assert records, 'No ELF libraries found'
    return {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'passed': all(r['passed'] for r in records), 'libraries': records}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.archive)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    failures = [r['path'] for r in result['libraries'] if not r['passed']]
    print(json.dumps({'passed': result['passed'], 'libraries': len(result['libraries']), 'failures': failures}))
    raise SystemExit(0 if result['passed'] else 1)
