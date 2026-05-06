# Publishing Guide

## 1) Create GitHub repo
1. Create a new GitHub repository (recommended name: `sullys-music-downloader`).
2. In project folder:
```bash
git init
git add .
git commit -m "Initial release: sully's music downloader"
git branch -M main
git remote add origin https://github.com/<OWNER>/<REPO>.git
git push -u origin main
```

## 2) Build release artifacts

### macOS `.app`
```bash
source .venv/bin/activate
./build_macos_app.sh
```
Artifact to upload:
- `dist/Sully's Music Downloader.app` (zip it first for upload)

### Windows `.exe`
On Windows machine:
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install pyinstaller
pyinstaller --name "Sully's Music Downloader" --noconfirm --windowed --onefile launcher.py
```
Artifact to upload:
- `dist\Sully's Music Downloader.exe`

## 3) Create a GitHub Release
1. Go to GitHub repo -> `Releases` -> `Draft a new release`.
2. Tag example: `v1.0.0`.
3. Upload:
   - `sullys-music-downloader-macos.zip` (contains `.app`)
   - `sullys-music-downloader-windows.exe`
4. Publish release.

## 4) Enable one-line installers
Edit the installer scripts in `scripts/`:
- Replace `<OWNER>` and `<REPO>`.
- Replace `v1.0.0` with latest release tag.

Then users can run:
- macOS:
```bash
curl -fsSL https://raw.githubusercontent.com/<OWNER>/<REPO>/main/scripts/install-macos.sh | bash
```
- Windows:
```powershell
iwr https://raw.githubusercontent.com/<OWNER>/<REPO>/main/scripts/install-windows.ps1 -UseBasicParsing | iex
```
