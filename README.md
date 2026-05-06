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

> **Next time:** Open Terminal, run `cd ~/MusicDownloader && source .venv/bin/activate && python launcher.py`

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

> **Next time:** Open PowerShell, run `cd MusicDownloader`, then `.venv\Scripts\Activate.ps1`, then `python launcher.py`

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
