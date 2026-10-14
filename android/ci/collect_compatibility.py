"""Gate publication on the exact universal APK across the Android API matrix."""
import hashlib
import json
import os
from pathlib import Path

root = Path('android/build')
assets = root / 'release'
apk = next(assets.glob('*universal*.apk'))
digest = hashlib.sha256(apk.read_bytes()).hexdigest()
reports = {}
for path in (root / 'compatibility').glob('**/compatibility.json'):
    report = json.loads(path.read_text())
    api = report['api']
    assert api not in reports, f'Duplicate API {api}'
    assert report['passed'] and report['apk_sha256'] == digest
    assert report['commit'] == os.environ['GITHUB_SHA']
    assert report['screen_off_seconds'] >= 600
    if api >= 29:
        assert report['renderer_recovery'] == 'passed'
    assert all(report[key] for key in ['browser_login_navigation', 'console_rendered',
                                      'console_after_unlock', 'user_exemption_flow',
                                      'http_idle_exempted', 'forced_idle_confirmed'])
    reports[api] = report
assert set(reports) == {24, 31, 33, 34, 35, 36}, reports.keys()
(assets / 'android-compatibility.json').write_text(json.dumps({
    'passed': True, 'commit': os.environ['GITHUB_SHA'], 'apk_sha256': digest,
    'environments': reports,
    'limitations': ['Emulators with 4 KiB pages; no physical phones or OEM power managers',
                    'Ten-minute screen-off checks, not multi-day endurance',
                    'No real Xiaomi account or physical device control',
                    '16 KiB page-size devices not yet validated'],
}, indent=2))
(assets / 'ANDROID_SHA256SUMS').write_text(''.join(
    f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n'
    for p in sorted(assets.iterdir()) if p.is_file() and p.name != 'ANDROID_SHA256SUMS'))
