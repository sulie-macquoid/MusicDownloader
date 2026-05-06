import json
from pathlib import Path

DEFAULTS = {
    "output_folder": "",
    "quality": "mp3_320",
    "format": "mp3",
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
