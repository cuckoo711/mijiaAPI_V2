"""Bounded recovery for metadata transport, never for application HTTP failures."""
from datetime import datetime, timezone
import subprocess
import time
import re


class TransportObservationError(RuntimeError):
    """Missing measurement; the application outcome is not known from this error."""


ALLOWED = {
    ('shell', 'cat', '/proc/sys/kernel/random/boot_id'),
    ('shell', 'cat', '/proc/uptime'),
    ('shell', 'pidof', 'com.cuckoo.mijia.standalone:server'),
    ('shell', 'dumpsys', 'power'),
    ('shell', 'dumpsys', 'deviceidle'),
    ('shell', 'dumpsys', 'activity', 'services', 'com.cuckoo.mijia.standalone'),
    ('forward', 'tcp:0', 'tcp:8123'),
}


def probe(adb, command, on_failure):
    command = tuple(command)
    process_stat = (len(command) == 3 and command[:2] == ('shell', 'cat')
                    and re.fullmatch(r'/proc/[1-9][0-9]*/stat', command[2]))
    assert command in ALLOWED or process_stat, 'Only explicit metadata reads and ephemeral HTTP transport setup may retry'
    for attempt in range(1, 4):
        record = {'command': list(command), 'attempt': attempt,
                  'utc': datetime.now(timezone.utc).isoformat(), 'will_retry': attempt < 3}
        try:
            result = subprocess.run(adb + list(command), capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
            record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        except subprocess.TimeoutExpired:
            record['error'] = 'transport_timeout_10s'
        on_failure(record)
        if attempt < 3:
            time.sleep(1)
    raise TransportObservationError(f'ADB probe failed after 3 attempts: {record}')
