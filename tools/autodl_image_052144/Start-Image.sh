#!/usr/bin/env bash
set -euo pipefail
if [[ -x /root/autodl-tmp/aaa-bootstrap-py312/bin/python ]]; then
    aaa_python=/root/autodl-tmp/aaa-bootstrap-py312/bin/python
elif [[ -x /root/miniconda3/bin/python3 ]]; then
    aaa_python=/root/miniconda3/bin/python3
else
    echo 'Python missing; use the supported AutoDL base image.' >&2
    exit 1
fi
if [[ ! -e /root/autodl-tmp/aaa-install ]]; then
    "$aaa_python" -B /opt/aaa-image-052144/first_boot.py --apply
fi
exec /root/autodl-tmp/aaa-bootstrap-py312/bin/python -B /opt/aaa-image-052144/first_boot.py --start
