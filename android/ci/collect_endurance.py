"""Publishable summary only after uninterrupted, completed 24-hour runs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from endurance_duration import validate_duration
from observation_evidence import analyze_samples

parser = argparse.ArgumentParser()
parser.add_argument('--apk', type=Path, required=True)
parser.add_argument('--reports', type=Path, nargs='+', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
digest = hashlib.sha256(args.apk.read_bytes()).hexdigest()
environments = {}
for path in args.reports:
    report = json.loads(path.read_text(encoding='utf-8'))
    assert report['passed'] and report['state'] == 'passed', f'Incomplete: {path}'
    assert report['apk_sha256'] == digest, 'APK mismatch'
    validate_duration(report)
    assert all(report[key] for key in ('console_after_unlock', 'background_passed',
                                      'forced_idle_confirmed', 'http_idle_exempted',
                                      'ui_process_termination_survived', 'ui_process_recreated'))
    samples = report['samples']
    assert analyze_samples(report)['unresolved_gap_count'] == 0
    key = f"{report['api']}-{report['page_size']}"
    assert key not in environments
    if report['page_size'] == 16384:
        assert report['page_size_backcompat_disabled']
    environments[key] = report
assert {'24-4096', '36-16384'} <= environments.keys(), 'Both old Android and 16 KiB runs required'
args.output.write_text(json.dumps({
    'passed': True, 'apk_sha256': digest, 'generated_utc': datetime.now(timezone.utc).isoformat(),
    'environments': environments,
    'limitations': ['Disposable emulators; x86_64 simulates 16 KiB userspace on 4 KiB kernel',
                    'Availability sampled every 30 seconds; not a continuous request stream',
                    'No physical ARM phones, OEM battery management, Xiaomi cloud or real device actions'],
}, indent=2), encoding='utf-8')
print(f'24-hour endurance passed: {sorted(environments)}; APK SHA256 {digest}')
