"""Probe only the container's loopback service with either supported transport."""
import ssl
from urllib.request import urlopen

for scheme in ('https', 'http'):
    try:
        # The private self-signed certificate is generated on first container boot.
        with urlopen(f'{scheme}://127.0.0.1:8123/healthz', timeout=2,
                     context=ssl._create_unverified_context()) as response:
            if response.status == 200:
                raise SystemExit(0)
    except (OSError, ValueError):
        continue
raise SystemExit(1)
