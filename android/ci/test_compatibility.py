"""Black-box foreground/UI/screen-off checks on disposable Android emulators.

No instrumentation remains attached during background measurements. Never run
against a user's phone: clearing the package and changing idle state are destructive.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socketserver
import subprocess
import threading
import time
from urllib.request import urlopen
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument('--serial', required=True)
parser.add_argument('--apk', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--seconds', type=int, default=600)
parser.add_argument('--disposable', action='store_true', required=True)
parser.add_argument('--expect-console', action='store_true')
parser.add_argument('--expect-exemption-ui', action='store_true')
parser.add_argument('--full-ui', action='store_true')
args = parser.parse_args()
assert args.serial.startswith('emulator-'), 'Disposable emulators only'
assert args.seconds >= 60
out = args.output
out.mkdir(parents=True, exist_ok=True)
adb = ['adb', '-s', args.serial]
package = 'com.cuckoo.mijia.standalone'

def run(*command, check=True):
    result = subprocess.run(adb + list(command), capture_output=True, text=True, timeout=45)
    if check and result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout

def hierarchy():
    run('shell', 'uiautomator', 'dump', '/sdcard/compat-ui.xml')
    return run('shell', 'cat', '/sdcard/compat-ui.xml')

def click_text(text, resource=None):
    document = ET.fromstring(hierarchy())
    for node in document.iter('node'):
        if (resource and node.get('resource-id', '').endswith(resource)) or (text and node.get('text') == text):
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds')))
            run('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
            return True
    return False

report = {'passed': False, 'serial': args.serial, 'samples': [],
          'commit': os.environ.get('GITHUB_SHA', ''),
          'apk_sha256': hashlib.sha256(args.apk.read_bytes()).hexdigest()}
initial_idle = run('shell', 'dumpsys', 'deviceidle')
try:
    report['api'] = int(run('shell', 'getprop', 'ro.build.version.sdk').strip())
    report['android'] = run('shell', 'getprop', 'ro.build.version.release').strip()
    page_size = run('shell', 'getconf', 'PAGE_SIZE', check=False).strip()
    if not page_size.isdigit():
        smaps = run('shell', 'cat', '/proc/self/smaps')
        page_size = str(int(re.search(r'KernelPageSize:\s+(\d+) kB', smaps).group(1))*1024)
    report['page_size'] = int(page_size)
    report['abis'] = run('shell', 'getprop', 'ro.product.cpu.abilist').strip()
    report['webview'] = run('shell', 'dumpsys', 'webviewupdate').strip()
    if report['api'] == 24:
        # Nougat's image also ships Chrome 69 as a WebView provider. Select the
        # factory WebView 53 so this job actually exercises the legacy bundle.
        run('shell', 'pm', 'disable-user', '--user', '0', 'com.android.chrome', check=False)
        run('shell', 'pm', 'enable', 'com.google.android.webview')
        selected = run('shell', 'cmd', 'webviewupdate', 'set-webview-implementation', 'com.google.android.webview')
        assert 'Success' in selected, selected
        report['legacy_provider_selected'] = 'com.google.android.webview'
    run('shell', 'input', 'keyevent', '224')
    run('shell', 'wm', 'dismiss-keyguard', check=False)
    run('shell', 'input', 'keyevent', '82')
    run('install', '-r', '-t', str(args.apk.resolve()))
    assert 'Success' in run('shell', 'pm', 'clear', package)
    if args.full_ui:
        instrument = subprocess.run(adb+['shell', 'am', 'instrument', '-w', package+'/.SmokeInstrumentation'],
                                    capture_output=True, text=True, timeout=360)
        (out/'webview-smoke.log').write_text(instrument.stdout+instrument.stderr)
        assert 'INSTRUMENTATION_CODE: -1' in instrument.stdout, instrument.stdout
        assert 'webview_login_navigation=passed' in instrument.stdout, instrument.stdout
        report['browser_login_navigation'] = True
        report['browser_user_agent'] = next(line.split('=', 1)[1] for line in instrument.stdout.splitlines()
                                          if line.startswith('INSTRUMENTATION_RESULT: webview_user_agent='))
        if report['api'] == 24:
            assert 'Chrome/53.' in report['browser_user_agent'], report['browser_user_agent']
        run('shell', 'am', 'force-stop', package)
        assert 'Success' in run('shell', 'pm', 'clear', package)
    run('shell', 'am', 'start', '-W', '-n', package + '/.MainActivity')
    time.sleep(3)
    assert click_text('启动服务')
    time.sleep(3)
    if report['api'] >= 33:
        click_text(None, 'permission_deny_button')
    def health():
        # Recreate a short-lived tunnel for every probe: an SDK client can reset
        # ADB forwarding while leaving the actual service/process unaffected.
        forwarded = run('forward', 'tcp:0', 'tcp:8123').strip()
        try:
            with urlopen(f'http://127.0.0.1:{forwarded}/readyz', timeout=6) as response:
                body = json.load(response)
                assert body['status'] == 'ready'
        finally:
            run('forward', '--remove', 'tcp:'+forwarded, check=False)
        return True

    deadline = time.monotonic()+150
    while True:
        try:
            health()
            break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
    report['service_started'] = True
    assert click_text('打开管理台')
    time.sleep(10)
    ui = hierarchy()
    (out/'console.xml').write_text(ui)
    with (out/'console.png').open('wb') as image:
        subprocess.run(adb+['exec-out', 'screencap', '-p'], stdout=image, check=True)
    report['console_accessibility_text'] = '创建管理员' in ui
    report['legacy_update_prompt'] = '请更新系统 WebView' in ui
    original_pid = run('shell', 'pidof', package).strip()
    report['initial_pid'] = original_pid
    # Remove the Activity from the foreground, unplug and explicitly sleep.
    run('shell', 'input', 'keyevent', '3')
    run('shell', 'dumpsys', 'battery', 'unplug')
    run('shell', 'settings', 'put', 'global', 'stay_on_while_plugged_in', '0')
    run('shell', 'input', 'keyevent', '223')
    started = time.monotonic()
    while True:
        sample = {'elapsed_seconds': round(time.monotonic()-started, 1)}
        try:
            sample['http_ready'] = health()
        except Exception as error:
            sample['http_ready'] = False
            sample['error'] = type(error).__name__
        sample['pid'] = run('shell', 'pidof', package).strip()
        report['samples'].append(sample)
        (out/'compatibility.json').write_text(json.dumps(report, indent=2))
        print(f"API {report['api']}: screen off {sample['elapsed_seconds']}s, HTTP={sample['http_ready']}, pid={sample['pid']}", flush=True)
        if time.monotonic()-started >= args.seconds:
            break
        time.sleep(min(30, args.seconds-(time.monotonic()-started)))
    report['screen_off_seconds'] = round(time.monotonic()-started, 1)
    power = run('shell', 'dumpsys', 'power')
    services = run('shell', 'dumpsys', 'activity', 'services', package)
    (out/'power.txt').write_text(power)
    (out/'services.txt').write_text(services)
    report['screen_off_confirmed'] = 'mWakefulness=Asleep' in power or 'mWakefulness=Dozing' in power
    report['foreground_service'] = 'isForeground=true' in services
    report['wake_lock_held'] = 'mijia:server' in power
    report['background_passed'] = all(s['http_ready'] and s['pid'] == original_pid for s in report['samples'])
    # Test the app UID's network access during forced idle using a controlled
    # local endpoint, without contacting Xiaomi or any external service.
    class Probe(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()
            self.wfile.write(b'compat-ok\n')
    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), Probe) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def network():
            script = f'echo compat | toybox nc -w 3 10.0.2.2 {server.server_address[1]}'
            return 'compat-ok' in run('shell', f'run-as {package} sh -c {shlex.quote(script)}', check=False)
        run('shell', 'input', 'keyevent', '224')
        run('shell', 'wm', 'dismiss-keyguard', check=False)
        run('shell', 'input', 'keyevent', '82')
        time.sleep(2)
        report['network_before_idle'] = network()
        run('shell', 'input', 'keyevent', '3')
        run('shell', 'input', 'keyevent', '223')
        report['idle_enable_result'] = run('shell', 'dumpsys', 'deviceidle', 'enable', check=False).strip()
        report['force_idle_result'] = run('shell', 'dumpsys', 'deviceidle', 'force-idle', check=False).strip()
        time.sleep(5)
        report['network_in_idle'] = network()
        idle = run('shell', 'dumpsys', 'deviceidle')
        (out/'idle-before-exemption.txt').write_text(idle)
        report['forced_idle_confirmed'] = 'mState=IDLE' in idle
        if args.expect_exemption_ui:
            run('shell', 'dumpsys', 'deviceidle', 'unforce', check=False)
            run('shell', 'input', 'keyevent', '224')
            run('shell', 'wm', 'dismiss-keyguard', check=False)
            run('shell', 'input', 'keyevent', '82')
            run('shell', 'am', 'start', '-W', '-n', package+'/.MainActivity')
            time.sleep(2)
            assert click_text('后台运行帮助')
            assert click_text('设置后台运行')
            time.sleep(2)
            (out/'battery-permission.xml').write_text(hierarchy())
            assert click_text(None, 'android:id/button1'), 'System battery exemption confirmation missing'
            time.sleep(2)
            whitelist = run('shell', 'dumpsys', 'deviceidle', 'whitelist')
            assert package in whitelist, 'System did not grant requested battery exemption'
            report['user_exemption_flow'] = True
            run('shell', 'input', 'keyevent', '3')
            run('shell', 'input', 'keyevent', '223')
            run('shell', 'dumpsys', 'deviceidle', 'force-idle')
        else:
            run('shell', 'dumpsys', 'deviceidle', 'whitelist', '+'+package)
            report['user_exemption_flow'] = False
        time.sleep(3)
        report['network_idle_exempted'] = network()
        report['http_idle_exempted'] = health()
        server.shutdown()
    run('shell', 'dumpsys', 'deviceidle', 'unforce', check=False)
    run('shell', 'dumpsys', 'battery', 'reset')
    run('shell', 'input', 'keyevent', '224')
    run('shell', 'wm', 'dismiss-keyguard', check=False)
    run('shell', 'am', 'start', '-W', '-n', package + '/.MainActivity')
    time.sleep(2)
    report['http_after_unlock'] = health()
    if args.expect_console:
        assert click_text('打开管理台')
        # Some system WebViews omit DOM children from accessibility snapshots.
        # Attach only after background sampling to read the actual DOM.
        inspected = subprocess.run(adb+['shell', 'am', 'instrument', '-w', '-e', 'mode', 'inspect',
                                        package+'/.SmokeInstrumentation'], capture_output=True, text=True, timeout=180)
        (out/'webview-after-unlock.log').write_text(inspected.stdout+inspected.stderr)
        report['console_after_unlock'] = 'INSTRUMENTATION_CODE: -1' in inspected.stdout and 'webview_ui=passed' in inspected.stdout
        assert report['console_after_unlock'], inspected.stdout
    report['console_rendered'] = bool(report.get('browser_login_navigation') and report.get('console_after_unlock'))
    report['passed'] = (report['background_passed'] and report['screen_off_confirmed']
                        and report['foreground_service'] and report['wake_lock_held']
                        and report['forced_idle_confirmed']
                        and report['network_before_idle'] and report['network_idle_exempted']
                        and (report['console_rendered'] or not args.expect_console))
finally:
    run('shell', 'dumpsys', 'deviceidle', 'unforce', check=False)
    run('shell', 'dumpsys', 'deviceidle', 'whitelist', '-'+package, check=False)
    if 'mDeepEnabled=false' in initial_idle:
        run('shell', 'dumpsys', 'deviceidle', 'disable', 'deep', check=False)
    if 'mLightEnabled=false' in initial_idle:
        run('shell', 'dumpsys', 'deviceidle', 'disable', 'light', check=False)
    run('shell', 'dumpsys', 'battery', 'reset', check=False)
    (out/'logcat.txt').write_text(run('logcat', '-d', '-t', '800', check=False))
    (out/'compatibility.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
assert report['passed'], 'Compatibility failed; see report and diagnostics'
