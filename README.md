# Sully's Music Downloader

Free desktop app that:
- Accepts YouTube / YouTube Music / Spotify / Apple Music / mixed links.
- Auto-parses playlists/albums and single tracks.
- Builds an editable pre-download list for confirmation.
- Downloads as MP3 (128/256/320kbps), FLAC lossless, or MP4 (360p/720p/1080p).
- Preserves metadata for MP3/FLAC (artist/title/album/date + cover when available).
- Embeds lyrics automatically (optional, for popular tracks).
- Creates album/playlist folders automatically.
- Tracks duplicate downloads in SQLite and warns/skips (or force-downloads).
- Supports queueing, concurrent downloads (1-3 workers), and stop-download control.
- Auto-update checker with one-click update link.
- Desktop app (.app on macOS, .bat on Windows) with auto-setup.

## New Features (v1.0.0)

- **Quality selector**: Choose MP3 (128/256/320), FLAC, or MP4 (360/720/1080p) in Settings
- **Concurrent downloads**: Set 1-3 workers for faster batch downloads
- **Lyrics embedding**: Auto-fetch and embed lyrics (toggle in Settings)
- **Duplicate handling**: Skip duplicates or force re-download (configurable)
- **Progress bar**: Real-time download progress with percentage and title display
- **Scrollable logs**: Terminal panel auto-scrolls with manual scroll support
- **Editable preview**: Review and edit links before adding to queue
- **Theme support**: System/Dark/Light theme options
- **macOS desktop app**: One-click `.app` builder with automatic updates
- **Windows support**: Full PowerShell setup with desktop shortcut

## Important

Only download content you have rights to use.

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) (required for audio extraction and format conversion)

## Quick Start

### macOS

**Step 1 — Install prerequisites**
If you don't have Homebrew installed, run this in Terminal first:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```
Then install Git, Python, and ffmpeg:
```bash
brew install git python ffmpeg
```

**Step 2 — Get the code and run the app**
Open Terminal and paste the commands below one by one (press Enter after each):
```bash
# 1. Download the app
git clone https://github.com/sulie-macquoid/MusicDownloader.git

# 2. Go into the folder
cd MusicDownloader

# 3. Create a Python environment
python3 -m venv .venv

# 4. Activate it
source .venv/bin/activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Launch the app
python launcher.py
```
The app window will open. Paste any music link and click download.

**Step 3 — Create a Desktop launcher (optional)**
Run this once to put a clickable app on your Desktop:
```bash
python setup_desktop_shortcut.py
python build_macos_app.sh
```
> **Next time:** Just double-click **Sully's Music Downloader.app** on your Desktop.

---

### Windows

**Step 1 — Install prerequisites**
Open PowerShell as Administrator and run these commands one by one:

```powershell
# Install Git (for downloading the app)
winget install Git.Git

# Install Python
winget install Python.Python.3.12

# Install ffmpeg
winget install Gyan.FFmpeg
```
Close PowerShell and reopen it (not as Administrator) so the new tools are recognized.

**Step 2 — Get the code and run the app**
Open PowerShell and paste the commands below one by one (press Enter after each):
```powershell
# 1. Download the app
git clone https://github.com/sulie-macquoid/MusicDownloader.git

# 2. Go into the folder
cd MusicDownloader

# 3. Create a Python environment
python -m venv .venv

# 4. Activate it
.venv\Scripts\Activate.ps1
```
> **Note:** If you get a red error about "execution policy", run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` first, then try the activate command again.

```powershell
# 5. Install dependencies
pip install -r requirements.txt

# 6. Launch the app
python launcher.py
```
The app window will open. Paste any music link and click download.

**Step 3 — Create a Desktop launcher (optional)**
Run this once to put a clickable shortcut on your Desktop:
```powershell
python setup_desktop_shortcut.py
```
> **Next time:** Just double-click **Sully's Music Downloader.bat** on your Desktop.

---

### Linux

**Step 1 — Install prerequisites**
Open your terminal and install Git, Python, and ffmpeg:

Debian/Ubuntu:
```bash
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip ffmpeg
```

Fedora:
```bash
sudo dnf install -y git python3 python3-pip ffmpeg
```

Arch:
```bash
sudo pacman -S git python ffmpeg
```

**Step 2 — Get the code and run the app**
Open Terminal and paste the commands below one by one (press Enter after each):
```bash
# 1. Download the app
git clone https://github.com/sulie-macquoid/MusicDownloader.git

# 2. Go into the folder
cd MusicDownloader

# 3. Create a Python environment
python3 -m venv .venv

# 4. Activate it
source .venv/bin/activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Launch the app
python launcher.py
```
The app window will open. Paste any music link and click download.

> **Next time:** Open Terminal, run `cd ~/MusicDownloader && source .venv/bin/activate && python launcher.py`
