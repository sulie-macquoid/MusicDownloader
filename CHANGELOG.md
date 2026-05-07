# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- Cleaned up unused test files and libraries
- Removed unused npm packages: spotify-url-info, jsdom, puppeteer, puppeteer-extra, puppeteer-extra-plugin-stealth, node-fetch
- Removed unused Python packages: spotipy, requests-html, beautifulsoup4
- Updated README with complete setup instructions

### Removed
- Deleted unused test files: spotify_*.py, spotify_*.js, lib/*.js, test_spotify/
- Removed experimental metadata extractors that were never implemented

---

## [v1.1.0] - 2026-05-07

### Added
- **Spotify support** - Download from Spotify URLs (tracks, playlists, albums)
  - Requires free Spotify API credentials (one-time setup)
  - Uses `spotdl` library for reliable Spotify integration
- **Quality selector** - Choose download format in Settings:
  - MP3: 128kbps, 256kbps, 320kbps
  - FLAC: Lossless audio
  - MP4: 360p, 720p, 1080p video
- **Concurrent downloads** - Set 1-3 workers for faster batch downloads
- **Lyrics embedding** - Auto-fetch and embed lyrics (toggle in Settings)
- **Duplicate handling** - Skip duplicates or force re-download (configurable)
- **Progress bar** - Real-time download progress with percentage and title display
- **Scrollable logs** - Terminal panel auto-scrolls with manual scroll support
- **Editable preview** - Review and edit links before adding to queue
- **Theme support** - System/Dark/Light theme options
- **macOS desktop app** - One-click `.app` builder with automatic updates
- **Windows support** - Full PowerShell setup with desktop shortcut
- **Auto-update checker** - Notifies when new version is available

### Fixed
- Spotify metadata extraction now works with proper API credentials
- Better error handling for invalid URLs
- Improved download queue management

### Changed
- Updated `requirements.txt` with only necessary dependencies:
  - `spotdl>=4.4.4`
  - `yt-dlp>=2026.3.17`
  - `mutagen>=1.47.0`
  - `requests>=2.33.1`
- Simplified setup process with clear documentation

### Technical Details
- Spotify integration uses `spotdl` Python library
- Metadata extraction via Spotify Web API (requires free credentials)
- YouTube downloads handled by `yt-dlp`
- Audio conversion and metadata embedding via `ffmpeg` and `mutagen`
- GUI built with `tkinter` (Python standard library)

---

## [v1.0.0] - 2026 (Initial Release)

### Added
- Initial release with YouTube support
- Download single tracks and playlists from YouTube
- Basic MP3 download functionality
- Simple GUI interface
- SQLite database for tracking downloads
- Basic metadata embedding (title, artist, album)
- Cover art download and embedding
- Desktop launcher scripts for macOS and Windows

### Features
- Accepts YouTube URLs (individual tracks, playlists)
- Auto-parses playlists and albums
- Builds editable pre-download list
- Downloads as MP3 with metadata
- Preserves cover art
- Tracks duplicate downloads
- Supports queuing and stop/start control
