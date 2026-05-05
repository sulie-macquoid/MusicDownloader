import re
import sqlite3
import threading
import urllib.parse
import urllib.request
import json
import ssl
import shutil
from html import unescape
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import END, StringVar, Tk, Toplevel, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from urllib.parse import urlparse
import sys

import yt_dlp
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TXXX


def app_data_dir() -> Path:
    # Keep runtime state in a user-writable location (important for packaged .app).
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "sully's music downloader"
    else:
        root = Path.home() / ".sullys-music-downloader"
    root.mkdir(parents=True, exist_ok=True)
    return root


DB_PATH = app_data_dir() / "downloads.db"
YOUTUBE_HOST_MARKERS = ("youtube.com", "youtu.be", "music.youtube.com")


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


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (title or "").lower())).strip()


def clean_song_title(raw_title: str, artist_hint: str = "") -> str:
    title = (raw_title or "").strip()
    if not title:
        return "Unknown Title"

    # Remove common trailing id suffixes like " [abc123]"
    title = re.sub(r"\s*\[[^\]]+\]\s*$", "", title, flags=re.IGNORECASE)

    # If format looks like "Artist - Song", prefer song part.
    if artist_hint and title.lower().startswith(artist_hint.lower() + " - "):
        title = title[len(artist_hint) + 3 :].strip()
    elif " - " in title:
        parts = [p.strip() for p in title.split(" - ", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            # Heuristic: treat leading segment as artist/uploader in common cases.
            if len(parts[0].split()) <= 6:
                title = parts[1]

    # Remove noisy parenthetical/suffix descriptors.
    noise = (
        r"official video|official visualizer|official audio|audio only|lyric video|lyrics|"
        r"music video|visualizer|mv|hd|4k|topic"
    )
    title = re.sub(rf"\s*\((?:{noise})[^)]*\)\s*", " ", title, flags=re.IGNORECASE)
    title = re.sub(rf"\s*\[(?:{noise})[^\]]*\]\s*", " ", title, flags=re.IGNORECASE)
    title = re.sub(rf"\s*-\s*(?:{noise}).*$", "", title, flags=re.IGNORECASE)

    # Normalize whitespace and trim punctuation.
    title = re.sub(r"\s+", " ", title).strip(" -_.,")
    return title or "Unknown Title"


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned or "Unknown Title"


def unique_mp3_path(output_dir: Path, title: str) -> Path:
    base = safe_filename(title)
    candidate = output_dir / f"{base}.mp3"
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        alt = output_dir / f"{base} ({i}).mp3"
        if not alt.exists():
            return alt
        i += 1


def detect_ffmpeg_location() -> str:
    # Finder-launched macOS apps may not inherit Homebrew PATH.
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(candidate).exists():
            return str(Path(candidate).parent)
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
    # Cap to avoid very long processing on massive playlists.
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

    # Fallback for unsupported Apple link types.
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
        # Strip common trailing punctuation from editable list formats like "(url)".
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
        # Keep existing embedded thumbnail if artwork download fails.
        return


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

    # Deduplicate near-identical queries while preserving order.
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


def download_one(
    url: str,
    output_dir: Path,
    log,
    source_query: MusicQuery | None = None,
    output_format: str = "mp3",
):
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

    output_format = (output_format or "mp3").lower()
    if output_format not in {"mp3", "mp4"}:
        output_format = "mp3"

    download_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "writethumbnail": output_format == "mp3",
        "addmetadata": True,
        # Temporary unique name; we'll rename to clean title after conversion/merge.
        "outtmpl": str(output_dir / "__tmp__%(id)s.%(ext)s"),
        "format": "bestaudio/best" if output_format == "mp3" else "bestvideo*+bestaudio/best",
        "postprocessors": (
            [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ]
            if output_format == "mp3"
            else [{"key": "FFmpegMetadata"}]
        ),
    }
    if output_format == "mp4":
        download_opts["merge_output_format"] = "mp4"
    ffmpeg_location = detect_ffmpeg_location()
    if ffmpeg_location:
        download_opts["ffmpeg_location"] = ffmpeg_location

    with yt_dlp.YoutubeDL(download_opts) as ydl:
        result = ydl.extract_info(url, download=True)
        prepared = Path(ydl.prepare_filename(result))

    target_ext = ".mp3" if output_format == "mp3" else ".mp4"
    media_path = prepared.with_suffix(target_ext)
    chosen_title = source_query.title if source_query and source_query.title else track.title
    chosen_title = clean_song_title(chosen_title, source_query.artist if source_query else track.artist)
    final_media = unique_mp3_path(output_dir, chosen_title).with_suffix(target_ext)

    if media_path.exists() and media_path != final_media:
        media_path.rename(final_media)
    media_path = final_media

    if output_format == "mp3":
        enrich_mp3_tags(media_path, track, source_query=source_query)
    log(f"Saved: {media_path.name}")
    return track, str(media_path)


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("sully's music downloader")
        self.root.geometry("920x620")

        self.url_var = StringVar()
        self.output_var = StringVar(value=str(Path.home() / "Music" / "sully's music downloader"))
        self.dup_mode = StringVar(value="skip")
        self.status_var = StringVar(value="Ready")

        self.tracker = DownloadTracker(DB_PATH)
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True, padx=12, pady=12)

        ttk.Label(main, text="Paste URL(s) (YouTube/YouTube Music/Spotify/Apple/etc.):").pack(anchor="w")
        ttk.Entry(main, textvariable=self.url_var).pack(fill="x", **pad)

        row = ttk.Frame(main)
        row.pack(fill="x")
        ttk.Label(row, text="Output Folder:").pack(side="left")
        ttk.Entry(row, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Browse", command=self.pick_output).pack(side="left")

        mode_row = ttk.Frame(main)
        mode_row.pack(fill="x", **pad)
        ttk.Label(mode_row, text="If duplicate found:").pack(side="left")
        ttk.Radiobutton(mode_row, text="Warn + Skip", value="skip", variable=self.dup_mode).pack(side="left", padx=6)
        ttk.Radiobutton(mode_row, text="Warn + Download anyway", value="force", variable=self.dup_mode).pack(side="left", padx=6)

        action_row = ttk.Frame(main)
        action_row.pack(fill="x", **pad)
        self.download_btn = ttk.Button(action_row, text="Analyze + Download", command=self.start_download)
        self.download_btn.pack(side="left")
        ttk.Button(action_row, text="Reset Download Memory", command=self.reset_download_memory).pack(side="left", padx=8)
        ttk.Label(action_row, textvariable=self.status_var).pack(side="left", padx=10)

        self.log_box = ScrolledText(main, height=24)
        self.log_box.pack(fill="both", expand=True, **pad)

        self.log("Notes: Only download content you have rights to use.")

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

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            self.log("Please paste a URL.")
            return
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

    def run_download(self, raw_input: str):
        output = Path(self.output_var.get()).expanduser()
        output.mkdir(parents=True, exist_ok=True)

        self.set_status("Analyzing link...")
        try:
            input_urls = extract_urls_from_input(raw_input)
            if not input_urls:
                self.log("No valid URL found in input.")
                self.set_status("Ready")
                self.set_download_button(True)
                return

            all_tasks = []
            all_preview = []
            for idx, one_url in enumerate(input_urls, start=1):
                self.log(f"[{idx}/{len(input_urls)}] Resolving {one_url}")
                tasks, preview = self.resolve_targets(one_url)
                all_tasks.extend(tasks)
                all_preview.extend(preview)

            if not all_tasks:
                self.log("No downloadable items found.")
                self.set_status("Ready")
                self.set_download_button(True)
                return

            # Global de-dup by final YouTube URL across mixed inputs.
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

            # Use edited URLs while preserving metadata when URL is unchanged.
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

            for index, task in enumerate(final_tasks, start=1):
                target = task.youtube_url
                self.set_status(f"Downloading {index}/{len(final_tasks)}")
                self.log(f"[{index}/{len(final_tasks)}] Checking {target}")

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
                    self.log("  Could not read metadata, skipped.")
                    skipped += 1
                    continue

                track = make_track(info)
                duplicate = self.tracker.check_duplicate(track)
                if duplicate:
                    self.log(
                        f"  Duplicate warning: '{track.title}' already downloaded at {duplicate['downloaded_at']}"
                    )
                    if self.dup_mode.get() == "skip":
                        self.log("  Skipped due to duplicate policy.")
                        skipped += 1
                        continue

                try:
                    target_output = output
                    if task.collection_name:
                        target_output = output / safe_filename(task.collection_name)
                        target_output.mkdir(parents=True, exist_ok=True)
                    saved_track, path = download_one(
                        target,
                        target_output,
                        self.log,
                        source_query=task.source_query,
                    )
                    self.tracker.add_download(saved_track, path)
                    downloaded += 1
                except Exception as e:
                    self.log(f"  Failed: {e}")
                    skipped += 1

            self.log(f"Done. Downloaded: {downloaded}, skipped/failed: {skipped}")
            self.set_status("Ready")

        except Exception as e:
            self.log(f"Error: {e}")
            self.set_status("Ready")
        finally:
            self.set_download_button(True)


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
