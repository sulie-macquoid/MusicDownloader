from setuptools import setup

APP = ['launcher.py']
DATA_FILES = [('ui', ['ui/index.html'])]
OPTIONS = {
    'argv_emulation': False,
    'iconfile': None,
    'packages': ['webview', 'customtkinter', 'yt_dlp', 'mutagen'],
    'includes': ['app', 'app_webview', 'app_tk_pro', 'app_ctk'],
    'plist': {
        'CFBundleName': "Sully's Music Downloader",
        'CFBundleDisplayName': "Sully's Music Downloader",
        'CFBundleIdentifier': 'com.sulie.sullysmusicdownloader',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '12.0',
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
