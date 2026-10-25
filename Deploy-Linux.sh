#!/bin/sh
set -eu
if [ "$(uname -s)" != Linux ]; then
    echo 'Use Deploy-Windows.cmd on Windows. This entry is for Linux.'; exit 1
fi
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
PYTHON=${AAA_PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo 'Python missing. Install Python 3.12 + venv, Git and curl using your distribution package manager.'; exit 1
fi
if [ "$#" -eq 0 ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    echo 'Headless Linux: copy examples/deployment-plan.linux.json and edit local paths/options.'
    echo 'Preflight: sh Deploy-Linux.sh --plan /absolute/path/my-plan.json'
    echo 'Install:   sh Deploy-Linux.sh --plan /absolute/path/my-plan.json --apply'
    echo 'NapCat: see docs/NAPCAT_SETUP.md (verified preparation, then interactive upstream installer).'
    exit 0
fi
exec "$PYTHON" tools/setup_center.py --platform linux "$@"
