#!/usr/bin/env bash
set -euo pipefail
aaa_tool_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x /root/autodl-tmp/aaa-bootstrap-py312/bin/python ]]; then
    aaa_python=/root/autodl-tmp/aaa-bootstrap-py312/bin/python
elif [[ -x /root/miniconda3/bin/python3 ]]; then
    aaa_python=/root/miniconda3/bin/python3
else
    echo 'Python not found. Use the Python interpreter from your AAA deployment.' >&2
    exit 1
fi
exec "$aaa_python" -B "$aaa_tool_dir/credential_help.py" "$@"
