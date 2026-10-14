"""Test all APK flavors on a disposable emulator and collect release evidence."""
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
out = root / 'build/validation'
out.mkdir(parents=True, exist_ok=True)
adb = ['adb', '-s', os.environ.get('ANDROID_SERIAL', 'emulator-5554')]
package = 'com.cuckoo.mijia.standalone'
def run(*args):
    return subprocess.check_output(adb + list(args), text=True, timeout=300)

reports = {}
for flavor in ['x86', 'x64', 'arm32', 'arm64', 'universal']:
    run('shell', 'am', 'force-stop', package)
    run('install', '-r', '-t', str(root / f'app/build/outputs/apk/{flavor}/debug/app-{flavor}-debug.apk'))
    assert 'Success' in run('shell', 'pm', 'clear', package)
    log = run('shell', 'am', 'instrument', '-w', package + '/.SmokeInstrumentation')
    (out / f'smoke-{flavor}.log').write_text(log)
    assert 'INSTRUMENTATION_CODE: -1' in log and 'webview_ui=passed' in log, log
    assert 'webview_login_navigation=passed' in log, log
    assert 'renderer_recovery=passed' in log or 'renderer_recovery=in_process_webview' in log, log
    reports[flavor] = {}
    for name, filename in [('runtime', 'android-smoke.json'), ('restart', 'android-restart-smoke.json')]:
        content = run('shell', 'run-as', package, 'cat', 'files/service/' + filename)
        (out / f'{name}-{flavor}.json').write_text(content)
        report = json.loads(content)
        assert report['passed'], report
        reports[flavor][name] = report
    reports[flavor]['webview_ui'] = 'passed'
    reports[flavor]['webview_login_navigation'] = 'passed'
    reports[flavor]['renderer_recovery'] = 'passed' if 'renderer_recovery=passed' in log else 'in_process_webview'
report = {
    'passed': True,
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    'android_api': run('shell', 'getprop', 'ro.build.version.sdk').strip(),
    'emulator_abis': run('shell', 'getprop', 'ro.product.cpu.abilist').strip(),
    'arm_execution': 'Android native bridge translation, not ARM hardware',
    'limitations': ['No physical phone testing', 'No real Xiaomi account or device control',
                    'Per-API background checks are recorded separately in android-compatibility.json',
                    'No multi-day screen-off endurance test'],
    'flavors': reports,
}
(out / 'android-validation.json').write_text(json.dumps(report, indent=2))
