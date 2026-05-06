import os
import plistlib
import sys
import stat
from pathlib import Path


def main():
    project_dir = Path(__file__).resolve().parent
    desktop = Path.home() / "Desktop"

    if sys.platform == "darwin":
        app_name = "Sully's Music Downloader"
        app_bundle = desktop / f"{app_name}.app"
        contents = app_bundle / "Contents"
        macos = contents / "MacOS"

        macos.mkdir(parents=True, exist_ok=True)

        info = {
            "CFBundleName": app_name,
            "CFBundleDisplayName": app_name,
            "CFBundleIdentifier": "com.sulie.sullysmusicdownloader.launcher",
            "CFBundleVersion": "1.0.0",
            "CFBundlePackageType": "APPL",
            "CFBundleSignature": "????",
            "CFBundleExecutable": "launch",
            "LSMinimumSystemVersion": "12.0",
        }
        with open(contents / "Info.plist", "wb") as f:
            plistlib.dump(info, f)

        launcher = macos / "launch"
        launcher.write_text(
            f'#!/bin/zsh\n'
            f'cd "{project_dir}" || exit 1\n'
            f'source .venv/bin/activate || exit 1\n'
            f'exec python launcher.py\n',
            encoding="utf-8",
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print(f"Created: {app_bundle}")

    elif sys.platform == "win32":
        shortcut = desktop / "Sully's Music Downloader.bat"
        shortcut.write_text(
            f'@echo off\n'
            f'cd /d "{project_dir}"\n'
            f'call .venv\\Scripts\\activate.bat\n'
            f'python launcher.py\n',
            encoding="utf-8",
        )
        print(f"Created: {shortcut}")

    else:
        print("Desktop shortcut creation is only supported on macOS and Windows.")
        return

    print("You can now launch the app from your Desktop.")


if __name__ == "__main__":
    main()
