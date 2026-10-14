"""Launch an owned disposable API 35 or 36 / 16 KiB image on the acceptance host."""
import argparse
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--sdk', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--api', type=int, choices=(35, 36), default=36)
parser.add_argument('--memory', type=int, default=4096)
parser.add_argument('--port', type=int, default=5584)
parser.add_argument('--adb-server-port', type=int, default=5037)
args = parser.parse_args()
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=True)
assert args.port % 2 == 0 and 5554 <= args.port <= 5584, 'Use an ADB-discoverable console port'
assert 1024 <= args.adb_server_port <= 65535
env = dict(os.environ, ANDROID_HOME=str(args.sdk), ANDROID_AVD_HOME=str(root/'avd'),
           ANDROID_ADB_SERVER_PORT=str(args.adb_server_port),
           ADB_SERVER_SOCKET=f'tcp:127.0.0.1:{args.adb_server_port}')
(root/'avd').mkdir(exist_ok=True)
name = f'mijia-acceptance-{args.api}-16k'
avd = root/'avd'/f'{name}.avd'
if not avd.exists():
    subprocess.run([str(args.sdk/'cmdline-tools/latest/bin/avdmanager'), 'create', 'avd',
                    '-n', name, '-k', f'system-images;android-{args.api};google_apis_ps16k;x86_64',
                    '-p', str(avd), '--device', 'pixel_2'],
                   input='no\n', text=True, env=env, check=True)
    with (avd/'config.ini').open('a') as config:
        config.write('\nhw.keyboard=yes\nhw.lcd.width=480\nhw.lcd.height=800\nhw.lcd.density=160\n')
with (root/'emulator.log').open('ab') as log:
    process = subprocess.Popen([str(args.sdk/'emulator/emulator'), '-avd', name,
                                '-no-window', '-no-audio', '-no-snapshot', '-gpu',
                                'swiftshader_indirect', '-memory', str(args.memory), '-cores', '2',
                                '-port', str(args.port), '-no-boot-anim'], env=env,
                               stdout=log, stderr=log, start_new_session=True)
(root/'emulator.pid').write_text(str(process.pid))
print(process.pid)
