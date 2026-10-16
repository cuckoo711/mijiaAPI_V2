"""Shared actual system-UI, Doze, network and unlock checks on disposable emulators."""
import re
import shlex
import socketserver
import subprocess
import threading
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET


def run_postflight(adb, run, health, report, out, package,
                   expect_exemption_ui=True, expect_console=True):
    args = SimpleNamespace(expect_exemption_ui=expect_exemption_ui, expect_console=expect_console)

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
            await_click('后台运行帮助')
            await_click('设置后台运行')
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
        await_click('打开管理台')
        # Some system WebViews omit DOM children from accessibility snapshots.
        # Attach only after background sampling to read the actual DOM.
        inspected = subprocess.run(adb+['shell', 'am', 'instrument', '-w', '-e', 'mode', 'inspect',
                                        package+'/.SmokeInstrumentation'], capture_output=True, text=True, timeout=180)
        (out/'webview-after-unlock.log').write_text(inspected.stdout+inspected.stderr)
        report['console_after_unlock'] = 'INSTRUMENTATION_CODE: -1' in inspected.stdout and 'webview_ui=passed' in inspected.stdout
        assert report['console_after_unlock'], inspected.stdout
    report['console_rendered'] = bool(report.get('browser_login_navigation') and report.get('console_after_unlock'))
