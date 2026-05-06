import threading
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

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


class ConfirmDialog(tk.Toplevel):
    def __init__(self, parent: tk.Tk, lines: list[str]):
        super().__init__(parent)
        self.title("Confirm And Edit Links")
        self.geometry("1000x620")
        self.resizable(True, True)
        self.result = None

        self.configure(bg="#111722")
        self.transient(parent)
        self.grab_set()

        lbl = tk.Label(
            self,
            text="Review and edit links (one URL per line).",
            bg="#111722",
            fg="#e9edf5",
            font=("Helvetica Neue", 13, "bold"),
            anchor="w",
        )
        lbl.pack(fill="x", padx=14, pady=(12, 8))

        self.text = ScrolledText(self, wrap="none", undo=True, bg="#0f1622", fg="#d7deea", insertbackground="#d7deea")
        self.text.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.text.insert("1.0", "\n".join(lines))
        self.text.focus_set()

        btns = tk.Frame(self, bg="#111722")
        btns.pack(fill="x", padx=14, pady=(0, 12))

        ttk.Button(btns, text="Undo", command=self.undo).pack(side="left")
        ttk.Button(btns, text="Redo", command=self.redo).pack(side="left", padx=(8, 18))
        ttk.Button(btns, text="Add To Queue", command=self.confirm).pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=8)

        self.bind("<Command-z>", lambda e: self.undo())
        self.bind("<Command-Z>", lambda e: self.undo())
        self.bind("<Command-Shift-Z>", lambda e: self.redo())
        self.bind("<Command-y>", lambda e: self.redo())
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-Z>", lambda e: self.undo())
        self.bind("<Control-Shift-Z>", lambda e: self.redo())
        self.bind("<Control-y>", lambda e: self.redo())

    def undo(self):
        try:
            self.text.edit_undo()
        except Exception:
            pass

    def redo(self):
        try:
            self.text.edit_redo()
        except Exception:
            pass

    def confirm(self):
        urls = extract_urls_from_input(self.text.get("1.0", "end"))
        if not urls:
            messagebox.showwarning("No URLs", "Add at least one valid URL.", parent=self)
            return
        self.result = urls
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()


class ProApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("sully's music downloader")
        self.root.geometry("1360x860")
        self.root.minsize(1180, 740)

        self.tracker = DownloadTracker(DB_PATH)
        self.dup_mode = tk.StringVar(value="skip")
        self.status_var = tk.StringVar(value="Ready")

        self.analysis_queue = deque()
        self.analysis_lock = threading.Lock()
        self.analysis_running = False

        self.download_queue = deque()
        self.download_lock = threading.Lock()
        self.download_running = False

        self.group_meta = {}
        self.group_order = []
        self.active_group = ""
        self.active_title = ""
        self._render_scheduled = False

        self._configure_style()
        self._build_ui()

    def _configure_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg = "#0b0f16"
        card = "#111826"
        fg = "#e6edf7"
        muted = "#a1b1c9"

        self.root.configure(bg=bg)
        style.configure("TFrame", background=card)
        style.configure("Card.TFrame", background=card)
        style.configure("TLabel", background=card, foreground=fg)
        style.configure("Muted.TLabel", background=card, foreground=muted)
        style.configure("TButton", padding=8)

    def _build_ui(self):
        outer = tk.Frame(self.root, bg="#0b0f16")
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        outer.grid_columnconfigure(0, weight=5)
        outer.grid_columnconfigure(1, weight=2)
        outer.grid_rowconfigure(5, weight=1)

        header = tk.Frame(outer, bg="#111826", highlightthickness=1, highlightbackground="#1f2a3d")
        header.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        tk.Label(header, text="sully's music downloader", bg="#111826", fg="#edf2fb", font=("Helvetica Neue", 22, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        tk.Label(
            header,
            text="Queue links fast, review editable matches, and download with metadata/folder grouping.",
            bg="#111826",
            fg="#9fb0c8",
            font=("Helvetica Neue", 12),
        ).pack(anchor="w", padx=14, pady=(0, 10))

        left = tk.Frame(outer, bg="#0b0f16")
        left.grid(row=1, column=0, rowspan=5, sticky="nsew", padx=(0, 10))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(5, weight=1)

        self._card_label(left, 0, "Source Links", "Paste one or many links")
        self.input_box = ScrolledText(left, height=8, undo=True, wrap="word", bg="#0f1622", fg="#d7deea", insertbackground="#d7deea")
        self.input_box.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.input_box.bind("<Command-z>", lambda e: self._undo_input())
        self.input_box.bind("<Command-Shift-Z>", lambda e: self._redo_input())

        out_card = tk.Frame(left, bg="#111826", highlightthickness=1, highlightbackground="#1f2a3d")
        out_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        out_card.grid_columnconfigure(1, weight=1)
        tk.Label(out_card, text="Output Folder", bg="#111826", fg="#9fb0c8", font=("Helvetica Neue", 12)).grid(row=0, column=0, padx=(10, 8), pady=10)
        self.output_entry = ttk.Entry(out_card)
        self.output_entry.grid(row=0, column=1, sticky="ew", pady=10)
        self.output_entry.insert(0, str(Path.home() / "Music" / "sully's music downloader"))
        ttk.Button(out_card, text="Browse", command=self.pick_output).grid(row=0, column=2, padx=10, pady=10)

        opts = tk.Frame(left, bg="#111826", highlightthickness=1, highlightbackground="#1f2a3d")
        opts.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        tk.Label(opts, text="Duplicate handling", bg="#111826", fg="#9fb0c8", font=("Helvetica Neue", 12)).pack(side="left", padx=(10, 8), pady=10)
        ttk.Radiobutton(opts, text="Warn + Skip", value="skip", variable=self.dup_mode).pack(side="left", padx=8)
        ttk.Radiobutton(opts, text="Warn + Download anyway", value="force", variable=self.dup_mode).pack(side="left", padx=8)

        actions = tk.Frame(left, bg="#111826", highlightthickness=1, highlightbackground="#1f2a3d")
        actions.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(actions, text="Analyze + Add To Queue", command=self.start).pack(side="left", padx=10, pady=10)
        ttk.Button(actions, text="Reset Download Memory", command=self.reset_memory).pack(side="left", padx=(0, 10), pady=10)
        tk.Label(actions, textvariable=self.status_var, bg="#111826", fg="#9fb0c8", font=("Helvetica Neue", 12, "bold")).pack(side="left", padx=6)

        logs_card = tk.Frame(left, bg="#111826", highlightthickness=1, highlightbackground="#1f2a3d")
        logs_card.grid(row=5, column=0, sticky="nsew")
        logs_card.grid_columnconfigure(0, weight=1)
        logs_card.grid_rowconfigure(1, weight=1)
        tk.Label(logs_card, text="Terminal / Logs", bg="#111826", fg="#edf2fb", font=("Helvetica Neue", 14, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 6))
        self.log_box = ScrolledText(logs_card, undo=False, wrap="word", bg="#0f1622", fg="#d7deea", insertbackground="#d7deea")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        right_card = tk.Frame(outer, bg="#111826", highlightthickness=1, highlightbackground="#1f2a3d")
        right_card.grid(row=1, column=1, rowspan=5, sticky="nsew")
        right_card.grid_columnconfigure(0, weight=1)
        right_card.grid_rowconfigure(1, weight=1)
        tk.Label(right_card, text="Queue Status", bg="#111826", fg="#edf2fb", font=("Helvetica Neue", 16, "bold")).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 8))
        self.queue_box = ScrolledText(right_card, undo=False, wrap="word", bg="#0f1622", fg="#d7deea", insertbackground="#d7deea")
        self.queue_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.queue_box.tag_configure("group", foreground="#7cc7ff", font=("Helvetica Neue", 15, "bold"))
        self.queue_box.tag_configure("active", foreground="#45d17a", font=("Helvetica Neue", 13, "bold"))
        self.queue_box.tag_configure("song", foreground="#d7deea", font=("Helvetica Neue", 13))
        self.queue_box.tag_configure("muted", foreground="#8fa2c1", font=("Helvetica Neue", 12))
        self.queue_box.insert("1.0", "No active downloads.\n")

        self.log("Notes: Only download content you have rights to use.")

    def _card_label(self, parent, row, title, subtitle):
        card = tk.Frame(parent, bg="#111826", highlightthickness=1, highlightbackground="#1f2a3d")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 6))
        tk.Label(card, text=title, bg="#111826", fg="#edf2fb", font=("Helvetica Neue", 14, "bold")).pack(anchor="w", padx=12, pady=(8, 1))
        tk.Label(card, text=subtitle, bg="#111826", fg="#9fb0c8", font=("Helvetica Neue", 11)).pack(anchor="w", padx=12, pady=(0, 8))

    def _undo_input(self):
        try:
            self.input_box.edit_undo()
        except Exception:
            pass

    def _redo_input(self):
        try:
            self.input_box.edit_redo()
        except Exception:
            pass

    def log(self, text: str):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.log, text)
            return
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def set_status(self, text: str):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.set_status, text)
            return
        self.status_var.set(text)

    def _ui_value(self, getter):
        if threading.current_thread() is threading.main_thread():
            return getter()
        ev = threading.Event()
        out = {"value": None}

        def read():
            out["value"] = getter()
            ev.set()

        self.root.after(0, read)
        ev.wait()
        return out["value"]

    def pick_output(self):
        folder = filedialog.askdirectory(initialdir=self.output_entry.get().strip())
        if folder:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, folder)

    def reset_memory(self):
        ok = messagebox.askyesno("Reset Download Memory", "Clear duplicate history of downloaded songs?")
        if not ok:
            return
        self.tracker.reset_download_memory()
        self.log("Download memory reset. Duplicate history cleared.")

    def start(self):
        raw = self.input_box.get("1.0", "end").strip()
        if not raw:
            self.log("Please paste at least one URL.")
            return
        with self.analysis_lock:
            self.analysis_queue.append(raw)
            pending = len(self.analysis_queue)
        self.log(f"Added to analysis queue. Pending analyses: {pending}")
        self.set_status(f"Analysis queue: {pending}")
        self.input_box.delete("1.0", "end")
        self._start_analysis_worker_if_needed()

    def _start_analysis_worker_if_needed(self):
        with self.analysis_lock:
            if self.analysis_running:
                return
            self.analysis_running = True
        threading.Thread(target=self._analysis_worker, daemon=True).start()

    def _pop_analysis(self):
        with self.analysis_lock:
            if not self.analysis_queue:
                return None, 0
            raw = self.analysis_queue.popleft()
            return raw, len(self.analysis_queue)

    def _analysis_worker(self):
        try:
            while True:
                raw, remaining = self._pop_analysis()
                if raw is None:
                    break
                self.set_status(f"Analyzing links... ({remaining} pending)")
                self._analyze_and_queue(raw)
        finally:
            with self.analysis_lock:
                self.analysis_running = False
            if not self.download_running:
                self.set_status("Ready")

    def _resolve_targets(self, url: str):
        tasks = []
        if is_youtube_url(url):
            self.log("Detected YouTube link. Building direct download list...")
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

        self.log("Detected non-YouTube link. Parsing track metadata...")
        queries, collection_name = extract_music_queries(url)
        for idx, q in enumerate(queries, start=1):
            self.set_status(f"Searching YouTube {idx}/{len(queries)}")
            yt_url = pick_youtube_for_query(q)
            if not yt_url:
                self.log(f"  No YouTube match found: {q.artist} - {q.title}")
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

    def _preview_lines(self, tasks: list[DownloadTask]):
        groups = {}
        order = []
        for t in tasks:
            g = t.group_name or t.display_title or "individual"
            if g not in groups:
                groups[g] = []
                order.append(g)
            groups[g].append(t)

        lines = []
        for g in order:
            items = groups[g]
            if len(items) > 1:
                lines.append(f"*{g}* ({len(items)} songs)")
            else:
                lines.append(f"*{items[0].display_title}* (individual link)")
            for item in items:
                lines.append(f"   {item.display_title}.mp3 ({item.youtube_url})")
            lines.append("")
        return lines

    def _ask_confirm_urls(self, lines: list[str]):
        if threading.current_thread() is threading.main_thread():
            dlg = ConfirmDialog(self.root, lines)
            self.root.wait_window(dlg)
            return dlg.result

        ev = threading.Event()
        out = {"urls": None}

        def show():
            dlg = ConfirmDialog(self.root, lines)
            self.root.wait_window(dlg)
            out["urls"] = dlg.result
            ev.set()

        self.root.after(0, show)
        ev.wait()
        return out["urls"]

    def _analyze_and_queue(self, raw_input: str):
        urls = extract_urls_from_input(raw_input)
        if not urls:
            self.log("No valid URL found in input.")
            return

        all_tasks = []
        for i, u in enumerate(urls, start=1):
            self.log(f"[{i}/{len(urls)}] Resolving {u}")
            all_tasks.extend(self._resolve_targets(u))

        if not all_tasks:
            self.log("No downloadable items found.")
            return

        dedup = []
        seen = set()
        for t in all_tasks:
            if t.youtube_url in seen:
                continue
            seen.add(t.youtube_url)
            dedup.append(t)

        self.log(f"Prepared {len(dedup)} item(s). Waiting for your confirmation...")
        confirmed = self._ask_confirm_urls(self._preview_lines(dedup))
        if not confirmed:
            self.log("Add-to-queue canceled by user.")
            return

        by_url = {t.youtube_url: t for t in dedup}
        new_tasks = []
        seen2 = set()
        for u in confirmed:
            if u in seen2:
                continue
            seen2.add(u)
            t = by_url.get(u)
            if not t:
                title = safe_filename(u.rsplit("=", 1)[-1] or "Unknown Title")
                t = DownloadTask(youtube_url=u, source_input_url=u, display_title=title, group_name=title)
            new_tasks.append(t)

        added = self._enqueue_downloads(new_tasks)
        self.log(f"Queued {added} new item(s).")
        self._start_download_worker_if_needed()

    def _enqueue_downloads(self, tasks: list[DownloadTask]):
        with self.download_lock:
            existing = {t.youtube_url for t in self.download_queue}
            added = 0
            for t in tasks:
                if t.youtube_url in existing:
                    continue
                self.download_queue.append(t)
                existing.add(t.youtube_url)
                g = t.group_name
                if g not in self.group_meta:
                    self.group_meta[g] = {"total": 0, "done": 0, "pending": []}
                    self.group_order.append(g)
                self.group_meta[g]["total"] += 1
                self.group_meta[g]["pending"].append(t.display_title)
                added += 1
            qlen = len(self.download_queue)
        self.set_status(f"Queued: {qlen}")
        self._schedule_queue_render()
        return added

    def _start_download_worker_if_needed(self):
        with self.download_lock:
            if self.download_running:
                return
            self.download_running = True
        threading.Thread(target=self._download_worker, daemon=True).start()

    def _pop_download(self):
        with self.download_lock:
            if not self.download_queue:
                return None, 0
            t = self.download_queue.popleft()
            return t, len(self.download_queue)

    def _mark_started(self, t: DownloadTask):
        with self.download_lock:
            self.active_group = t.group_name
            self.active_title = t.display_title
            m = self.group_meta.get(t.group_name)
            if m:
                try:
                    m["pending"].remove(t.display_title)
                except ValueError:
                    pass
        self._schedule_queue_render()

    def _mark_finished(self, t: DownloadTask):
        with self.download_lock:
            m = self.group_meta.get(t.group_name)
            if m:
                m["done"] += 1
                if m["done"] >= m["total"]:
                    self.group_meta.pop(t.group_name, None)
                    self.group_order = [g for g in self.group_order if g != t.group_name]
            self.active_group = ""
            self.active_title = ""
        self._schedule_queue_render()

    def _schedule_queue_render(self):
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self._schedule_queue_render)
            return
        if self._render_scheduled:
            return
        self._render_scheduled = True
        self.root.after(100, self._render_queue_now)

    def _render_queue_now(self):
        self._render_scheduled = False
        self.queue_box.delete("1.0", "end")

        def add(text: str, tag: str | None = None):
            if tag:
                self.queue_box.insert("end", text, tag)
            else:
                self.queue_box.insert("end", text)

        rendered = 0

        if self.active_group:
            m = self.group_meta.get(self.active_group, {"total": 1, "done": 0, "pending": []})
            if m["total"] > 1:
                add(f"{self.active_group} ({m['done']}/{m['total']})\n", "group")
            else:
                add(f"{self.active_group}\n", "group")
            add(f"  • {self.active_title}.mp3 downloading\n", "active")
            for p in m["pending"][:8]:
                add(f"  • {p}.mp3\n", "song")
            add("\n")
            rendered += 1

        for g in self.group_order:
            if g == self.active_group:
                continue
            m = self.group_meta.get(g)
            if not m:
                continue
            if m["total"] > 1:
                add(f"{g} ({m['done']}/{m['total']})\n", "group")
            else:
                add(f"{g}\n", "group")
            for p in m["pending"][:6]:
                add(f"  • {p}.mp3\n", "song")
            add("\n")
            rendered += 1

        if rendered == 0:
            add("No active downloads.\n", "muted")

    def _download_worker(self):
        out_dir = Path(self._ui_value(lambda: self.output_entry.get().strip())).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        dup_mode = self._ui_value(lambda: self.dup_mode.get())

        downloaded = 0
        failures = []
        idx = 0

        try:
            while True:
                task, remain = self._pop_download()
                if task is None:
                    break

                idx += 1
                self._mark_started(task)
                self.set_status(f"Downloading... Queue remaining: {remain}")
                self.log(f"[{idx}] Checking {task.youtube_url}")

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
                    failures.append((task.youtube_url, str(e).splitlines()[0]))
                    self.log(f"  Failed before download: {failures[-1][1]}")
                    self._mark_finished(task)
                    continue

                if not info:
                    failures.append((task.youtube_url, "Could not read metadata"))
                    self.log("  Could not read metadata, skipped.")
                    self._mark_finished(task)
                    continue

                track = make_track(info)
                dup = self.tracker.check_duplicate(track)
                if dup and dup_mode == "skip":
                    self.log(f"  Duplicate warning: '{track.title}' already downloaded at {dup['downloaded_at']}")
                    self.log("  Skipped due to duplicate policy.")
                    self._mark_finished(task)
                    continue

                try:
                    target_output = out_dir
                    folder = task.collection_name or (task.group_name if task.group_name != task.display_title else "")
                    if folder:
                        target_output = out_dir / safe_filename(folder)
                        target_output.mkdir(parents=True, exist_ok=True)

                    saved_track, path = download_one(task.youtube_url, target_output, self.log, source_query=task.source_query)
                    self.tracker.add_download(saved_track, path)
                    downloaded += 1
                except Exception as e:
                    failures.append((task.youtube_url, str(e).splitlines()[0]))
                    self.log(f"  Failed: {failures[-1][1]}")
                finally:
                    self._mark_finished(task)

            self.log(f"Done. Downloaded: {downloaded}  Error: {len(failures)}")
            if failures:
                for i, (u, r) in enumerate(failures, start=1):
                    self.log(f'{i}. "{u}" couldnt be downloaded: {r}')
        finally:
            with self.download_lock:
                self.download_running = False
            if not self.analysis_running:
                self.set_status("Ready")
            self._schedule_queue_render()


def main():
    root = tk.Tk()
    app = ProApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
