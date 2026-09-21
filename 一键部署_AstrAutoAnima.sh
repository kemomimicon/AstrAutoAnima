#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
if ! command -v python3 >/dev/null 2>&1; then
    echo '需要 Python 3.12+。允许使用系统 apt 安装 python3、venv、tk、git？[y/N]'
    read -r answer
    if [ "$answer" != y ] || ! command -v apt-get >/dev/null 2>&1; then
        echo '已停止；请自行安装 Python 3.12+。'; exit 1
    fi
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-tk git
fi
exec python3 tools/deploy_project.py "$@"
