#!/bin/bash
# Probant, all-in-one version: double-click. Close the window (or Ctrl+C) to stop the tool.
cd "$(dirname "$0")" || exit 1
xattr -dr com.apple.quarantine . 2>/dev/null
if [ "$(uname -m)" = "arm64" ]; then PY="./system/python-mac-arm/bin/python3"; else PY="./system/python-mac-intel/bin/python3"; fi
chmod +x "$PY" 2>/dev/null
echo "Starting Probant, please wait (the first start takes a few minutes)..."
PYTHONPATH="$PWD/system/libs" PYTHONUTF8=1 "$PY" system/launch.py
