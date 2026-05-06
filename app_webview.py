import threading
import webbrowser
from collections import deque
from pathlib import Path
import sys

import webview
import yt_dlp

from app import (
    DB_PATH,
    DownloadTask,
    DownloadTracker,
    clean_song_title,
    download_one,
    extract_entries_youtube_detailed,
    extract_music_queries,
    extract_urls_from_input,
    is_youtube_url,
    make_track,
    pick_youtube_for_query,
    safe_filename,
    detect_ffmpeg_location,
    embed_lyrics_if_available,
    notify,
    check_for_updates,
    CURRENT_VERSION,
    GITHUB_REPO_URL,
)
from config import Config, QUALITY_PRESETS, QUALITY_LABELS, app_data_dir

# Inline _build_download_opts to avoid import issues
from pathlib import Path as _Path

def _build_download_opts(output_dir, quality_key):
    output_dir = _Path(output_dir)
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


class DownloaderAPI:
    def __init__(self):
        # Initialize Spotify client if credentials are set
        self.spotify_client = None
        spotify_id = self.config.get("spotify_client_id", "")
        spotify_secret = self.config.get("spotify_client_secret", "")
        if spotify_id and spotify_secret:
            try:
                import spotipy
                from spotipy.oauth2 import SpotifyClientCredentials
                client_credentials_manager = SpotifyClientCredentials(
                    client_id=spotify_id,
                    client_secret=spotify_secret
                )
                self.spotify_client = spotipy.Spotify(
                    client_credentials_manager=client_credentials_manager
                )
            except Exception:
                self.spotify_client = None
        self.window = None
        self.tracker = DownloadTracker(DB_PATH)
        self.config = Config(app_data_dir() / "config.json")

        self._state_lock = threading.Lock()
        saved = self.config.load()
        self.output_dir = saved.get("output_folder", "") or str(Path.home() / "Music" / "sully's music downloader")
        self.dup_mode = saved.get("dup_mode", "skip")
        self.quality_key = saved.get("quality", "mp3_320")
        self.concurrency = min(3, max(1, saved.get("concurrency", 1)))
        self.embed_lyrics = saved.get("embed_lyrics", False)
        self.notifications = saved.get("notifications", True)
        self.theme = saved.get("theme", "system")

        self.download_queue = deque()
        self.download_lock = threading.Lock()
        self.download_running = False
        self.stop_requested = False

        self.group_meta = {}
        self.group_order = []
        self.active_group = ""
        self.active_title = ""
        self.active_downloads = 0

        self.preview_cache = {}

        self._events = []
        self._events_lock = threading.Lock()

        self._log("Notes: Only download content you have rights to use.")

    def attach_window(self, window):
        self.window = window

    def _emit(self, event: str, payload: dict):
        with self._events_lock:
            self._events.append({"event": event, "payload": payload})

    def pull_events(self):
        with self._events_lock:
            events = self._events[:]
            self._events.clear()
        return events

    def _log(self, msg: str):
        self._emit("log", {"message": msg})

    def _status(self, msg: str):
        self._emit("status", {"message": msg})

    def _queue_event(self):
        self._emit("queue", self._queue_snapshot())

    def _download_state_event(self):
        with self.download_lock:
            running = self.download_running
        self._emit("download_state", {"running": running})

    def _progress_event(self, fmt: str, idx: int, total: int, progress: float, title: str):
        self._emit("progress", {
            "format": fmt,
            "index": idx,
            "total": total,
            "progress": progress,
            "title": title,
        })

    def _queue_snapshot(self):
        with self.download_lock:
            groups = []
            if self.active_group:
                meta = self.group_meta.get(self.active_group, {"total": 1, "done": 0, "pending": []})
                groups.append(
                    {
                        "name": self.active_group,
                        "done": int(meta.get("done", 0)),
                        "total": int(meta.get("total", 1)),
                        "active": self.active_title,
                        "pending": list(meta.get("pending", []))[:10],
                    }
                )

            for name in self.group_order:
                if name == self.active_group:
                    continue
                meta = self.group_meta.get(name)
                if not meta:
                    continue
                groups.append(
                    {
                        "name": name,
                        "done": int(meta.get("done", 0)),
                        "total": int(meta.get("total", 1)),
                        "active": "",
                        "pending": list(meta.get("pending", []))[:10],
                    }
                )
        return {"groups": groups}

    def get_initial_state(self):
        with self._state_lock:
            return {
                "output_dir": self.output_dir,
                "dup_mode": self.dup_mode,
                "quality": self.quality_key,
                "concurrency": self.concurrency,
                "embed_lyrics": self.embed_lyrics,
            }

    def get_settings(self):
        saved = self.config.load()
        return {
            "quality": saved.get("quality", "mp3_320"),
            "concurrency": saved.get("concurrency", 1),
            "embed_lyrics": saved.get("embed_lyrics", False),
            "notifications": saved.get("notifications", True),
            "check_updates": saved.get("check_updates", True),
            "dup_mode": saved.get("dup_mode", "skip"),
            "theme": saved.get("theme", "system"),
            "spotify_client_id": saved.get("spotify_client_id", ""),
            "spotify_client_secret": saved.get("spotify_client_secret", ""),
        }

    def save_settings(self, settings: dict):
        if "theme" in settings:
            self.theme = settings["theme"]
            self.config.set("theme", self.theme)
        if "quality" in settings:
            self.quality_key = settings["quality"]
            self.config.set("quality", self.quality_key)
        if "concurrency" in settings:
            val = min(3, max(1, int(settings["concurrency"])))
            self.config.set("concurrency", val)
            with self._state_lock:
                self.concurrency = val
        if "embed_lyrics" in settings:
            self.config.set("embed_lyrics", bool(settings["embed_lyrics"]))
            with self._state_lock:
                self.embed_lyrics = bool(settings["embed_lyrics"])
        if "dup_mode" in settings:
            self.config.set("dup_mode", settings["dup_mode"])
            with self._state_lock:
                self.dup_mode = settings["dup_mode"]
        if "notifications" in settings:
            self.config.set("notifications", bool(settings["notifications"]))
            with self._state_lock:
                self.notifications = bool(settings["notifications"])
        if "check_updates" in settings:
            self.config.set("check_updates", bool(settings["check_updates"]))
        # Spotify credentials
        spotify_id = settings.get("spotify_client_id", "").strip()
        spotify_secret = settings.get("spotify_client_secret", "").strip()
        self.config.set("spotify_client_id", spotify_id)
        self.config.set("spotify_client_secret", spotify_secret)
        self.config.save()
        return True

    def check_update(self):
        latest = check_for_updates()
        if latest:
            return {"available": True, "version": latest, "url": f"{GITHUB_REPO_URL}/releases"}
        return {"available": False}

    def browse_output_folder(self):
        if not self.window:
            return ""
        chosen = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if not chosen:
            return ""
        folder = chosen[0]
        with self._state_lock:
            self.output_dir = folder
        self.config.set("output_folder", folder)
        self.config.save()
        self._status(f"Output folder set: {folder}")
        return folder

    def set_output_folder(self, folder: str):
        folder = (folder or "").strip()
        if not folder:
            return False
        with self._state_lock:
            self.output_dir = folder
        self.config.set("output_folder", folder)
        self.config.save()
        return True

    def set_duplicate_mode(self, mode: str):
        if mode not in ("skip", "force"):
            return False
        with self._state_lock:
            self.dup_mode = mode
        self.config.set("dup_mode", mode)
        self.config.save()
        return True

    def set_quality(self, quality: str):
        from config import QUALITY_PRESETS
        if quality not in QUALITY_PRESETS:
            return False
        with self._state_lock:
            self.quality_key = quality
        self.config.set("quality", quality)
        self.config.save()
        return True

    def set_concurrency(self, n: int):
        n = min(3, max(1, int(n)))
        with self._state_lock:
            self.concurrency = n
        self.config.set("concurrency", n)
        self.config.save()
        return True

    def reset_download_memory(self):
        self.tracker.reset_download_memory()
        self._log("Download memory reset. Duplicate history cleared.")
        return True

    def _resolve_targets(self, url: str):
        tasks = []
        if is_youtube_url(url):
            self._log("Detected YouTube link. Building direct download list...")
            items, collection_name = extract_entries_youtube_detailed(url)
            for item in items:
                title = safe_filename(clean_song_title(item.get("title") or "", "")) or "Unknown Title"
                group = safe_filename(collection_name) if collection_name else title
                tasks.append(
                    DownloadTask(
                        youtube_url=item["url"],
                        source_input_url=url,
                        collection_name=collection_name,
                        display_title=title,
                        group_name=group,
                    )
                )
            return tasks

        self._log("Detected non-YouTube link. Parsing track metadata...")
        
        # Check if Spotify and credentials are configured
        if 'spotify.com' in url:
            spotify_id = self.config.get("spotify_client_id", "")
            spotify_secret = self.config.get("spotify_client_secret", "")
            if not spotify_id or not spotify_secret:
                self._log("⚠️ Spotify credentials not configured. See Settings > Spotify API.")
                self._log("   Get free API keys from: https://developer.spotify.com/dashboard")
                return tasks
        
        queries, collection_name = extract_music_queries(url, config=self.config)
        
        if not queries:
            self._log("❌ No tracks found. Try using YouTube URLs instead.")
            return tasks
        
        for idx, q in enumerate(queries, start=1):
            # Skip Spotify tracks with empty URLs (credentials missing)
            if not q.source_url and 'spotify.com' in url:
                self._log(f"  ⚠️ Skipping Spotify track: {q.title}")
                continue
            
            self._status(f"Searching YouTube {idx}/{len(queries)}")
            yt_url = pick_youtube_for_query(q)
            if not yt_url:
                self._log(f"  No YouTube match found: {q.artist} - {q.title}")
                continue
            title = safe_filename(clean_song_title(q.title, q.artist)) or "Unknown Title"
            group = safe_filename(collection_name) if collection_name else title
            tasks.append(
                DownloadTask(
                    youtube_url=yt_url,
                    source_input_url=url,
                    source_query=q,
                    collection_name=collection_name,
                    display_title=title,
                    group_name=group,
                )
            )
        return tasks

        self._log("Detected non-YouTube link. Parsing track metadata...")
        
        # Warn about Spotify limitations
        if 'spotify.com' in url:
            self._log("⚠️ Spotify direct downloads not supported. Use YouTube URLs for best results.")
        
        queries, collection_name = extract_music_queries(url, config=self.config)
        
        # Filter out Spotify tracks with no URL
        if 'spotify.com' in url:
            queries = [q for q in queries if q.source_url]
            if not queries:
                self._log("❌ No valid tracks found. Try using YouTube URLs instead.")
                return tasks
        
        for idx, q in enumerate(queries, start=1):
            self._status(f"Searching YouTube {idx}/{len(queries)}")
            yt_url = pick_youtube_for_query(q)
            if not yt_url:
                self._log(f"  No YouTube match found: {q.artist} - {q.title}")
                continue
            title = safe_filename(clean_song_title(q.title, q.artist)) or "Unknown Title"
            group = safe_filename(collection_name) if collection_name else title
            tasks.append(
                DownloadTask(
                    youtube_url=yt_url,
                    source_input_url=url,
                    source_query=q,
                    collection_name=collection_name,
                    display_title=title,
                    group_name=group,
                )
            )
        return tasks

    def _preview_model(self, tasks: list[DownloadTask]):
        groups = {}
        order = []
        for t in tasks:
            g = t.group_name or t.display_title or "individual"
            if g not in groups:
                groups[g] = []
                order.append(g)
            groups[g].append(t)

        model = []
        lines = []
        for g in order:
            items = groups[g]
            model.append(
                {
                    "name": g,
                    "count": len(items),
                    "songs": [{"title": s.display_title, "url": s.youtube_url} for s in items],
                }
            )
            if len(items) > 1:
                lines.append(f"* {g} ({len(items)} songs)")
            else:
                lines.append(f"* {items[0].display_title} (individual link)")
            for s in items:
                ext = QUALITY_PRESETS.get(self.quality_key, QUALITY_PRESETS["mp3_320"])["format"]
                ext_map = {"mp3": ".mp3", "flac": ".flac", "mp4": ".mp4"}
                suffix = ext_map.get(ext, ".mp3")
                lines.append(f"  - {s.display_title}{suffix} ({s.youtube_url})")
            lines.append("")

        return model, "\n".join(lines).strip()

    def analyze_links(self, raw_input: str):
        urls = extract_urls_from_input(raw_input or "")
        if not urls:
            return {"ok": False, "error": "No valid URL found in input."}

        all_tasks = []
        for idx, u in enumerate(urls, start=1):
            self._log(f"[{idx}/{len(urls)}] Resolving {u}")
            all_tasks.extend(self._resolve_targets(u))

        if not all_tasks:
            return {"ok": False, "error": "No downloadable items found."}

        dedup = []
        seen = set()
        for t in all_tasks:
            if t.youtube_url in seen:
                continue
            seen.add(t.youtube_url)
            dedup.append(t)

        token = f"preview_{threading.get_ident()}_{len(self.preview_cache)+1}"
        self.preview_cache[token] = dedup

        groups, editable_text = self._preview_model(dedup)
        self._log(f"Prepared {len(dedup)} item(s). Waiting for your confirmation...")
        self._status("Awaiting confirmation")
        return {
            "ok": True,
            "token": token,
            "total": len(dedup),
            "groups": groups,
            "editable_text": editable_text,
        }

    def _enqueue_downloads(self, tasks: list[DownloadTask]):
        with self.download_lock:
            existing = {t.youtube_url for t in self.download_queue}
            added = 0
            for t in tasks:
                if t.youtube_url in existing:
                    continue
                self.download_queue.append(t)
                existing.add(t.youtube_url)

                g = t.group_name or t.display_title
                if g not in self.group_meta:
                    self.group_meta[g] = {"total": 0, "done": 0, "pending": []}
                    self.group_order.append(g)
                self.group_meta[g]["total"] += 1
                self.group_meta[g]["pending"].append(t.display_title)
                added += 1
            qlen = len(self.download_queue)

        self._status(f"Queued: {qlen}")
        self._queue_event()
        return added

    def confirm_add_to_queue(self, token: str, edited_text: str):
        original = self.preview_cache.pop(token, [])
        if not original:
            return {"ok": False, "error": "Preview expired. Analyze again."}

        urls = extract_urls_from_input(edited_text or "")
        if not urls:
            return {"ok": False, "error": "No valid URL found in edited list."}

        by_url = {t.youtube_url: t for t in original}
        new_tasks = []
        seen = set()
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            t = by_url.get(u)
            if not t:
                title = safe_filename(u.rsplit("=", 1)[-1] or "Unknown Title")
                t = DownloadTask(youtube_url=u, source_input_url=u, display_title=title, group_name=title)
            new_tasks.append(t)

        added = self._enqueue_downloads(new_tasks)
        self._log(f"Queued {added} new item(s).")
        self._start_download_worker_if_needed()
        return {"ok": True, "added": added}

    def _start_download_worker_if_needed(self):
        with self.download_lock:
            if self.download_running:
                return
            self.stop_requested = False
            self.download_running = True
        self._download_state_event()
        threading.Thread(target=self._download_worker, daemon=True).start()

    def stop_downloads(self):
        with self.download_lock:
            if not self.download_running:
                return {"ok": False, "message": "No active downloads."}
            self.stop_requested = True
            self.download_queue.clear()
            for g in list(self.group_meta.keys()):
                self.group_meta[g]["pending"] = []
        self._log("Stop requested. Finishing current item, then terminating queue.")
        self._status("Stopping downloads...")
        self._queue_event()
        return {"ok": True, "message": "Stopping downloads..."}

    def _pop_download(self):
        with self.download_lock:
            if not self.download_queue:
                return None, 0
            task = self.download_queue.popleft()
            return task, len(self.download_queue)

    def _mark_started(self, task: DownloadTask):
        with self.download_lock:
            self.active_group = task.group_name or task.display_title
            self.active_title = task.display_title
            self.active_downloads += 1
            meta = self.group_meta.get(self.active_group)
            if meta:
                try:
                    meta["pending"].remove(task.display_title)
                except ValueError:
                    pass
        self._queue_event()

    def _mark_finished(self, task: DownloadTask):
        g = task.group_name or task.display_title
        with self.download_lock:
            self.active_downloads = max(0, self.active_downloads - 1)
            meta = self.group_meta.get(g)
            if meta:
                meta["done"] += 1
                if meta["done"] >= meta["total"]:
                    self.group_meta.pop(g, None)
                    self.group_order = [x for x in self.group_order if x != g]
            if self.active_downloads <= 0:
                self.active_group = ""
                self.active_title = ""
        self._queue_event()

    def _download_single(self, task: DownloadTask, idx: int, total: int):
        with self._state_lock:
            out_dir = Path(self.output_dir).expanduser()
            dup_mode = self.dup_mode
            quality_key = self.quality_key
            do_lyrics = self.embed_lyrics

        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            with yt_dlp.YoutubeDL(
                {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "noplaylist": True,
                    "nocheckcertificate": True,
                }
            ) as ydl:
                info = ydl.extract_info(task.youtube_url, download=False)
        except Exception as e:
            self._log(f"  Failed before download: {str(e).splitlines()[0]}")
            self._mark_finished(task)
            return False

        if not info:
            self._log("  Could not read metadata, skipped.")
            self._mark_finished(task)
            return False

        track = make_track(info)
        dup = self.tracker.check_duplicate(track)
        if dup and dup_mode == "skip":
            self._log(f"  Duplicate: '{track.title}' already downloaded at {dup['downloaded_at']}")
            self._log("  Skipped due to duplicate policy.")
            self._mark_finished(task)
            return False

        try:
            target_output = out_dir
            folder = task.collection_name or (task.group_name if task.group_name != task.display_title else "")
            if folder:
                target_output = out_dir / safe_filename(folder)
                target_output.mkdir(parents=True, exist_ok=True)

            def progress_hook(d):
                if d["status"] == "downloading":
                    total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    if total_bytes > 0:
                        downloaded_bytes = d.get("downloaded_bytes", 0)
                        pct = downloaded_bytes / total_bytes
                        self._progress_event("", idx, total, pct, task.display_title)
                elif d["status"] == "finished":
                    self._progress_event("", idx, total, 1.0, task.display_title)

            saved_track, path, actual_fmt = download_one(
                task.youtube_url,
                target_output,
                self._log,
                source_query=task.source_query,
                quality_key=quality_key,
                progress_hook=progress_hook,
            )
            self.tracker.add_download(saved_track, path)

            if do_lyrics:
                chosen_title = task.source_query.title if task.source_query and task.source_query.title else saved_track.title
                chosen_artist = task.source_query.artist if task.source_query and task.source_query.artist else saved_track.artist
                embed_lyrics_if_available(Path(path), chosen_title, chosen_artist, fmt=actual_fmt)

            return True
        except Exception as e:
            self._log(f"  Failed: {str(e).splitlines()[0]}")
            return False
        finally:
            self._mark_finished(task)

    def _download_worker(self):
        downloaded = 0
        failures = 0
        idx = 0

        try:
            with self._state_lock:
                workers = self.concurrency

            semaphore = threading.Semaphore(workers)
            threads = []

            while True:
                with self.download_lock:
                    stopping = self.stop_requested
                if stopping:
                    break

                task, remain = self._pop_download()
                if not task:
                    break

                idx += 1
                self._mark_started(task)
                self._status(f"Downloading ({idx})... queue remaining: {remain}")
                self._log(f"[{idx}] {task.display_title}")

                def run_single(t=task, i=idx, tot=idx):
                    with semaphore:
                        with self.download_lock:
                            stop = self.stop_requested
                        if stop:
                            return
                        result = self._download_single(t, i, tot)
                        if result:
                            nonlocal downloaded
                            downloaded += 1
                        else:
                            nonlocal failures
                            failures += 1

                t = threading.Thread(target=run_single, daemon=True)
                t.start()
                threads.append(t)

            for t in threads:
                t.join(timeout=300)

            self._log(f"Done. Downloaded: {downloaded}  Failed/skipped: {failures}")
            if self.notifications:
                notify("Download Complete", f"{downloaded} tracks saved. {failures} failed/skipped.")
        finally:
            with self.download_lock:
                self.download_running = False
                self.stop_requested = False
            self._status("Ready")
            self._download_state_event()
            self._queue_event()

    def open_url(self, url: str):
        url = (url or "").strip()
        if not url:
            return False
        webbrowser.open(url)
        return True


def resolve_html_path() -> Path:
    candidates = []
    here = Path(__file__).resolve().parent
    candidates.append(here / "ui" / "index.html")
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            resources = Path(sys.executable).resolve().parents[1] / "Resources"
        else:
            resources = Path(sys.executable).resolve().parent
        candidates.append(resources / "ui" / "index.html")
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def main():
    html = resolve_html_path()
    api = DownloaderAPI()
    window = webview.create_window(
        "Sully's Music Downloader",
        url=html.as_uri(),
        js_api=api,
        width=1400,
        height=900,
        min_size=(1120, 720),
        background_color="#0B111B",
    )
    api.attach_window(window)
    webview.start(debug=False, gui="edgechromium" if sys.platform == "win32" else None)


if __name__ == "__main__":
    main()
