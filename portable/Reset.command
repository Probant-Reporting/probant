#!/bin/bash
# Back to the starting point (deletes your trials): the tool restores its initial backup, or prepares the demo again.
cd "$(dirname "$0")" || exit 1
if [ "$(uname -m)" = "arm64" ]; then PY="./system/python-mac-arm/bin/python3"; else PY="./system/python-mac-intel/bin/python3"; fi
PYTHONPATH="$PWD/system/libs" PYTHONUTF8=1 "$PY" system/launch.py --reset
