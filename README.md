# sully's music downloader

Free desktop app that:
- Accepts YouTube / YouTube Music / Spotify / Apple Music / mixed links.
- Auto-parses playlists/albums and single tracks.
- Builds an editable pre-download list for confirmation.
- Downloads as MP3 or MP4 (toggle in app).
- Preserves metadata for MP3 (artist/title/album/date + cover when available).
- Creates album/playlist folders automatically.
- Tracks duplicate downloads in SQLite and warns/skips (or force-downloads).
- Supports queueing and stop-download control.

## Important
Only download content you have rights to use.

## Quick Start (macOS, local dev)
```bash
cd "/Users/sulie/Documents/Music downloader"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install ffmpeg
python app_webview.py
```

## Build macOS .app
```bash
cd "/Users/sulie/Documents/Music downloader"
source .venv/bin/activate
./build_macos_app.sh
```
Output:
- `dist/sully's music downloader.app` (name comes from bundle metadata)

## Build Windows .exe
From Windows PowerShell:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --name "sully's music downloader" --noconfirm --windowed --onefile launcher.py
```
Output:
- `dist\sully's music downloader.exe`

Note:
- Keep `ui/index.html` bundled if switching to one-folder mode.
- For reliable ffmpeg usage on Windows, install ffmpeg and add to PATH.

## One-line installers (for GitHub releases)
After publishing releases, friends can install with:
- macOS:
```bash
curl -fsSL https://raw.githubusercontent.com/<OWNER>/<REPO>/main/scripts/install-macos.sh | bash
```
- Windows (PowerShell):
```powershell
iwr https://raw.githubusercontent.com/<OWNER>/<REPO>/main/scripts/install-windows.ps1 -UseBasicParsing | iex
```

## Packaging + Publish Guide
See:
- `docs/PUBLISHING.md`

# MusicDownloader
