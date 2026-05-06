import os
import re
import sqlite3
import threading
import urllib.parse
import urllib.request
import json
import ssl
import shutil
import subprocess
from html import unescape
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

# Fix SSL certificate verification on macOS
if sys.platform == "darwin":
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        ssl._create_default_https_context = ssl._create_unverified_context

# Only import tkinter if running directly (not imported by app_webview)
if __name__ == "__main__":
    from tkinter import END, StringVar, BooleanVar, IntVar, Tk, Toplevel, filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

# Fix SSL certificate verification on macOS
if sys.platform == "darwin":
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        ssl._create_default_https_context = ssl._create_unverified_context

import yt_dlp
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TXXX, USLT
from mutagen.flac import FLAC, Picture
from mutagen import File as MutagenFile

from config import Config, DEFAULTS, QUALITY_PRESETS

try:
    from config import app_data_dir as _cfg_app_data_dir
except ImportError:
    _cfg_app_data_dir = None


def app_data_dir() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "sully's music downloader"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "sully's music downloader"
    else:
        root = Path.home() / ".sullys-music-downloader"
    root.mkdir(parents=True, exist_ok=True)
    return root


DB_PATH = app_data_dir() / "downloads.db"
CONFIG_PATH = app_data_dir() / "config.json"
YOUTUBE_HOST_MARKERS = ("youtube.com", "youtu.be", "music.youtube.com")
REPO_URL = "https://api.github.com/repos/sulie-macquoid/MusicDownloader/releases/latest"
GITHUB_REPO_URL = "https://github.com/sulie-macquoid/MusicDownloader"
CURRENT_VERSION = "1.0.0"


class DownloadState(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class TrackInfo:
    video_id: str
    title: str
    artist: str
    uploader: str
    upload_date: str
    duration: int
    webpage_url: str


@dataclass
class MusicQuery:
    title: str
    artist: str
    source_url: str
    album: str = ""
    release_date: str = ""
    artwork_url: str = ""


@dataclass
class DownloadTask:
    youtube_url: str
    source_input_url: str
    source_query: MusicQuery | None = None
    collection_name: str = ""
    display_title: str = ""
    group_name: str = ""


@dataclass
class QueuedTask:
    task: DownloadTask
    state: DownloadState = DownloadState.PENDING
    event: threading.Event = field(default_factory=threading.Event)


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (title or "").lower())).strip()


