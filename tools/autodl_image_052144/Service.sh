#!/usr/bin/env bash
set -euo pipefail
aaa_tools="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec /root/autodl-tmp/aaa-bootstrap-py312/bin/python -B "$aaa_tools/service_control.py" "$@"
