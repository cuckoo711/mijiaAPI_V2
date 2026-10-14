"""Verify SDK, signatures and ABI contents; publish only tested APKs and evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
from check_page_size import scan

root = Path(__file__).resolve().parents[1]
output = root / 'build/release'
output.mkdir(parents=True, exist_ok=True)
tools = Path(os.environ['ANDROID_HOME']) / 'build-tools/35.0.0'
flavors = {'universal': {'armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64'},
           'arm32': {'armeabi-v7a'}, 'arm64': {'arm64-v8a'}, 'x86': {'x86'}, 'x64': {'x86_64'}}
certificates = set()
records = []
page_size_records = []
for flavor, abis in flavors.items():
    directory = root / f'app/build/outputs/apk/{flavor}/debug'
    metadata = json.loads((directory / 'output-metadata.json').read_text())['elements'][0]
    source = directory / metadata['outputFile']
    version = metadata['versionName']
    signature = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--print-certs', str(source)], text=True)
    certificate = next(line for line in signature.splitlines() if 'certificate SHA-256 digest:' in line)
    certificates.add(certificate)
    manifest = subprocess.check_output([str(tools / 'aapt'), 'dump', 'badging', str(source)], text=True)
    assert "sdkVersion:'24'" in manifest and "targetSdkVersion:'35'" in manifest
    subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(source)], check=True)
    alignment = scan(source)
    assert alignment['passed'], f'{flavor}: unaligned 64-bit ELF, including Python archives'
    page_size_records.append(alignment)
    with zipfile.ZipFile(source) as apk:
        native = {p.split('/')[1] for p in apk.namelist() if p.startswith('lib/') and p.endswith('.so')}
        python = {p.split('/')[-1][7:-4] for p in apk.namelist() if p.startswith('assets/chaquopy/stdlib-') and p.endswith('.imy')} - {'common'}
        assert native == abis and python == abis, (flavor, native, python)
    target = output / f'mijia-server-android-{flavor}-{version}.apk'
    shutil.copy2(source, target)
    records.append({'file': target.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                    'version': version, 'version_code': metadata['versionCode'], 'abis': sorted(abis)})
assert len(certificates) == 1
validation = root / 'build/validation/android-validation.json'
assert json.loads(validation.read_text())['passed']
shutil.copy2(validation, output / validation.name)
shutil.copy2(root / 'wheels/dist/compatibility-build.json', output / 'android-native-wheels.json')
(output / 'android-apk-verification.json').write_text(json.dumps({'apks': records, 'certificate': certificates.pop()}, indent=2))
(output / 'android-page-size.json').write_text(json.dumps({'passed': True, 'runtime_tested': False,
                                                         'apks': page_size_records}, indent=2))
(output / 'ANDROID_SHA256SUMS').write_text(''.join(
    f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in sorted(output.iterdir()) if p.is_file()))
