#!/bin/zsh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
pip install --upgrade setuptools pip > /dev/null 2>&1 || true
.venv/bin/python3 setup_py2app.py py2app
