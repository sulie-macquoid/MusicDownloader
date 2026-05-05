from pathlib import Path
import traceback
import datetime
import importlib

ROOT = Path(__file__).resolve().parent
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
        log('app_webview.py failed; trying app_tk_pro.py')
        log(traceback.format_exc())

    try:
        log('Starting app_tk_pro.py')
        app_tk_pro = importlib.import_module('app_tk_pro')
        app_tk_pro.main()
        return
    except Exception:
        log('app_tk_pro.py failed; trying app_ctk.py')
        log(traceback.format_exc())

    try:
        import customtkinter  # noqa: F401
        log('Starting app_ctk.py')
        app_ctk = importlib.import_module('app_ctk')
        app_ctk.main()
        return
    except Exception:
        log('app_ctk.py failed; falling back to app.py')
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
