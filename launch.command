#!/bin/zsh
cd "/Users/sulie/Documents/Music downloader" || exit 1
source .venv/bin/activate || exit 1
exec python launcher.py
