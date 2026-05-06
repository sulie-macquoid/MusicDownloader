from pathlib import Path
import traceback
import datetime
import importlib
import sys

ROOT = Path(__file__).resolve().parent
# Add ROOT to sys.path so .py files in Resources/ are found first
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG = ROOT / 'launcher.log'


def log(msg: str):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with LOG.open('a', encoding='utf-8') as f:
        f.write(f'[{timestamp}] {msg}\n')


def main():
    log('Launcher start')
    try:
        import webview  # noqa: F401
        log('Starting app_webview.py')
        app_webview = importlib.import_module('app_webview')
        app_webview.main()
        return
    except Exception:
        log('app_webview.py failed; falling back to app.py')
        log(traceback.format_exc())
 
    try:
        app = importlib.import_module('app')
        app.main()
    except Exception:
        log('app.py failed')
        log(traceback.format_exc())
        raise


if __name__ == '__main__':
    main()
