"""Prepare pinned sources and Python targets for a clean Linux CI runner."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

root = Path(__file__).resolve().parents[1]
work = root / 'build/native'
work.mkdir(parents=True, exist_ok=True)
chaquopy = work / 'chaquopy'
revision = '884ec5f14591d69844e20c9dc6a6a9c5d1ba0a41'
if not chaquopy.exists():
    subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout',
                    'https://github.com/chaquo/chaquopy.git', str(chaquopy)], check=True)
subprocess.run(['git', 'checkout', '--force', revision], cwd=chaquopy, check=True)
for item in json.loads((root / 'ci/inputs.json').read_text()):
    archive = work / item['file']
    if not archive.exists():
        with urllib.request.urlopen(item['url'], timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == item['sha256'], archive
    if archive.suffix == '.zip':
        target = chaquopy / 'maven/com/chaquo/python/target/3.11.17-0'
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, target / archive.name)
    else:
        package = 'pydantic-core' if archive.name.startswith('pydantic') else 'pycryptodome'
        target = work / 'sources' / package
        if not target.exists():
            extracted = work / ('extract-' + package)
            extracted.mkdir(exist_ok=True)
            with tarfile.open(archive) as source:
                source.extractall(extracted, filter='data')
            shutil.move(str(next(extracted.iterdir())), str(target))
