#!/bin/sh
set -eu
cd "$(dirname "$0")"
BUILD_PYTHON=${BUILD_PYTHON:-python3.11}
"$BUILD_PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Android build requires Python 3.11"'
(cd ../web && npm ci && npm run build)
"$BUILD_PYTHON" prepare.py
"$BUILD_PYTHON" wheels/vendor.py
"$BUILD_PYTHON" verify_wheels.py
sh ./gradlew assembleDebug "-PbuildPython=$BUILD_PYTHON" --no-daemon
