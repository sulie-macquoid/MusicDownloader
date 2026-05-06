from setuptools import setup

APP = ['launcher.py']
DATA_FILES = [
    ('ui', ['ui/index.html']),
    ('', ['app.py', 'app_webview.py', 'config.py']),
]
OPTIONS = {
    'argv_emulation': False,
    'iconfile': None,
    'packages': ['webview', 'yt_dlp', 'mutagen', 'certifi'],
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
