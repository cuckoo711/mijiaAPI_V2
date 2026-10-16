"""Close an observation review without clearing application data or resetting time."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen

from background_postflight import run_postflight


parser = argparse.ArgumentParser()
parser.add_argument('--serial', required=True)
parser.add_argument('--adb-server-port', type=int, default=5039)
parser.add_argument('--apk', type=Path, required=True)
parser.add_argument('--source-commit', required=True)
parser.add_argument('--snapshot', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--disposable', action='store_true', required=True)
args = parser.parse_args()
assert args.serial.startswith('emulator-')
out = args.output
out.mkdir(parents=True, exist_ok=True)
package = 'com.cuckoo.mijia.standalone'
adb = ['adb', '-P', str(args.adb_server_port), '-s', args.serial]
snapshot = json.loads(args.snapshot.read_text())
digest = hashlib.sha256(args.apk.read_bytes()).hexdigest()
assert snapshot['apk_sha256'] == digest and snapshot['commit'] == args.source_commit


def run(*command, check=True):
    result = subprocess.run(adb + list(command), capture_output=True, text=True, timeout=45)
    if check and result.returncode:
        raise RuntimeError(f'ADB {command[0]}: exit {result.returncode}: {result.stderr or result.stdout}')
    return result.stdout


def identity():
    pid = run('shell', 'pidof', package+':server').strip()
    assert pid.isdigit()
    stat = run('shell', 'cat', f'/proc/{pid}/stat').rsplit(')', 1)[1].split()
    return {'pid': pid, 'start_ticks': stat[19],
            'boot_id': run('shell', 'cat', '/proc/sys/kernel/random/boot_id').strip()}


expected = identity()
assert expected['pid'] == snapshot['initial_pid'] and expected['boot_id'] == snapshot['guest_boot_id']
installed = run('shell', 'pm', 'path', package).strip().removeprefix('package:')
assert installed.endswith('.apk') and '\n' not in installed
with tempfile.TemporaryDirectory(prefix='mijia-apk-review-') as directory:
    pulled = Path(directory)/'installed.apk'
    # Old adbd may misreport an existing file in the modern sync protocol.
    with pulled.open('wb') as target:
        subprocess.run(adb+['exec-out', 'cat', installed], stdout=target, check=True, timeout=90)
    assert hashlib.sha256(pulled.read_bytes()).hexdigest() == digest
report = {'passed': False, 'kind': 'observation_review_postflight',
          'api': snapshot['api'], 'page_size': snapshot['page_size'],
          'commit': args.source_commit, 'apk_sha256': digest, 'identity_before': expected,
          'started_utc': datetime.now(timezone.utc).isoformat(),
          'browser_login_navigation': snapshot['browser_login_navigation'],
          'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'shared_postflight_sha256': hashlib.sha256(Path(__file__).with_name('background_postflight.py').read_bytes()).hexdigest()}


def health():
    port = run('forward', 'tcp:0', 'tcp:8123').strip()
    try:
        with urlopen(f'http://127.0.0.1:{port}/readyz', timeout=6) as response:
            assert json.load(response)['status'] == 'ready'
        assert identity() == expected, 'Service identity changed during postflight'
    finally:
        run('forward', '--remove', 'tcp:'+port, check=False)
    return True


initial_idle = run('shell', 'dumpsys', 'deviceidle')
try:
    report['http_before_unlock'] = health()
    run_postflight(adb, run, health, report, out, package)
    # DOM inspection intentionally attaches instrumentation and restarts the
    # package after measuring identity; do not claim identity across that step.
    report['identity_verified_until_dom_inspection'] = True
    report['passed'] = all(report[key] for key in (
        'http_before_unlock', 'forced_idle_confirmed', 'network_before_idle',
        'user_exemption_flow', 'network_idle_exempted', 'http_idle_exempted',
        'http_after_unlock', 'console_after_unlock', 'console_rendered'))
except Exception as error:
    report['error'] = f'{type(error).__name__}: {error}'
    raise
finally:
    run('shell', 'dumpsys', 'deviceidle', 'unforce', check=False)
    run('shell', 'dumpsys', 'deviceidle', 'whitelist', '-'+package, check=False)
    if 'mDeepEnabled=false' in initial_idle:
        run('shell', 'dumpsys', 'deviceidle', 'disable', 'deep', check=False)
    if 'mLightEnabled=false' in initial_idle:
        run('shell', 'dumpsys', 'deviceidle', 'disable', 'light', check=False)
    run('shell', 'dumpsys', 'battery', 'reset', check=False)
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    (out/'postflight.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
assert report['passed']
