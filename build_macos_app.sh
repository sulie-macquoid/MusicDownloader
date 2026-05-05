#!/bin/zsh
set -e
cd "/Users/sulie/Documents/Music downloader"
source .venv/bin/activate
python setup_py2app.py py2app
