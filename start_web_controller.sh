#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

if [ -x /userdata/.venv/bin/python ]; then
    exec /userdata/.venv/bin/python web_robot_controller.py "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 web_robot_controller.py "$@"
else
    echo "未找到可用的 Python 解释器" >&2
    exit 127
fi