def clean_song_title(raw_title: str, artist_hint: str = "") -> str:
    title = (raw_title or "").strip()
    if not title:
        return "Unknown Title"

    title = re.sub(r"\s*\[[^\]]+\]\s*$", "", title, flags=re.IGNORECASE)

    if artist_hint and title.lower().startswith(artist_hint.lower() + " - "):
        title = title[len(artist_hint) + 3 :].strip()
    elif " - " in title:
        parts = [p.strip() for p in title.split(" - ", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            if len(parts[0].split()) <= 6:
                title = parts[1]

    noise = (
        r"official video|official visualizer|official audio|audio only|lyric video|lyrics|"
        r"music video|visualizer|mv|hd|4k|topic"
    )
    # Remove noise in parentheses: "Song (4K) - Channel" -> "Song  - Channel"
    title = re.sub(rf"\s*\((?:{noise})[^)]*\)", " ", title, flags=re.IGNORECASE)
    # Remove noise in brackets: "Song [Official Video]" -> "Song "
    title = re.sub(rf"\s*\[(?:{noise})[^\]]*\]", " ", title, flags=re.IGNORECASE)
    # Remove trailing noise after dash: "Song - topic" -> "Song"
    title = re.sub(rf"\s*-\s*(?:{noise}).*$", "", title, flags=re.IGNORECASE)
    # Clean up "Song  - Channel" -> "Song - Channel" then split properly
    title = re.sub(r"\s+", " ", title)
    # Now handle "Song - Channel" pattern - if channel name is long, title is second part
    if " - " in title:
        parts = [p.strip() for p in title.split(" - ", 1)]
        if len(parts) == 2:
            # If first part looks like a channel name (many words) and second part is short, swap
            if len(parts[0].split()) > 3 and len(parts[1].split()) <= 6:
                title = parts[1]
            elif len(parts[0].split()) <= 6:
                title = parts[1]

    title = re.sub(r"\s+", " ", title).strip(" -_.,")
    return title or "Unknown Title"


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or "Unknown Title"


def unique_media_path(output_dir: Path, title: str, ext: str) -> Path:
    base = safe_filename(title)
    candidate = output_dir / f"{base}.{ext}"
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        alt = output_dir / f"{base} ({i}).{ext}"
        if not alt.exists():
            return alt
        i += 1


def detect_ffmpeg_location() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    if sys.platform == "darwin":
        for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
            if Path(candidate).exists():
                return str(Path(candidate).parent)
    elif sys.platform == "win32":
        pf = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        for candidate in [Path(pf) / "ffmpeg" / "bin" / "ffmpeg.exe", Path(pf) / "ffmpeg" / "ffmpeg.exe"]:
            if candidate.exists():
                return str(candidate.parent)
    return ""


def pick_artist(info: dict) -> str:
    return (
        info.get("artist")
        or info.get("album_artist")
        or info.get("uploader")
        or info.get("channel")
        or "Unknown Artist"
    )


def make_track(info: dict) -> TrackInfo:
    return TrackInfo(
        video_id=info.get("id", ""),
        title=clean_song_title(info.get("track") or info.get("title") or "Unknown Title", pick_artist(info)),
        artist=pick_artist(info),
        uploader=info.get("uploader") or "",
        upload_date=info.get("upload_date") or "",
        duration=info.get("duration") or 0,
        webpage_url=info.get("webpage_url") or "",
    )


def format_upload_date(raw: str) -> str:
    if not raw or len(raw) != 8 or not raw.isdigit():
        return ""
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return any(marker in host for marker in YOUTUBE_HOST_MARKERS)


def split_title_artist(text: str):
    if not text:
        return "", ""
    if " - " in text:
        artist, title = text.split(" - ", 1)
        return title.strip(), artist.strip()
    return text.strip(), ""


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url)
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=20, context=ctx) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_meta_value(html: str, key: str, prop: bool = False):
    attr = "property" if prop else "name"
    pattern = rf'<meta[^>]+{attr}="{re.escape(key)}"[^>]+content="([^"]+)"'
    match = re.search(pattern, html, flags=re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""


def extract_spotify_track_query(track_url: str, html: str = ""):
    page = html or fetch_text(track_url)
    title = extract_meta_value(page, "og:title", prop=True)
    artist = extract_meta_value(page, "music:musician_description")
    release_date = extract_meta_value(page, "music:release_date")
    artwork_url = extract_meta_value(page, "og:image", prop=True)
    if title:
        return MusicQuery(
            title=title,
            artist=artist,
            source_url=track_url,
            release_date=release_date,
            artwork_url=artwork_url,
        )
    return None


def extract_spotify_queries(url: str):
    page = fetch_text(url)
    path = (urlparse(url).path or "").lower()
    if "/track/" in path:
        q = extract_spotify_track_query(url, html=page)
        return ([q] if q else []), ""

    track_urls = re.findall(
        r'<meta name="music:song" content="(https://open\.spotify\.com/track/[^"]+)"',
        page,
        flags=re.IGNORECASE,
    )
    track_urls = list(dict.fromkeys(track_urls))[:200]

    queries = []
    for t_url in track_urls:
        try:
            q = extract_spotify_track_query(t_url)
            if q:
                queries.append(q)
        except Exception:
            continue
    collection_name = ""
    if "/playlist/" in path or "/album/" in path:
        collection_name = extract_meta_value(page, "og:title", prop=True)
    return queries, collection_name


def extract_apple_queries(url: str):
    parsed = urlparse(url)
    q = urllib.parse.parse_qs(parsed.query)
    track_id = q.get("i", [""])[0]

    path = parsed.path or ""
    album_id_match = re.search(r"/album/[^/]+/(\d+)", path)
    album_id = album_id_match.group(1) if album_id_match else ""

    queries = []
    if track_id.isdigit():
        payload = json.loads(fetch_text(f"https://itunes.apple.com/lookup?id={track_id}&entity=song"))
        for item in payload.get("results", []):
            if item.get("wrapperType") == "track":
                title = item.get("trackName", "")
                artist = item.get("artistName", "")
                album = item.get("collectionName", "")
                release_date = (item.get("releaseDate", "") or "").split("T")[0]
                artwork_url = (item.get("artworkUrl100", "") or "").replace("100x100", "1000x1000")
                if title:
                    queries.append(
                        MusicQuery(
                            title=title,
                            artist=artist,
                            source_url=url,
                            album=album,
                            release_date=release_date,
                            artwork_url=artwork_url,
                        )
                    )
                break
        return queries, ""

    if album_id.isdigit():
        payload = json.loads(fetch_text(f"https://itunes.apple.com/lookup?id={album_id}&entity=song"))
        for item in payload.get("results", []):
            if item.get("wrapperType") != "track":
                continue
            title = item.get("trackName", "")
            artist = item.get("artistName", "")
            album = item.get("collectionName", "")
            release_date = (item.get("releaseDate", "") or "").split("T")[0]
            artwork_url = (item.get("artworkUrl100", "") or "").replace("100x100", "1000x1000")
            if title:
                queries.append(
                    MusicQuery(
                        title=title,
                        artist=artist,
                        source_url=url,
                        album=album,
                        release_date=release_date,
                        artwork_url=artwork_url,
                    )
                )
        collection_name = queries[0].album if queries else ""
        return queries, collection_name

    page = fetch_text(url)
    title = extract_meta_value(page, "og:title", prop=True)
    if title:
        t, a = split_title_artist(title)
        if t:
            queries.append(MusicQuery(title=t, artist=a, source_url=url))
    return queries, ""


def extract_generic_queries(url: str):
    page = fetch_text(url)
    title = extract_meta_value(page, "og:title", prop=True) or extract_meta_value(page, "twitter:title")
    desc = extract_meta_value(page, "description")
    artist = ""

    if title:
        t, a = split_title_artist(title)
        if not t:
            t = title
        if not a and " - " in desc:
            _, a2 = split_title_artist(desc)
            a = a2
        artist = a
        return [MusicQuery(title=t, artist=artist, source_url=url)], ""
    return [], ""


def extract_urls_from_input(text: str):
    raw_urls = re.findall(r"https?://[^\s]+", text or "")
    cleaned = []
    for u in raw_urls:
        u = u.rstrip(").,;]>\"'")
        cleaned.append(u)
    return list(dict.fromkeys(cleaned))


class DownloadTracker:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE,
                    title TEXT,
                    normalized_title TEXT,
                    artist TEXT,
                    uploader TEXT,
                    upload_date TEXT,
                    duration INTEGER,
                    webpage_url TEXT,
                    file_path TEXT,
                    downloaded_at TEXT
                )
                """
            )
            self.conn.commit()

    def check_duplicate(self, track: TrackInfo):
        with self._lock:
            by_id = self.conn.execute(
                "SELECT * FROM downloads WHERE video_id = ?", (track.video_id,)
            ).fetchone()
        if by_id:
            return dict(by_id)

        with self._lock:
            by_name = self.conn.execute(
                """
                SELECT * FROM downloads
                WHERE normalized_title = ?
                AND abs(duration - ?) <= 2
                LIMIT 1
                """,
                (normalize_title(track.title), track.duration or 0),
            ).fetchone()
        if by_name:
            return dict(by_name)

        return None

    def add_download(self, track: TrackInfo, file_path: str):
        with self._lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO downloads (
                    video_id, title, normalized_title, artist, uploader,
                    upload_date, duration, webpage_url, file_path, downloaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    track.video_id,
                    track.title,
                    normalize_title(track.title),
                    track.artist,
                    track.uploader,
                    track.upload_date,
                    track.duration,
                    track.webpage_url,
                    file_path,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            self.conn.commit()

    def reset_download_memory(self):
        with self._lock:
            self.conn.execute("DELETE FROM downloads")
            self.conn.commit()


def embed_cover_if_available(tags: ID3, artwork_url: str):
    if not artwork_url:
        return
    try:
        raw = urllib.request.urlopen(artwork_url, timeout=20, context=ssl._create_unverified_context()).read()
        if not raw:
            return
        mime = "image/jpeg"
        lowered = artwork_url.lower()
        if ".png" in lowered:
            mime = "image/png"
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=raw))
    except Exception:
        return


def fetch_lyrics(title: str, artist: str) -> str | None:
    try:
        url = f"https://lrclib.net/api/get?artist_name={urllib.parse.quote(artist)}&track_name={urllib.parse.quote(title)}"
        req = urllib.request.Request(url, headers={"User-Agent": "sullys-music-downloader"})
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("plainLyrics") or data.get("syncedLyrics")
    except Exception:
        return None


def embed_lyrics_if_available(media_path: Path, title: str, artist: str, fmt: str = "mp3"):
    if not media_path.exists():
        return
    lyrics = fetch_lyrics(title, artist)
    if not lyrics:
        return
    try:
        if fmt == "mp3":
            tags = ID3(str(media_path))
            tags.delall("USLT")
            tags.add(USLT(encoding=3, lang="eng", desc="Lyrics", text=lyrics))
            tags.save(v2_version=3)
        elif fmt == "flac":
            tags = FLAC(str(media_path))
            tags["lyrics"] = [lyrics]
            tags.save()
    except Exception:
        pass


def _embed_cover_flac(flac_file: FLAC, artwork_url: str):
    if not artwork_url:
        return
    try:
        raw = urllib.request.urlopen(artwork_url, timeout=20, context=ssl._create_unverified_context()).read()
        if not raw:
            return
        pic = Picture()
        pic.type = 3
        pic.desc = "Cover"
        pic.data = raw
        lowered = artwork_url.lower()
        pic.mime = "image/png" if ".png" in lowered else "image/jpeg"
        flac_file.add_picture(pic)
    except Exception:
        pass


def enrich_flac_tags(flac_path: Path, track: TrackInfo, source_query: MusicQuery | None = None):
    if not flac_path.exists():
        return
    try:
        tags = FLAC(str(flac_path))
        tags["title"] = [source_query.title if source_query and source_query.title else track.title]
        tags["artist"] = [source_query.artist if source_query and source_query.artist else track.artist]
        if source_query and source_query.album:
            tags["album"] = [source_query.album]
        published = ""
        if source_query and source_query.release_date:
            published = source_query.release_date
        else:
            published = format_upload_date(track.upload_date)
        if published:
            tags["date"] = [published]
        if source_query and source_query.artwork_url:
            _embed_cover_flac(tags, source_query.artwork_url)
        tags.save()
    except Exception:
        pass
    except Exception:
        pass


def enrich_mp3_tags(mp3_path: Path, track: TrackInfo, source_query: MusicQuery | None = None):
    if not mp3_path.exists():
        return

    tags = ID3(str(mp3_path))
    tags.delall("TIT2")
    tags.delall("TPE1")
    tags.delall("TALB")
    tags.delall("TDRC")

    chosen_title = source_query.title if source_query and source_query.title else track.title
    chosen_artist = source_query.artist if source_query and source_query.artist else track.artist
    tags.add(TIT2(encoding=3, text=chosen_title))
    tags.add(TPE1(encoding=3, text=chosen_artist))

    if source_query and source_query.album:
        tags.add(TALB(encoding=3, text=source_query.album))

    published = ""
    if source_query and source_query.release_date:
        published = source_query.release_date
    else:
        published = format_upload_date(track.upload_date)
    if published:
        tags.add(TDRC(encoding=3, text=published))

    if track.webpage_url:
        tags.add(TXXX(encoding=3, desc="SOURCE_URL", text=track.webpage_url))
    if track.video_id:
        tags.add(TXXX(encoding=3, desc="YOUTUBE_ID", text=track.video_id))
    if track.uploader:
        tags.add(TXXX(encoding=3, desc="UPLOADER", text=track.uploader))

    if source_query:
        if source_query.source_url:
            tags.add(TXXX(encoding=3, desc="SOURCE_LOOKUP_URL", text=source_query.source_url))
        embed_cover_if_available(tags, source_query.artwork_url)

    tags.save(v2_version=3)


def extract_entries_youtube(url: str):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        return [], ""

    if "entries" in info and info["entries"]:
        entries = []
        collection_name = info.get("title") or ""
        for e in info["entries"]:
            if not e:
                continue
            vid = e.get("id")
            if vid:
                entries.append(f"https://www.youtube.com/watch?v={vid}")
            elif e.get("url"):
                entries.append(e["url"])
        return entries, collection_name

    return [url], ""


def extract_entries_youtube_detailed(url: str):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        return [], ""

    collection_name = info.get("title") or ""
    if "entries" in info and info["entries"]:
        entries = []
        for e in info["entries"]:
            if not e:
                continue
            vid = e.get("id")
            item_url = ""
            if vid:
                item_url = f"https://www.youtube.com/watch?v={vid}"
            elif e.get("url"):
                item_url = e["url"]
            if not item_url:
                continue
            entries.append({"url": item_url, "title": e.get("title") or ""})
        return entries, collection_name

    return [{"url": url, "title": info.get("title") or ""}], ""


def extract_music_queries(url: str):
    collection_name = ""
    info = None
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "nocheckcertificate": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        info = None

    queries = []

    def add_from_info(item: dict, fallback_source: str):
        if not item:
            return
        title = item.get("track") or item.get("title") or ""
        artist = item.get("artist") or item.get("album_artist") or item.get("uploader") or ""
        if not title:
            title, parsed_artist = split_title_artist(item.get("title") or "")
            if not artist:
                artist = parsed_artist
        if title:
            queries.append(MusicQuery(title=title.strip(), artist=artist.strip(), source_url=item.get("webpage_url") or fallback_source))

    if info:
        if info.get("entries"):
            for e in info["entries"]:
                add_from_info(e, url)
        else:
            add_from_info(info, url)

    if not queries:
        host = (urlparse(url).netloc or "").lower()
        if "spotify.com" in host:
            queries, collection_name = extract_spotify_queries(url)
        elif "music.apple.com" in host:
            queries, collection_name = extract_apple_queries(url)
        else:
            queries, collection_name = extract_generic_queries(url)

    seen = set()
    result = []
    for q in queries:
        key = (normalize_title(q.title), normalize_title(q.artist))
        if key in seen:
            continue
        seen.add(key)
        result.append(q)
    return result, collection_name


def score_yt_candidate(query: MusicQuery, entry: dict) -> int:
    title = (entry.get("title") or "").lower()
    uploader = (entry.get("uploader") or entry.get("channel") or "").lower()
    duration = entry.get("duration") or 0

    score = 0

    for token in normalize_title(query.title).split():
        if token and token in title:
            score += 4

    if query.artist:
        for token in normalize_title(query.artist).split():
            if token and token in title:
                score += 5
            if token and token in uploader:
                score += 4

    preferred = ["official audio", "audio", "topic", "provided to youtube"]
    for p in preferred:
        if p in title or p in uploader:
            score += 16

    avoid = ["live", "cover", "reaction", "karaoke", "remix", "8d", "nightcore", "slowed", "sped up"]
    for bad in avoid:
        if bad in title:
            score -= 24

    if duration <= 0:
        score -= 4
    elif duration < 45:
        score -= 8
    elif duration > 600:
        score -= 10

    return score


def pick_youtube_for_query(query: MusicQuery):
    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "nocheckcertificate": True,
        }
    ) as ydl:
        search = ydl.extract_info(f"ytsearch10:{query.artist} {query.title} audio", download=False)

    entries = (search or {}).get("entries") or []
    if not entries:
        return None

    best = max(entries, key=lambda e: score_yt_candidate(query, e))
    if best.get("webpage_url"):
        return best["webpage_url"]
    if best.get("id"):
        return f"https://www.youtube.com/watch?v={best['id']}"
    return None


def _build_download_opts(output_dir: Path, quality_key: str):
    output_dir = Path(output_dir)
    preset = QUALITY_PRESETS.get(quality_key, QUALITY_PRESETS["mp3_320"])
    fmt = preset["format"]

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "writethumbnail": fmt in ("mp3", "flac"),
        "addmetadata": True,
        "outtmpl": str(output_dir / "__tmp__%(id)s.%(ext)s"),
    }

    if fmt == "mp3":
        bitrate = preset.get("bitrate", "320")
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": bitrate},
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ]
    elif fmt == "flac":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "flac", "preferredquality": "0"},
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ]
    elif fmt == "mp4":
        resolution = preset.get("resolution", "720")
        opts["format"] = f"bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]/best"
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{"key": "FFmpegMetadata"}]

    ffmpeg_location = detect_ffmpeg_location()
    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location

    return opts, fmt


def download_one(
    url: str,
    output_dir: Path,
    log,
    source_query: MusicQuery | None = None,
    quality_key: str = "mp3_320",
    progress_hook=None,
):
    output_dir = Path(output_dir)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError(f"Could not read video info: {url}")

    track = make_track(info)

    dl_opts, fmt = _build_download_opts(output_dir, quality_key)
    if progress_hook:
        dl_opts["progress_hooks"] = [progress_hook]

    with yt_dlp.YoutubeDL(dl_opts) as ydl:
        result = ydl.extract_info(url, download=True)
        prepared = Path(ydl.prepare_filename(result))

    ext_map = {"mp3": ".mp3", "flac": ".flac", "mp4": ".mp4"}
    target_ext = ext_map.get(fmt, ".mp3")
    media_path = prepared.with_suffix(target_ext)
    chosen_title = source_query.title if source_query and source_query.title else track.title
    chosen_title = clean_song_title(chosen_title, source_query.artist if source_query else track.artist)
    final_media = unique_media_path(output_dir, chosen_title, fmt)

    if media_path.exists() and media_path != final_media:
        media_path.rename(final_media)
    media_path = final_media

    if fmt == "mp3":
        enrich_mp3_tags(media_path, track, source_query=source_query)
    elif fmt == "flac":
        enrich_flac_tags(media_path, track, source_query=source_query)
    log(f"Saved: {media_path.name}")
    return track, str(media_path), fmt


def notify(title: str, message: str):
    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                check=False, capture_output=True,
            )
        elif sys.platform == "win32":
            subprocess.run(
                [
                    "powershell", "-Command",
                    f'[System.Windows.Forms.MessageBox]::Show("{message}", "{title}")',
                ],
                check=False, capture_output=True, timeout=5,
            )
            return
    except Exception:
        pass

    try:
        from plyer import notification as plyer_not
        plyer_not.notify(title=title, message=message, app_name="Sully's Music Downloader")
    except Exception:
        pass


def check_for_updates() -> str | None:
    try:
        req = urllib.request.Request(REPO_URL, headers={"Accept": "application/vnd.github.v3+json"})
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            data = json.loads(response.read().decode("utf-8"))
            latest = data.get("tag_name", "").lstrip("v")
            if latest and latest != CURRENT_VERSION:
                return latest
    except Exception:
        pass
    return None


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("sully's music downloader")
        self.root.geometry("980x680")

        self.cfg = Config(CONFIG_PATH)
        saved = self.cfg.load()

        self.url_var = StringVar()
        output_default = saved.get("output_folder", "") or str(Path.home() / "Music" / "sully's music downloader")
        self.output_var = StringVar(value=output_default)
        self.dup_mode = StringVar(value=saved.get("dup_mode", "skip"))
        self.quality_var = StringVar(value=saved.get("quality", "mp3_320"))
        self.embed_lyrics_var = BooleanVar(value=saved.get("embed_lyrics", False))
        self.concurrency_var = IntVar(value=min(3, max(1, saved.get("concurrency", 1))))
        self.status_var = StringVar(value="Ready")

        self.tracker = DownloadTracker(DB_PATH)
        self.queue: list[QueuedTask] = []
        self.queue_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()

        self._build_ui()
        self._apply_theme()
        self._setup_drag_drop()
        self._check_updates()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(main, text="Paste URL(s) (YouTube/YouTube Music/Spotify/Apple/etc.) — drag & drop supported:").pack(anchor="w")
        self.url_entry = ttk.Entry(main, textvariable=self.url_var)
        self.url_entry.pack(fill="x", **pad)

        row = ttk.Frame(main)
        row.pack(fill="x")
        ttk.Label(row, text="Output Folder:").pack(side="left")
        ttk.Entry(row, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Browse", command=self.pick_output).pack(side="left")

        settings_row = ttk.Frame(main)
        settings_row.pack(fill="x", **pad)

        ttk.Label(settings_row, text="Quality:").pack(side="left")
        self.quality_combo = ttk.Combobox(settings_row, textvariable=self.quality_var, width=14, state="readonly")
        self.quality_combo["values"] = [
            "mp3_128", "mp3_256", "mp3_320",
            "flac",
            "mp4_360", "mp4_720", "mp4_1080",
        ]
        self.quality_combo.pack(side="left", padx=6)

        ttk.Label(settings_row, text="Workers:").pack(side="left", padx=(12, 0))
        self.conc_spin = ttk.Spinbox(settings_row, from_=1, to=3, textvariable=self.concurrency_var, width=3)
        self.conc_spin.pack(side="left", padx=4)

        ttk.Checkbutton(settings_row, text="Embed lyrics", variable=self.embed_lyrics_var).pack(side="left", padx=(12, 0))

        mode_row = ttk.Frame(main)
        mode_row.pack(fill="x", **pad)
        ttk.Label(mode_row, text="If duplicate found:").pack(side="left")
        ttk.Radiobutton(mode_row, text="Skip", value="skip", variable=self.dup_mode).pack(side="left", padx=6)
        ttk.Radiobutton(mode_row, text="Download anyway", value="force", variable=self.dup_mode).pack(side="left", padx=6)

        action_row = ttk.Frame(main)
        action_row.pack(fill="x", **pad)
        self.download_btn = ttk.Button(action_row, text="Analyze + Download", command=self.start_download)
        self.download_btn.pack(side="left")
        self.stop_btn = ttk.Button(action_row, text="Stop", command=self.stop_download, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.pause_btn = ttk.Button(action_row, text="Pause", command=self.pause_download, state="disabled")
        self.pause_btn.pack(side="left", padx=4)
        ttk.Button(action_row, text="Reset Download Memory", command=self.reset_download_memory).pack(side="left", padx=8)
        ttk.Button(action_row, text="Settings", command=self.open_settings).pack(side="left", padx=4)
        ttk.Label(action_row, textvariable=self.status_var).pack(side="left", padx=10)

        self.log_box = ScrolledText(main, height=20)
        self.log_box.pack(fill="both", expand=True, **pad)

        self.log("Notes: Only download content you have rights to use.")

    def _apply_theme(self):
        theme_pref = self.cfg.get("theme", "system")
        if theme_pref == "system":
            return
        style = ttk.Style(self.root)
        available = style.theme_names()
        if theme_pref == "dark":
            for candidate in ("clam", "alt", "default"):
                if candidate in available:
                    style.theme_use(candidate)
                    break
        elif theme_pref == "light":
            for candidate in ("default", "aqua", "vista"):
                if candidate in available:
                    style.theme_use(candidate)
                    break

    def _setup_drag_drop(self):
        def on_drop(event):
            text = event.data.strip()
            urls = extract_urls_from_input(text)
            if urls:
                current = self.url_var.get().strip()
                if current:
                    self.url_var.set(current + "\n" + "\n".join(urls))
                else:
                    self.url_var.set("\n".join(urls))

        if sys.platform == "darwin":
            try:
                self.url_entry.tk.eval(
                    "package require TkDND 2.8\n"
                    "tkdnd::drop_target register %s DND_Files" % self.url_entry._w
                )
                self.url_entry.bind("<<Drop>>", on_drop)
            except Exception:
                pass
        elif sys.platform == "win32":
            try:
                self.url_entry.bind("<Button-3>", lambda e: self._context_menu(e))
            except Exception:
                pass

    def _context_menu(self, event):
        try:
            import tkinter as tk
            menu = tk.Menu(self.root, tearoff=0)
            menu.add_command(label="Paste", command=lambda: self.url_entry.event_generate("<<Paste>>"))
            menu.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass

    def log(self, text: str):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.log, text)
            return
        self.log_box.insert(END, text + "\n")
        self.log_box.see(END)

    def set_status(self, text: str):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.set_status, text)
            return
        self.status_var.set(text)

    def set_download_button(self, enabled: bool):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.set_download_button, enabled)
            return
        self.download_btn.config(state="normal" if enabled else "disabled")
        self.stop_btn.config(state="normal" if not enabled else "disabled")
        self.pause_btn.config(state="normal" if not enabled else "disabled")

    def pick_output(self):
        selected = filedialog.askdirectory(initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)

    def reset_download_memory(self):
        confirm = messagebox.askyesno(
            "Reset Download Memory",
            "This will clear duplicate history of downloaded songs. Continue?",
        )
        if not confirm:
            return
        self.tracker.reset_download_memory()
        self.log("Download memory reset. Duplicate history cleared.")

    def open_settings(self):
        dialog = Toplevel(self.root)
        dialog.title("Settings")
        dialog.geometry("420x460")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)

        saved = self.cfg.load()

        section_y = [0]
        def section(title):
            ttk.Label(frame, text=title, font=("", 11, "bold")).grid(row=section_y[0], column=0, columnspan=2, sticky="w", pady=(12 if section_y[0] else 0, 4))
            section_y[0] += 1

        def row(label_text, widget):
            ttk.Label(frame, text=label_text).grid(row=section_y[0], column=0, sticky="w", padx=(0, 12))
            widget.grid(row=section_y[0], column=1, sticky="w")
            section_y[0] += 1

        section("Appearance")
        theme_var = StringVar(value=saved.get("theme", "system"))
        row("Theme", ttk.Combobox(frame, textvariable=theme_var, values=["system", "light", "dark"], width=10, state="readonly"))

        section("Downloads")
        quality_var = StringVar(value=saved.get("quality", "mp3_320"))
        row("Default quality", ttk.Combobox(frame, textvariable=quality_var, values=["mp3_128", "mp3_256", "mp3_320", "flac", "mp4_360", "mp4_720", "mp4_1080"], width=10, state="readonly"))

        concurrency_var = IntVar(value=min(3, max(1, saved.get("concurrency", 1))))
        row("Parallel workers", ttk.Spinbox(frame, from_=1, to=3, textvariable=concurrency_var, width=3))

        dup_var = StringVar(value=saved.get("dup_mode", "skip"))
        row("Duplicate policy", ttk.Combobox(frame, textvariable=dup_var, values=["skip", "force"], width=10, state="readonly"))

        lyrics_var = BooleanVar(value=saved.get("embed_lyrics", False))
        row("Embed lyrics", ttk.Checkbutton(frame, variable=lyrics_var))

        section("Notifications")
        notify_var = BooleanVar(value=saved.get("notifications", True))
        row("Show completion alerts", ttk.Checkbutton(frame, variable=notify_var))

        section("Updates")
        update_var = BooleanVar(value=saved.get("check_updates", True))
        row("Check for updates", ttk.Checkbutton(frame, variable=update_var))

        def save():
            self.cfg.set("theme", theme_var.get())
            self.cfg.set("quality", quality_var.get())
            self.cfg.set("concurrency", concurrency_var.get())
            self.cfg.set("dup_mode", dup_var.get())
            self.cfg.set("embed_lyrics", lyrics_var.get())
            self.cfg.set("notifications", notify_var.get())
            self.cfg.set("check_updates", update_var.get())
            self.cfg.save()
            self.quality_var.set(quality_var.get())
            self.concurrency_var.set(concurrency_var.get())
            self.embed_lyrics_var.set(lyrics_var.get())
            self.dup_mode.set(dup_var.get())
            dialog.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=section_y[0], column=0, columnspan=2, pady=(20, 0), sticky="e")
        ttk.Button(btn_frame, text="Save", command=save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side="left")

    def stop_download(self):
        self._stop_event.set()
        self._pause_event.set()
        self.log("Stopping downloads...")

    def pause_download(self):
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.pause_btn.config(text="Resume")
            self.log("Downloads paused.")
        else:
            self._pause_event.set()
            self.pause_btn.config(text="Pause")
            self.log("Downloads resumed.")

    def _save_preferences(self):
        self.cfg.set("output_folder", self.output_var.get())
        self.cfg.set("quality", self.quality_var.get())
        self.cfg.set("dup_mode", self.dup_mode.get())
        self.cfg.set("embed_lyrics", self.embed_lyrics_var.get())
        self.cfg.set("concurrency", self.concurrency_var.get())
        self.cfg.save()

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            self.log("Please paste a URL.")
            return
        self._save_preferences()
        self._stop_event.clear()
        self._pause_event.set()
        self.set_download_button(False)
        threading.Thread(target=self.run_download, args=(url,), daemon=True).start()

    def show_preview_dialog(self, title: str, lines):
        result = {"urls": None}

        dialog = Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("860x520")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(
            frame,
            text="Review and edit links below (one URL per line). Download starts after confirmation.",
        ).pack(anchor="w")
        box = ScrolledText(frame, height=22)
        box.pack(fill="both", expand=True, pady=10)
        box.insert("1.0", "\n".join(lines))

        btns = ttk.Frame(frame)
        btns.pack(fill="x")

        def confirm():
            edited_urls = extract_urls_from_input(box.get("1.0", END))
            if not edited_urls:
                messagebox.showwarning("No URLs", "Add at least one valid URL before downloading.")
                return
            result["urls"] = edited_urls
            dialog.destroy()

        def cancel():
            result["urls"] = None
            dialog.destroy()

        ttk.Button(btns, text="Start Download", command=confirm).pack(side="left")
        ttk.Button(btns, text="Cancel", command=cancel).pack(side="left", padx=8)

        dialog.wait_window()
        return result["urls"]

    def ask_for_confirmation(self, title: str, lines):
        if threading.current_thread() is threading.main_thread():
            return self.show_preview_dialog(title, lines)

        event = threading.Event()
        out = {"urls": None}

        def ask():
            out["urls"] = self.show_preview_dialog(title, lines)
            event.set()

        self.root.after(0, ask)
        event.wait()
        return out["urls"]

    def resolve_targets(self, url: str):
        if is_youtube_url(url):
            self.log("Detected YouTube link. Building direct download list...")
            targets, collection_name = extract_entries_youtube(url)
            tasks = [DownloadTask(youtube_url=u, source_input_url=url, collection_name=collection_name) for u in targets]
            preview = [u for u in targets]
            return tasks, preview

        self.log("Detected non-YouTube link. Parsing track metadata...")
        queries, collection_name = extract_music_queries(url)
        if not queries:
            raise RuntimeError("Could not parse track metadata from this link.")

        self.log(f"Parsed {len(queries)} track(s). Searching YouTube best matches...")
        targets = []
        preview = []

        for idx, q in enumerate(queries, start=1):
            self.set_status(f"Searching YouTube {idx}/{len(queries)}")
            yt_url = pick_youtube_for_query(q)
            if not yt_url:
                self.log(f"  No YouTube match found: {q.artist} - {q.title}")
                continue
            targets.append(
                DownloadTask(
                    youtube_url=yt_url,
                    source_input_url=url,
                    source_query=q,
                    collection_name=collection_name,
                )
            )
            preview.append(yt_url)

        deduped = []
        seen = set()
        for task in targets:
            if task.youtube_url not in seen:
                seen.add(task.youtube_url)
                deduped.append(task)

        return deduped, preview

    def _download_single(self, task: DownloadTask, output: Path, quality_key: str):
        if self._stop_event.is_set():
            return
        self._pause_event.wait()

        target = task.youtube_url
        with yt_dlp.YoutubeDL(
            {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "nocheckcertificate": True,
            }
        ) as ydl:
            info = ydl.extract_info(target, download=False)

        if not info:
            self.log(f"  Could not read metadata for {target}, skipped.")
            return

        track = make_track(info)
        duplicate = self.tracker.check_duplicate(track)
        if duplicate:
            self.log(f"  Duplicate: '{track.title}' already downloaded at {duplicate['downloaded_at']}")
            if self.dup_mode.get() == "skip":
                self.log("  Skipped due to duplicate policy.")
                return

        if self._stop_event.is_set():
            return
        self._pause_event.wait()

        target_output = output
        if task.collection_name:
            target_output = output / safe_filename(task.collection_name)
            target_output.mkdir(parents=True, exist_ok=True)

        saved_track, path = download_one(
            target,
            target_output,
            self.log,
            source_query=task.source_query,
            quality_key=quality_key,
        )
        self.tracker.add_download(saved_track, path)

        if self.cfg.get("embed_lyrics", False):
            fmt = QUALITY_PRESETS.get(quality_key, QUALITY_PRESETS["mp3_320"])["format"]
            chosen_title = task.source_query.title if task.source_query and task.source_query.title else saved_track.title
            chosen_artist = task.source_query.artist if task.source_query and task.source_query.artist else saved_track.artist
            embed_lyrics_if_available(Path(path), chosen_title, chosen_artist, fmt=fmt)

    def run_download(self, raw_input: str):
        output = Path(self.output_var.get()).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        quality_key = self.quality_var.get()
        workers = min(3, max(1, self.concurrency_var.get()))

        self.set_status("Analyzing link...")
        try:
            input_urls = extract_urls_from_input(raw_input)
            if not input_urls:
                self.log("No valid URL found in input.")
                self.set_status("Ready")
                self.set_download_button(True)
                return

            all_tasks = []
            for idx, one_url in enumerate(input_urls, start=1):
                if self._stop_event.is_set():
                    self.log("Stopped during analysis.")
                    self.set_status("Ready")
                    self.set_download_button(True)
                    return
                self.log(f"[{idx}/{len(input_urls)}] Resolving {one_url}")
                tasks, _preview = self.resolve_targets(one_url)
                all_tasks.extend(tasks)

            if not all_tasks:
                self.log("No downloadable items found.")
                self.set_status("Ready")
                self.set_download_button(True)
                return

            deduped = []
            seen_urls = set()
            for task in all_tasks:
                if task.youtube_url in seen_urls:
                    continue
                seen_urls.add(task.youtube_url)
                deduped.append(task)

            self.log(f"Prepared {len(deduped)} item(s). Waiting for your confirmation...")
            initial_urls = [t.youtube_url for t in deduped]
            confirmed_urls = self.ask_for_confirmation("Confirm Download List", initial_urls)
            if not confirmed_urls:
                self.log("Download canceled by user.")
                self.set_status("Ready")
                self.set_download_button(True)
                return

            task_by_url = {t.youtube_url: t for t in deduped}
            final_tasks = []
            seen_final = set()
            for u in confirmed_urls:
                if u in seen_final:
                    continue
                seen_final.add(u)
                final_tasks.append(task_by_url.get(u) or DownloadTask(youtube_url=u, source_input_url=u))

            downloaded = 0
            skipped = 0
            total = len(final_tasks)

            if workers > 1:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = {}
                    for task in final_tasks:
                        if self._stop_event.is_set():
                            break
                        future = executor.submit(self._download_single, task, output, quality_key)
                        futures[future] = task
                        self.set_status(f"Downloading {len(futures)}/{total}...")

                    for future in as_completed(futures):
                        if self._stop_event.is_set():
                            break
                        try:
                            result = future.result()
                            if result:
                                downloaded += 1
                            else:
                                skipped += 1
                        except Exception as e:
                            self.log(f"  Failed: {e}")
                            skipped += 1
            else:
                for index, task in enumerate(final_tasks, start=1):
                    if self._stop_event.is_set():
                        self.log("Downloads stopped by user.")
                        break
                    self._pause_event.wait()
                    self.set_status(f"Downloading {index}/{total}")
                    try:
                        self._download_single(task, output, quality_key)
                        downloaded += 1
                    except Exception:
                        skipped += 1

            self.log(f"Done. Downloaded: {downloaded}, skipped/failed: {skipped}")
            self.set_status("Ready")
            if self.cfg.get("notifications", True):
                notify("Download Complete", f"{downloaded} tracks saved. {skipped} skipped/failed.")

        except Exception as e:
            self.log(f"Error: {e}")
            self.set_status("Ready")
        finally:
            self.set_download_button(True)

    def _check_updates(self):
        if not self.cfg.get("check_updates", True):
            return
        def check():
            latest = check_for_updates()
            if latest:
                self.root.after(0, lambda: self._prompt_update(latest))
        threading.Thread(target=check, daemon=True).start()

    def _prompt_update(self, latest: str):
        if messagebox.askyesno(
            "Update Available",
            f"Version {latest} is available. Open the download page?",
        ):
            import webbrowser
            webbrowser.open(f"{GITHUB_REPO_URL}/releases")


def main():
    root = Tk()
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
