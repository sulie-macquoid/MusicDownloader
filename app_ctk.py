import threading
from collections import deque
from pathlib import Path

import customtkinter as ctk
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
)


class PreviewDialog(ctk.CTkToplevel):
    def __init__(self, parent, lines: list[str]):
        super().__init__(parent)
        self.parent = parent
        self.result_urls = None

        self.title("Confirm And Edit Links")
        self.geometry("980x600")
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text="Review rows below. Edit/replace URLs directly and confirm.",
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 8))

        self.box = ctk.CTkTextbox(self, wrap="none", undo=True, autoseparators=True, maxundo=-1)
        self.box.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self.box.insert("1.0", "\n".join(lines))
        self.box.focus_set()

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkButton(actions, text="Undo", width=80, command=self.do_undo).pack(side="left")
        ctk.CTkButton(actions, text="Redo", width=80, command=self.do_redo).pack(side="left", padx=(8, 18))
        ctk.CTkButton(actions, text="Add To Queue", command=self.confirm).pack(side="left")
        ctk.CTkButton(
            actions,
            text="Cancel",
            command=self.cancel,
            fg_color="#444",
            hover_color="#555",
        ).pack(side="left", padx=8)

        self.bind("<Command-z>", lambda e: self.do_undo())
        self.bind("<Command-Z>", lambda e: self.do_undo())
        self.bind("<Command-Shift-Z>", lambda e: self.do_redo())
        self.bind("<Command-y>", lambda e: self.do_redo())
        self.bind("<Control-z>", lambda e: self.do_undo())
        self.bind("<Control-y>", lambda e: self.do_redo())

    def confirm(self):
        edited = extract_urls_from_input(self.box.get("1.0", "end"))
        if not edited:
            self.parent.log("No valid URL in confirmation dialog. Add at least one URL.")
            return
        self.result_urls = edited
        self.destroy()

    def cancel(self):
        self.result_urls = None
        self.destroy()

    def do_undo(self):
        try:
            self.box.edit_undo()
        except Exception:
            pass

    def do_redo(self):
        try:
            self.box.edit_redo()
        except Exception:
            pass


class ModernApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("sully's music downloader")
        self.geometry("1360x860")
        self.minsize(1220, 760)

        self.palette = {
            "bg": "#0b0f16",
            "card": "#111826",
            "card_alt": "#0f1522",
            "line": "#1f2a3d",
            "text": "#e6edf7",
            "muted": "#9fb0c8",
            "accent": "#2f7df6",
            "accent_hover": "#3c88ff",
            "danger": "#7c3440",
            "danger_hover": "#93414d",
        }
        self.configure(fg_color=self.palette["bg"])

        self.tracker = DownloadTracker(DB_PATH)
        self.dup_mode = ctk.StringVar(value="skip")

        self.queue = deque()
        self.queue_lock = threading.Lock()
        self.worker_running = False
        self.analysis_queue = deque()
        self.analysis_lock = threading.Lock()
        self.analysis_running = False

        self.group_order: list[str] = []
        self.group_meta: dict[str, dict] = {}
        self.active_group = ""
        self.active_title = ""
        self._queue_render_scheduled = False

        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=5)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(6, weight=1)

        header = ctk.CTkFrame(self, fg_color=self.palette["card"], corner_radius=16, border_width=1, border_color=self.palette["line"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="sully's music downloader",
            anchor="w",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=self.palette["text"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(
            header,
            text="Paste links, review matched videos with titles, queue downloads, and monitor progress by playlist/album.",
            anchor="w",
            font=ctk.CTkFont(size=13),
            text_color=self.palette["muted"],
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(2, 12))

        url_card = ctk.CTkFrame(self, fg_color=self.palette["card"], corner_radius=14, border_width=1, border_color=self.palette["line"])
        url_card.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))
        url_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            url_card,
            text="Source Links",
            anchor="w",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.palette["text"],
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            url_card,
            text="You can paste many links at once (one per line or mixed text).",
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=self.palette["muted"],
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))
        self.url_box = ctk.CTkTextbox(
            url_card,
            height=130,
            fg_color=self.palette["card_alt"],
            border_width=1,
            border_color=self.palette["line"],
            undo=True,
            autoseparators=True,
            maxundo=-1,
        )
        self.url_box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.url_box.bind("<Command-z>", lambda e: self._undo_main())
        self.url_box.bind("<Command-Z>", lambda e: self._undo_main())
        self.url_box.bind("<Command-Shift-Z>", lambda e: self._redo_main())
        self.url_box.bind("<Command-y>", lambda e: self._redo_main())
        self.url_box.bind("<Control-z>", lambda e: self._undo_main())
        self.url_box.bind("<Control-y>", lambda e: self._redo_main())

        output_row = ctk.CTkFrame(self, fg_color=self.palette["card"], corner_radius=14, border_width=1, border_color=self.palette["line"])
        output_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        output_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(output_row, text="Output Folder", text_color=self.palette["muted"]).grid(row=0, column=0, padx=(12, 8), pady=12)
        self.output_entry = ctk.CTkEntry(output_row, fg_color=self.palette["card_alt"], border_color=self.palette["line"])
        self.output_entry.grid(row=0, column=1, sticky="ew", pady=10)
        self.output_entry.insert(0, str(Path.home() / "Music" / "sully's music downloader"))
        ctk.CTkButton(
            output_row,
            text="Browse",
            width=110,
            command=self.pick_output,
            fg_color=self.palette["accent"],
            hover_color=self.palette["accent_hover"],
        ).grid(row=0, column=2, padx=12, pady=10)

        options_row = ctk.CTkFrame(self, fg_color=self.palette["card"], corner_radius=14, border_width=1, border_color=self.palette["line"])
        options_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 10))

        ctk.CTkLabel(options_row, text="Duplicate handling", text_color=self.palette["muted"]).pack(side="left", padx=(12, 8), pady=10)
        ctk.CTkRadioButton(options_row, text="Warn + Skip", value="skip", variable=self.dup_mode, text_color=self.palette["text"]).pack(side="left", padx=8)
        ctk.CTkRadioButton(options_row, text="Warn + Download anyway", value="force", variable=self.dup_mode, text_color=self.palette["text"]).pack(side="left", padx=8)

        action_row = ctk.CTkFrame(self, fg_color=self.palette["card"], corner_radius=14, border_width=1, border_color=self.palette["line"])
        action_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 10))

        self.analyze_btn = ctk.CTkButton(
            action_row,
            text="Analyze + Add To Queue",
            command=self.start,
            fg_color=self.palette["accent"],
            hover_color=self.palette["accent_hover"],
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.analyze_btn.pack(side="left", padx=10, pady=10)

        self.reset_btn = ctk.CTkButton(
            action_row,
            text="Reset Download Memory",
            fg_color=self.palette["danger"],
            hover_color=self.palette["danger_hover"],
            command=self.reset_memory,
        )
        self.reset_btn.pack(side="left", padx=0, pady=10)

        self.status_label = ctk.CTkLabel(action_row, text="Ready", text_color=self.palette["muted"], font=ctk.CTkFont(size=14))
        self.status_label.pack(side="left", padx=16)

        logs_card = ctk.CTkFrame(self, fg_color=self.palette["card"], corner_radius=14, border_width=1, border_color=self.palette["line"])
        logs_card.grid(row=5, column=0, sticky="nsew", padx=16, pady=(0, 16))
        logs_card.grid_columnconfigure(0, weight=1)
        logs_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(logs_card, text="Terminal / Logs", anchor="w", font=ctk.CTkFont(size=15, weight="bold"), text_color=self.palette["text"]).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        self.log_box = ctk.CTkTextbox(logs_card, fg_color=self.palette["card_alt"], border_width=1, border_color=self.palette["line"])
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        sidebar = ctk.CTkFrame(self, fg_color=self.palette["card"], corner_radius=14, border_width=1, border_color=self.palette["line"])
        sidebar.grid(row=1, column=1, rowspan=5, sticky="nsew", padx=(0, 16), pady=(0, 16))
        sidebar.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            sidebar,
            text="Queue Status",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
            text_color=self.palette["text"],
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        self.queue_box = ctk.CTkTextbox(sidebar, fg_color=self.palette["card_alt"], border_width=1, border_color=self.palette["line"])
        self.queue_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.queue_box.insert("1.0", "No active downloads.")

        self.log("Notes: Only download content you have rights to use.")

    def pick_output(self):
        import tkinter.filedialog as fd

        folder = fd.askdirectory(initialdir=self.output_entry.get().strip())
        if folder:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, folder)

    def log(self, text: str):
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self.log, text)
            return
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def set_status(self, text: str):
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self.set_status, text)
            return
        self.status_label.configure(text=text)

    def set_busy(self, busy: bool):
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self.set_busy, busy)
            return
        state = "disabled" if busy else "normal"
        self.reset_btn.configure(state=state)
        self.output_entry.configure(state=state)
        self.analyze_btn.configure(state="normal")
        self.url_box.configure(state="normal")

    def reset_memory(self):
        import tkinter.messagebox as mb

        ok = mb.askyesno("Reset Download Memory", "Clear duplicate history of downloaded songs?")
        if not ok:
            return
        self.tracker.reset_download_memory()
        self.log("Download memory reset. Duplicate history cleared.")

    def start(self):
        raw = self.url_box.get("1.0", "end").strip()
        if not raw:
            self.log("Please paste at least one URL.")
            return
        with self.analysis_lock:
            self.analysis_queue.append(raw)
            pending = len(self.analysis_queue)
        self.log(f"Added to analysis queue. Pending analyses: {pending}")
        self.set_status(f"Analysis queue: {pending}")
        self.url_box.delete("1.0", "end")
        self.start_analysis_worker_if_needed()

    def _undo_main(self):
        try:
            self.url_box.edit_undo()
        except Exception:
            pass

    def _redo_main(self):
        try:
            self.url_box.edit_redo()
        except Exception:
            pass

    def start_analysis_worker_if_needed(self):
        with self.analysis_lock:
            if self.analysis_running:
                return
            self.analysis_running = True
        threading.Thread(target=self.run_analysis_worker, daemon=True).start()

    def pop_next_analysis(self):
        with self.analysis_lock:
            if not self.analysis_queue:
                return None, 0
            raw = self.analysis_queue.popleft()
            return raw, len(self.analysis_queue)

    def run_analysis_worker(self):
        try:
            while True:
                raw, remaining = self.pop_next_analysis()
                if raw is None:
                    break
                self.set_status(f"Analyzing links... ({remaining} pending)")
                self.analyze_and_queue(raw)
        finally:
            with self.analysis_lock:
                self.analysis_running = False
            if not self.worker_running:
                self.set_status("Ready")

    def ensure_task_labels(self, task: DownloadTask):
        if not task.display_title:
            if task.source_query and task.source_query.title:
                task.display_title = safe_filename(clean_song_title(task.source_query.title, task.source_query.artist))
            else:
                task.display_title = safe_filename(task.youtube_url.rsplit("=", 1)[-1] or "Unknown Title")

        if not task.group_name:
            if task.collection_name:
                task.group_name = safe_filename(task.collection_name)
            else:
                task.group_name = task.display_title

        # Keep collection folder behavior stable across queue/edit flows.
        if not task.collection_name and task.group_name and task.group_name != task.display_title:
            task.collection_name = task.group_name

    def resolve_targets(self, url: str):
        if is_youtube_url(url):
            self.log("Detected YouTube link. Building direct download list...")
            items, collection_name = extract_entries_youtube_detailed(url)
            tasks = []
            for item in items:
                display = safe_filename(clean_song_title(item.get("title") or "", ""))
                tasks.append(
                    DownloadTask(
                        youtube_url=item["url"],
                        source_input_url=url,
                        collection_name=collection_name,
                        display_title=display if display else "Unknown Title",
                        group_name=safe_filename(collection_name) if collection_name else "",
                    )
                )
            return tasks

        self.log("Detected non-YouTube link. Parsing track metadata...")
        queries, collection_name = extract_music_queries(url)
        tasks = []
        for idx, q in enumerate(queries, start=1):
            self.set_status(f"Searching YouTube {idx}/{len(queries)}")
            yt_url = pick_youtube_for_query(q)
            if not yt_url:
                self.log(f"  No YouTube match found: {q.artist} - {q.title}")
                continue
            tasks.append(
                DownloadTask(
                    youtube_url=yt_url,
                    source_input_url=url,
                    source_query=q,
                    collection_name=collection_name,
                )
            )
        return tasks

    def build_grouped_preview_lines(self, tasks: list[DownloadTask]) -> list[str]:
        groups = {}
        order = []
        for t in tasks:
            group = t.group_name or t.display_title or "individual"
            if group not in groups:
                groups[group] = []
                order.append(group)
            groups[group].append(t)

        lines = []
        for group in order:
            items = groups[group]
            count = len(items)
            if count > 1:
                lines.append(f"*{group}* ({count} songs)")
            else:
                lines.append(f"*{items[0].display_title or group}* (individual link)")
            for item in items:
                title = item.display_title or "Unknown Title"
                lines.append(f"   {title}.mp3 ({item.youtube_url})")
            lines.append("")
        return lines

    def ask_confirmation_urls(self, preview_lines: list[str]):
        if threading.current_thread() is threading.main_thread():
            dlg = PreviewDialog(self, preview_lines)
            self.wait_window(dlg)
            return dlg.result_urls

        event = threading.Event()
        out = {"urls": None}

        def ask():
            dlg = PreviewDialog(self, preview_lines)
            self.wait_window(dlg)
            out["urls"] = dlg.result_urls
            event.set()

        self.after(0, ask)
        event.wait()
        return out["urls"]

    def analyze_and_queue(self, raw_input: str):
        self.set_status("Analyzing links...")
        input_urls = extract_urls_from_input(raw_input)
        if not input_urls:
            self.log("No valid URL found in input.")
            self.set_status("Ready")
            return

        all_tasks: list[DownloadTask] = []
        for idx, one_url in enumerate(input_urls, start=1):
            self.log(f"[{idx}/{len(input_urls)}] Resolving {one_url}")
            all_tasks.extend(self.resolve_targets(one_url))

        if not all_tasks:
            self.log("No downloadable items found.")
            self.set_status("Ready")
            return

        deduped = []
        seen = set()
        for t in all_tasks:
            if t.youtube_url in seen:
                continue
            seen.add(t.youtube_url)
            deduped.append(t)

        for t in deduped:
            self.ensure_task_labels(t)

        preview_lines = self.build_grouped_preview_lines(deduped)
        self.log(f"Prepared {len(deduped)} item(s). Waiting for your confirmation...")
        confirmed_urls = self.ask_confirmation_urls(preview_lines)
        if not confirmed_urls:
            self.log("Add-to-queue canceled by user.")
            self.set_status("Ready")
            return

        task_by_url = {t.youtube_url: t for t in deduped}
        new_tasks = []
        seen2 = set()
        for u in confirmed_urls:
            if u in seen2:
                continue
            seen2.add(u)
            task = task_by_url.get(u) or DownloadTask(youtube_url=u, source_input_url=u)
            self.ensure_task_labels(task)
            new_tasks.append(task)

        added = self.enqueue_tasks(new_tasks)
        self.log(f"Queued {added} new item(s).")
        self.url_box.delete("1.0", "end")
        self.start_worker_if_needed()

    def render_queue_sidebar(self):
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self.render_queue_sidebar)
            return
        if self._queue_render_scheduled:
            return
        self._queue_render_scheduled = True
        self.after(90, self._render_queue_sidebar_now)

    def _render_queue_sidebar_now(self):
        self._queue_render_scheduled = False

        lines = []
        if self.active_group:
            meta = self.group_meta.get(self.active_group, {"total": 1, "done": 0, "pending": []})
            total = meta["total"]
            done = meta["done"]
            if total > 1:
                lines.append(f"* {self.active_group} [{done}/{total}]")
            else:
                lines.append(f"* {self.active_group}")
            lines.append(f"   - {self.active_title} downloading")
            for t in meta["pending"][:8]:
                lines.append(f"   - {t}")
            lines.append("")

        for group in self.group_order:
            if group == self.active_group:
                continue
            meta = self.group_meta.get(group)
            if not meta:
                continue
            total = meta["total"]
            done = meta["done"]
            if total > 1:
                lines.append(f"* {group} [{done}/{total}]")
            else:
                lines.append(f"* {group}")
            for t in meta["pending"][:6]:
                lines.append(f"   - {t}")
            lines.append("")

        if not lines:
            lines = ["No active downloads."]

        self.queue_box.delete("1.0", "end")
        self.queue_box.insert("1.0", "\n".join(lines).rstrip() + "\n")

    def enqueue_tasks(self, tasks: list[DownloadTask]) -> int:
        with self.queue_lock:
            existing = {t.youtube_url for t in self.queue}
            added = 0
            for t in tasks:
                if t.youtube_url in existing:
                    continue
                self.queue.append(t)
                existing.add(t.youtube_url)
                group = t.group_name
                if group not in self.group_meta:
                    self.group_meta[group] = {"total": 0, "done": 0, "pending": []}
                    self.group_order.append(group)
                self.group_meta[group]["total"] += 1
                self.group_meta[group]["pending"].append(t.display_title)
                added += 1
            q_len = len(self.queue)
        self.set_status(f"Queued: {q_len}")
        self.render_queue_sidebar()
        return added

    def start_worker_if_needed(self):
        with self.queue_lock:
            if self.worker_running:
                return
            self.worker_running = True
        self.set_busy(True)
        threading.Thread(target=self.run_download_worker, daemon=True).start()

    def pop_next_task(self):
        with self.queue_lock:
            if not self.queue:
                return None, 0
            task = self.queue.popleft()
            return task, len(self.queue)

    def mark_task_started(self, task: DownloadTask):
        with self.queue_lock:
            group = task.group_name
            self.active_group = group
            self.active_title = task.display_title
            meta = self.group_meta.get(group)
            if meta:
                try:
                    meta["pending"].remove(task.display_title)
                except ValueError:
                    pass
        self.render_queue_sidebar()

    def mark_task_finished(self, task: DownloadTask):
        with self.queue_lock:
            group = task.group_name
            meta = self.group_meta.get(group)
            if meta:
                meta["done"] += 1
                if meta["done"] >= meta["total"]:
                    self.group_meta.pop(group, None)
                    self.group_order = [g for g in self.group_order if g != group]
            self.active_group = ""
            self.active_title = ""
        self.render_queue_sidebar()

    def run_download_worker(self):
        out_dir = Path(self.output_entry.get().strip()).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)

        downloaded = 0
        failures: list[tuple[str, str]] = []
        index = 0

        try:
            while True:
                task, remaining = self.pop_next_task()
                if task is None:
                    break

                index += 1
                target = task.youtube_url
                self.mark_task_started(task)
                self.set_status(f"Downloading... Queue remaining: {remaining}")
                self.log(f"[{index}] Checking {target}")

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
                        info = ydl.extract_info(target, download=False)
                except Exception as e:
                    reason = str(e).splitlines()[0] if str(e) else "Metadata fetch failed"
                    self.log(f"  Failed before download: {reason}")
                    failures.append((target, reason))
                    self.mark_task_finished(task)
                    continue

                if not info:
                    self.log("  Could not read metadata, skipped.")
                    failures.append((target, "Could not read metadata"))
                    self.mark_task_finished(task)
                    continue

                track = make_track(info)
                dup = self.tracker.check_duplicate(track)
                if dup and self.dup_mode.get() == "skip":
                    self.log(f"  Duplicate warning: '{track.title}' already downloaded at {dup['downloaded_at']}")
                    self.log("  Skipped due to duplicate policy.")
                    self.mark_task_finished(task)
                    continue

                try:
                    target_output = out_dir
                    folder_name = task.collection_name or (
                        task.group_name if task.group_name and task.group_name != task.display_title else ""
                    )
                    if folder_name:
                        target_output = out_dir / safe_filename(folder_name)
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
                    reason = str(e).splitlines()[0] if str(e) else "Download failed"
                    self.log(f"  Failed: {reason}")
                    failures.append((target, reason))
                finally:
                    self.mark_task_finished(task)

            self.log(f"Done. Downloaded: {downloaded}  Error: {len(failures)}")
            if failures:
                for idx, (url, reason) in enumerate(failures, start=1):
                    self.log(f'{idx}. "{url}" couldnt be downloaded: {reason}')

        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            with self.queue_lock:
                self.worker_running = False
            self.set_status("Ready")
            self.set_busy(False)
            self.render_queue_sidebar()


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = ModernApp()
    app.mainloop()


if __name__ == "__main__":
    main()
