# Sully's Music Downloader

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

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) (required for audio extraction and format conversion)

## Quick Start

### macOS

```bash
# Clone the repo
git clone https://github.com/sulie-macquoid/MusicDownloader.git
cd MusicDownloader

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install ffmpeg
brew install ffmpeg

# Run the app
python launcher.py
```

### Windows

```powershell
# Clone the repo
git clone https://github.com/sulie-macquoid/MusicDownloader.git
cd MusicDownloader

# Set up virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Install ffmpeg (add to PATH)
# https://ffmpeg.org/download.html

# Run the app
python launcher.py
```

### Linux

```bash
git clone https://github.com/sulie-macquoid/MusicDownloader.git
cd MusicDownloader

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install ffmpeg (Debian/Ubuntu)
sudo apt install ffmpeg

# Run the app
python launcher.py
```

## Build Standalone App

### macOS (.app)

```bash
cd MusicDownloader
source .venv/bin/activate
./build_macos_app.sh
```

Output: `dist/Sully's Music Downloader.app`

### Windows (.exe)

```powershell
cd MusicDownloader
.venv\Scripts\Activate.ps1
pip install pyinstaller
pyinstaller --name "Sully's Music Downloader" --noconfirm --windowed --onefile launcher.py
```

Output: `dist\Sully's Music Downloader.exe`

> **Note:** Keep `ui/index.html` bundled if switching to one-folder mode.
> For reliable ffmpeg usage on Windows, install ffmpeg and add it to your PATH.

## One-Line Installers

After publishing releases, users can install with:

**macOS:**
```bash
curl -fsSL https://raw.githubusercontent.com/sulie-macquoid/MusicDownloader/main/scripts/install-macos.sh | bash
```

**Windows (PowerShell):**
```powershell
iwr https://raw.githubusercontent.com/sulie-macquoid/MusicDownloader/main/scripts/install-windows.ps1 -UseBasicParsing | iex
```

## Publishing Guide

See [docs/PUBLISHING.md](docs/PUBLISHING.md) for detailed packaging and release instructions.
