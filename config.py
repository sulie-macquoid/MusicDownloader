import json
from pathlib import Path
import os
import sys


def app_data_dir() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "sully's music downloader"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "sully's music downloader"
    else:
        root = Path.home() / ".sullys-music-downloader"
    root.mkdir(parents=True, exist_ok=True)
    return root


DEFAULTS = {
    "output_folder": "",
    "quality": "mp3_320",
    "dup_mode": "skip",
    "concurrency": 1,
    "embed_lyrics": False,
    "check_updates": True,
    "notifications": True,
    "theme": "system",
}

QUALITY_PRESETS = {
    "mp3_128": {"format": "mp3", "bitrate": "128"},
    "mp3_256": {"format": "mp3", "bitrate": "256"},
    "mp3_320": {"format": "mp3", "bitrate": "320"},
    "flac": {"format": "flac", "bitrate": ""},
    "mp4_360": {"format": "mp4", "resolution": "360"},
    "mp4_720": {"format": "mp4", "resolution": "720"},
    "mp4_1080": {"format": "mp4", "resolution": "1080"},
}

QUALITY_LABELS = {
    "mp3_128": "MP3 128kbps",
    "mp3_256": "MP3 256kbps",
    "mp3_320": "MP3 320kbps",
    "flac": "FLAC Lossless",
    "mp4_360": "MP4 360p",
    "mp4_720": "MP4 720p",
    "mp4_1080": "MP4 1080p",
}


class Config:
    def __init__(self, path: Path):
        self._path = path
        self._data = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                merged = dict(DEFAULTS)
                merged.update(saved)
                return merged
            except Exception:
                pass
        return dict(DEFAULTS)

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value

    def load(self) -> dict:
        return dict(self._data)
