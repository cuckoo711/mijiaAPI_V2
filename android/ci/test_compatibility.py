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
from datetime import datetime, timezone
from urllib.request import urlopen
import xml.etree.ElementTree as ET
import adb_probe
from background_postflight import run_postflight
from observation_evidence import analyze_samples

parser = argparse.ArgumentParser()
parser.add_argument('--serial', required=True)
parser.add_argument('--adb-server-port', type=int, default=5037)
parser.add_argument('--apk', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--seconds', type=int, default=600)
parser.add_argument('--disposable', action='store_true', required=True)
parser.add_argument('--expect-console', action='store_true')
parser.add_argument('--expect-exemption-ui', action='store_true')
parser.add_argument('--full-ui', action='store_true')
parser.add_argument('--expect-page-size', type=int, choices=(4096, 16384))
args = parser.parse_args()
assert args.serial.startswith('emulator-'), 'Disposable emulators only'
assert args.seconds >= 60
out = args.output
out.mkdir(parents=True, exist_ok=True)
assert 1024 <= args.adb_server_port <= 65535
adb = ['adb', '-P', str(args.adb_server_port), '-s', args.serial]
package = 'com.cuckoo.mijia.standalone'
if args.expect_page_size == 16384:
    # Disable Android's 4 KiB backcompat fallback on this disposable userdebug
    # image. Root is only for system properties; the app keeps its normal UID.
    subprocess.run(adb+['root'], check=True, timeout=45)
    subprocess.run(adb+['wait-for-device'], check=True, timeout=90)
    for name, value in [('bionic.linker.16kb.app_compat.enabled', 'false'),
                        ('pm.16kb.app_compat.disabled', 'true')]:
        subprocess.run(adb+['shell', 'setprop', name, value], check=True, timeout=45)
        actual = subprocess.check_output(adb+['shell', 'getprop', name], text=True, timeout=45).strip()
        assert actual == value, 'Could not disable page-size backcompat fallback'
logcat_sink = (out/'logcat-full.txt').open('wb')
live_logcat = subprocess.Popen(adb+['logcat', '-v', 'threadtime', 'ActivityManager:I',
                                    'AndroidRuntime:E', 'MijiaServer:V', 'MijiaSmoke:V',
                                    'MijiaBrowser:V', 'libc:F', 'DEBUG:F', 'lmkd:I', '*:W'],
                               stdout=logcat_sink, stderr=subprocess.STDOUT)

def run(*command, check=True):
    result = subprocess.run(adb + list(command), capture_output=True, text=True, timeout=45)
    if check and result.returncode:
        raise RuntimeError(f'ADB {command[0]} failed (exit {result.returncode}): {result.stderr or result.stdout or "no output"}')
    return result.stdout

def probe(*command):
    return adb_probe.probe(adb, command, lambda failure: report.setdefault('transport_failures', []).append(failure))

def hierarchy():
    for attempt in range(3):
        # Some emulator builds exit nonzero after writing a complete snapshot.
        # Remove the prior file so only a freshly produced, valid XML is usable.
        run('shell', 'rm', '-f', '/sdcard/compat-ui.xml', check=False)
        dumped = subprocess.run(adb+['shell', 'uiautomator', 'dump', '/sdcard/compat-ui.xml'],
                                capture_output=True, text=True, timeout=45)
        xml = run('shell', 'cat', '/sdcard/compat-ui.xml', check=False)
        try:
            document = ET.fromstring(xml)
            assert document.tag == 'hierarchy'
            if dumped.returncode:
                report['snapshot_nonzero_with_valid_xml'] = report.get('snapshot_nonzero_with_valid_xml', 0)+1
                with (out/'snapshot-warnings.log').open('a') as diagnostics:
                    diagnostics.write(dumped.stdout+dumped.stderr)
            return xml
        except (ET.ParseError, AssertionError):
            time.sleep(1)
    raise RuntimeError('Unable to obtain a fresh valid UI snapshot')

def click_text(text, resource=None):
    document = ET.fromstring(hierarchy())
    for node in document.iter('node'):
        if node.get('enabled') == 'true' and ((resource and node.get('resource-id', '').endswith(resource)) or (text and node.get('text') == text)):
            x1, y1, x2, y2 = map(int, re.findall(r'\d+', node.get('bounds')))
            run('shell', 'input', 'tap', str((x1+x2)//2), str((y1+y2)//2))
            return True
    return False

def await_click(text):
    deadline = time.monotonic()+45
    while not click_text(text):
        if time.monotonic() >= deadline:
            (out/'missing-control.xml').write_text(hierarchy())
            raise AssertionError('Control not ready: '+text)
        time.sleep(1)

def health():
    forwarded = probe('forward', 'tcp:0', 'tcp:8123').strip()
    try:
        with urlopen(f'http://127.0.0.1:{forwarded}/readyz', timeout=6) as response:
            assert json.load(response)['status'] == 'ready'
    finally:
        run('forward', '--remove', 'tcp:'+forwarded, check=False)
    return True

report = {'passed': False, 'serial': args.serial, 'samples': [],
          'adb_server_port': args.adb_server_port,
          'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'harness_commit': os.environ.get('MIJIA_TEST_HARNESS_COMMIT', ''),
          'transport_helper_sha256': hashlib.sha256(Path(adb_probe.__file__).read_bytes()).hexdigest(),
          'state': 'preflight', 'requested_seconds': args.seconds,
          'commit': os.environ.get('GITHUB_SHA', ''),
          'apk_sha256': hashlib.sha256(args.apk.read_bytes()).hexdigest()}
initial_idle = probe('shell', 'dumpsys', 'deviceidle')
try:
    report['api'] = int(run('shell', 'getprop', 'ro.build.version.sdk').strip())
    report['android'] = run('shell', 'getprop', 'ro.build.version.release').strip()
    page_size = run('shell', 'getconf', 'PAGE_SIZE', check=False).strip()
    if not page_size.isdigit():
        smaps = run('shell', 'cat', '/proc/self/smaps')
        page_size = str(int(re.search(r'KernelPageSize:\s+(\d+) kB', smaps).group(1))*1024)
    report['page_size'] = int(page_size)
    report['page_size_backcompat_disabled'] = args.expect_page_size == 16384
    smaps = run('shell', 'cat', '/proc/self/smaps')
    report['kernel_page_sizes_kib'] = sorted({int(value) for value in re.findall(r'KernelPageSize:\s+(\d+) kB', smaps)})
    # x86_64 Google's 16 KiB image simulates 16 KiB userspace on a 4 KiB kernel.
    # Preserve both facts rather than describing it as an ARM 16 KiB kernel.
    report['page_size_environment'] = ('simulated_16k_userspace' if report['page_size'] == 16384
                                      and 16 not in report['kernel_page_sizes_kib'] else 'kernel_pages')
    if args.expect_page_size:
        assert report['page_size'] == args.expect_page_size, 'Unexpected kernel page size'
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
        for attempt in range(3):
            log_offset = (out/'logcat-full.txt').stat().st_size
            instrument = subprocess.run(adb+['shell', 'am', 'instrument', '-w', package+'/.SmokeInstrumentation'],
                                        capture_output=True, text=True, timeout=360)
            (out/f'webview-smoke-attempt-{attempt}.log').write_text(instrument.stdout+instrument.stderr)
            if 'INSTRUMENTATION_CODE: -1' in instrument.stdout:
                break
            time.sleep(1)
            recent = (out/'logcat-full.txt').read_bytes()[log_offset:].decode('utf-8', errors='replace')
            provider_exit = [line for line in recent.splitlines() if f':{package}/' in line
                             and 'depends on provider' in line and 'FontsProvider' in line]
            # Fresh Google API images refresh their font provider once. The UI
            # runner can be killed by Android, but the independent server must
            # still be healthy. Retry only that evidenced platform event.
            if 'Process crashed' not in instrument.stdout or not provider_exit or not health():
                break
            report.setdefault('font_provider_fixture_retries', []).append(provider_exit)
            run('shell', 'am', 'force-stop', package)
            assert 'Success' in run('shell', 'pm', 'clear', package)
            time.sleep(5)
        (out/'webview-smoke.log').write_text(instrument.stdout+instrument.stderr)
        assert 'INSTRUMENTATION_CODE: -1' in instrument.stdout, instrument.stdout
        assert 'webview_login_navigation=passed' in instrument.stdout, instrument.stdout
        report['browser_login_navigation'] = True
        report['renderer_recovery'] = 'passed' if 'renderer_recovery=passed' in instrument.stdout else 'unavailable'
        if report['api'] >= 29:
            assert report['renderer_recovery'] == 'passed', instrument.stdout
        report['browser_user_agent'] = next(line.split('=', 1)[1] for line in instrument.stdout.splitlines()
                                          if line.startswith('INSTRUMENTATION_RESULT: webview_user_agent='))
        if report['api'] == 24:
            assert 'Chrome/53.' in report['browser_user_agent'], report['browser_user_agent']
        run('shell', 'am', 'force-stop', package)
        assert 'Success' in run('shell', 'pm', 'clear', package)
    run('shell', 'am', 'start', '-W', '-n', package + '/.MainActivity')
    time.sleep(3)
    await_click('启动服务')
    time.sleep(3)
    if report['api'] >= 33:
        click_text(None, 'permission_deny_button')
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
    await_click('打开管理台')
    time.sleep(10)
    ui = hierarchy()
    (out/'console.xml').write_text(ui)
    with (out/'console.png').open('wb') as image:
        subprocess.run(adb+['exec-out', 'screencap', '-p'], stdout=image, check=True)
    report['console_accessibility_text'] = '创建管理员' in ui
    report['legacy_update_prompt'] = '请更新系统 WebView' in ui
    original_pid = probe('shell', 'pidof', package+':server').strip()
    report['process_start_ticks'] = probe('shell', 'cat', f'/proc/{original_pid}/stat').rsplit(')', 1)[1].split()[19]
    assert original_pid.isdigit(), 'Expected one dedicated server process'
    report['initial_pid'] = original_pid
    report['background_process'] = package+':server'
    ui_pid = run('shell', 'pidof', package).strip()
    assert ui_pid.isdigit() and ui_pid != original_pid
    report['initial_ui_pid'] = ui_pid
    # Kill only the UI process, as Android may do after a font/provider failure.
    # No package-wide force-stop: the dedicated foreground service must survive.
    run('shell', 'input', 'keyevent', '3')
    remaining_ui = [ui_pid]
    for attempt in range(5):
        # am kill reclaims only safe background processes. Unlike force-stop it
        # leaves the foreground :server process running, with no root required.
        run('shell', 'am', 'kill', '--user', '0', package)
        time.sleep(2)
        remaining_ui = run('shell', 'pidof', package, check=False).strip().split()
        if ui_pid not in remaining_ui:
            break
    assert ui_pid not in remaining_ui, 'The original UI process is still running'
    report['ui_termination_method'] = 'activity_manager_background_reclamation'
    report['ui_process_termination_survived'] = health() and probe('shell', 'pidof', package+':server').strip() == original_pid
    assert report['ui_process_termination_survived']
    run('shell', 'am', 'start', '-W', '-n', package+'/.MainActivity')
    await_click('打开管理台')
    report['ui_process_recreated'] = run('shell', 'pidof', package).strip() != ui_pid
    assert report['ui_process_recreated']
    # Remove the Activity from the foreground, unplug and explicitly sleep.
    run('shell', 'input', 'keyevent', '3')
    run('shell', 'dumpsys', 'battery', 'unplug')
    run('shell', 'settings', 'put', 'global', 'stay_on_while_plugged_in', '0')
    run('shell', 'input', 'keyevent', '223')
    boot_id = probe('shell', 'cat', '/proc/sys/kernel/random/boot_id').strip()
    report['guest_boot_id'] = boot_id
    report['guest_uptime_at_start'] = float(probe('shell', 'cat', '/proc/uptime').split()[0])
    started = time.monotonic()
    report['state'] = 'screen_off_running'
    report['screen_off_started_utc'] = datetime.now(timezone.utc).isoformat()
    previous_uptime = 0.0
    pending_gaps = []
    while True:
        sample = {'elapsed_seconds': round(time.monotonic()-started, 1),
                  'utc': datetime.now(timezone.utc).isoformat()}
        try:
            try:
                sample['http_ready'] = health()
            except adb_probe.TransportObservationError:
                raise
            except Exception as error:
                sample.update(http_ready=False, error=type(error).__name__)
            sample['pid'] = probe('shell', 'pidof', package+':server').strip()
            sample['boot_id'] = probe('shell', 'cat', '/proc/sys/kernel/random/boot_id').strip()
            assert sample['pid'] == original_pid, 'Service process changed'
            assert sample['boot_id'] == boot_id, 'Guest restarted'
            sample['process_start_ticks'] = probe('shell', 'cat', f'/proc/{original_pid}/stat').rsplit(')', 1)[1].split()[19]
            sample['guest_uptime'] = float(probe('shell', 'cat', '/proc/uptime').split()[0])
            power = probe('shell', 'dumpsys', 'power')
            sample['screen_off'] = 'mWakefulness=Asleep' in power or 'mWakefulness=Dozing' in power
            sample['wake_lock'] = 'mijia:server' in power
            sample['kind'] = 'healthy'
        except adb_probe.TransportObservationError as error:
            # Keep elapsed time and disclose the gap. Only a subsequent matching
            # boot/PID/start-time fingerprint can support process continuity.
            sample.update(kind='observation_gap', reason_category='adb_transport',
                          error=str(error), continuity='unresolved',
                          http_availability='observed_ready' if sample.get('http_ready') is True else 'unobserved')
            pending_gaps.append(len(report['samples']))
        except AssertionError as error:
            sample.update(kind='application_incident', error=str(error))
            report['samples'].append(sample)
            raise
        report['samples'].append(sample)
        if sample.get('http_ready') is False:
            report['application_incident'] = 'HTTP readiness failed; investigate before deciding any retest'
        if sample['kind'] == 'healthy':
            assert sample['http_ready'] and sample['pid'] == original_pid, 'Application HTTP or service identity changed'
            assert sample['boot_id'] == boot_id and sample['guest_uptime'] >= previous_uptime, 'Guest rebooted'
            assert sample['process_start_ticks'] == report['process_start_ticks'], 'PID was reused'
            assert sample['screen_off'] and sample['wake_lock'], 'Screen or wake lock changed'
            previous_uptime = sample['guest_uptime']
            for index in pending_gaps:
                report['samples'][index].update(continuity='process_identity_confirmed', recovered_utc=sample['utc'])
            pending_gaps.clear()
        checkpoint = out/'compatibility.pending.json'
        checkpoint.write_text(json.dumps(report, indent=2), encoding='utf-8')
        checkpoint.replace(out/'compatibility.json')
        print(f"API {report['api']}: {sample['kind']} at {sample['elapsed_seconds']}s, HTTP={sample.get('http_ready')}, pid={sample.get('pid')}", flush=True)
        assert sample.get('http_ready') is not False, 'Application HTTP failed; requires review'
        if time.monotonic()-started >= args.seconds and sample['kind'] == 'healthy':
            break
        remaining = args.seconds-(time.monotonic()-started)
        time.sleep(min(30, remaining) if remaining > 0 else 30)
    report['screen_off_seconds'] = round(time.monotonic()-started, 1)
    report['screen_off_finished_utc'] = datetime.now(timezone.utc).isoformat()
    report['state'] = 'postflight'
    power = probe('shell', 'dumpsys', 'power')
    services = probe('shell', 'dumpsys', 'activity', 'services', package)
    (out/'power.txt').write_text(power)
    (out/'services.txt').write_text(services)
    report['screen_off_confirmed'] = 'mWakefulness=Asleep' in power or 'mWakefulness=Dozing' in power
    report['foreground_service'] = 'isForeground=true' in services
    report['wake_lock_held'] = 'mijia:server' in power
    report['observation_summary'] = analyze_samples(report)
    report['background_passed'] = report['observation_summary']['unresolved_gap_count'] == 0
    run_postflight(adb, run, health, report, out, package, args.expect_exemption_ui, args.expect_console)
    report['passed'] = (report['background_passed'] and report['screen_off_confirmed']
                        and report['foreground_service'] and report['wake_lock_held']
                        and report['forced_idle_confirmed']
                        and report['network_before_idle'] and report['network_idle_exempted']
                        and (report['console_rendered'] or not args.expect_console))
except Exception as error:
    report['error'] = f'{type(error).__name__}: {error}'
    raise
finally:
    report['state'] = 'passed' if report['passed'] else 'failed'
    try:
        run('shell', 'dumpsys', 'deviceidle', 'unforce', check=False)
        run('shell', 'dumpsys', 'deviceidle', 'whitelist', '-'+package, check=False)
        if 'mDeepEnabled=false' in initial_idle:
            run('shell', 'dumpsys', 'deviceidle', 'disable', 'deep', check=False)
        if 'mLightEnabled=false' in initial_idle:
            run('shell', 'dumpsys', 'deviceidle', 'disable', 'light', check=False)
        run('shell', 'dumpsys', 'battery', 'reset', check=False)
        (out/'logcat.txt').write_text(run('logcat', '-d', '-t', '800', check=False))
    except Exception as error:
        report['cleanup_error'] = type(error).__name__
        report['passed'] = False
    live_logcat.terminate()
    try:
        live_logcat.wait(timeout=5)
    except subprocess.TimeoutExpired:
        live_logcat.kill()
        live_logcat.wait()
    logcat_sink.close()
    (out/'compatibility.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
assert report['passed'], 'Compatibility failed; see report and diagnostics'
