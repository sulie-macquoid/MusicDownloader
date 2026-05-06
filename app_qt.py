import sys
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from PySide6.QtCore import QObject, QThread, Signal, qInstallMessageHandler
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import (
    DB_PATH,
    DownloadTracker,
    DownloadTask,
    extract_entries_youtube,
    extract_music_queries,
    extract_urls_from_input,
    is_youtube_url,
    make_track,
    pick_youtube_for_query,
    download_one,
    safe_filename,
)


@dataclass
class ResolveResult:
    tasks: list[DownloadTask]


class ResolverWorker(QObject):
    log = Signal(str)
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, raw_input: str):
        super().__init__()
        self.raw_input = raw_input

    def run(self):
        try:
            urls = extract_urls_from_input(self.raw_input)
            if not urls:
                self.failed.emit("No valid URL found in input.")
                return

            all_tasks: list[DownloadTask] = []
            for idx, url in enumerate(urls, start=1):
                self.log.emit(f"[{idx}/{len(urls)}] Resolving {url}")
                self.status.emit(f"Resolving {idx}/{len(urls)}")
                tasks, _preview = self.resolve_one_url(url)
                all_tasks.extend(tasks)

            if not all_tasks:
                self.failed.emit("No downloadable items found.")
                return

            deduped = []
            seen = set()
            for task in all_tasks:
                if task.youtube_url in seen:
                    continue
                seen.add(task.youtube_url)
                deduped.append(task)

            self.done.emit(ResolveResult(tasks=deduped))
        except Exception as e:
            self.failed.emit(f"Resolve error: {e}")

    def resolve_one_url(self, url: str):
        if is_youtube_url(url):
            self.log.emit("Detected YouTube link. Building direct download list...")
            urls, collection_name = extract_entries_youtube(url)
            tasks = [DownloadTask(youtube_url=u, source_input_url=url, collection_name=collection_name) for u in urls]
            preview = list(urls)
            return tasks, preview

        self.log.emit("Detected non-YouTube link. Parsing track metadata...")
        queries, collection_name = extract_music_queries(url)
        if not queries:
            return [], []

        self.log.emit(f"Parsed {len(queries)} track(s). Searching YouTube best matches...")
        tasks = []
        preview = []
        for idx, q in enumerate(queries, start=1):
            self.status.emit(f"Matching {idx}/{len(queries)}")
            yt_url = pick_youtube_for_query(q)
            if not yt_url:
                self.log.emit(f"  No YouTube match found: {q.artist} - {q.title}")
                continue
            tasks.append(
                DownloadTask(
                    youtube_url=yt_url,
                    source_input_url=url,
                    source_query=q,
                    collection_name=collection_name,
                )
            )
            preview.append(yt_url)

        return tasks, preview


class DownloaderWorker(QObject):
    log = Signal(str)
    status = Signal(str)
    done = Signal(int, int)
    failed = Signal(str)

    def __init__(self, tasks: list[DownloadTask], output_dir: str, dup_mode: str):
        super().__init__()
        self.tasks = tasks
        self.output_dir = output_dir
        self.dup_mode = dup_mode

    def run(self):
        try:
            out = Path(self.output_dir).expanduser()
            out.mkdir(parents=True, exist_ok=True)
            tracker = DownloadTracker(DB_PATH)

            downloaded = 0
            skipped = 0

            for idx, task in enumerate(self.tasks, start=1):
                target = task.youtube_url
                self.status.emit(f"Downloading {idx}/{len(self.tasks)}")
                self.log.emit(f"[{idx}/{len(self.tasks)}] Checking {target}")

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
                    self.log.emit("  Could not read metadata, skipped.")
                    skipped += 1
                    continue

                track = make_track(info)
                dup = tracker.check_duplicate(track)
                if dup:
                    self.log.emit(f"  Duplicate warning: '{track.title}' already downloaded at {dup['downloaded_at']}")
                    if self.dup_mode == "skip":
                        self.log.emit("  Skipped due to duplicate policy.")
                        skipped += 1
                        continue

                try:
                    target_out = out
                    if task.collection_name:
                        target_out = out / safe_filename(task.collection_name)
                        target_out.mkdir(parents=True, exist_ok=True)
                    saved_track, path = download_one(
                        target,
                        target_out,
                        self.log.emit,
                        source_query=task.source_query,
                    )
                    tracker.add_download(saved_track, path)
                    downloaded += 1
                except Exception as e:
                    self.log.emit(f"  Failed: {e}")
                    skipped += 1

            self.done.emit(downloaded, skipped)
        except Exception as e:
            self.failed.emit(f"Download error: {e}")


class PreviewDialog(QDialog):
    def __init__(self, lines: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Download List")
        self.resize(900, 560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Review and edit links below (one URL per line), then confirm."))

        self.text = QTextEdit()
        self.text.setPlainText("\n".join(lines))
        font = QFont("Consolas" if sys.platform == "win32" else "Menlo")
        font.setStyleHint(QFont.Monospace)
        self.text.setFont(font)
        layout.addWidget(self.text)

        buttons = QHBoxLayout()
        self.btn_start = QPushButton("Start Download")
        self.btn_cancel = QPushButton("Cancel")
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_cancel)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.btn_start.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def get_urls(self):
        return extract_urls_from_input(self.text.toPlainText())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sully's music downloader")
        self.resize(1060, 760)

        self.resolve_thread = None
        self.download_thread = None
        self.pending_tasks: list[DownloadTask] = []

        root = QWidget()
        self.setCentralWidget(root)
        grid = QGridLayout(root)

        grid.addWidget(QLabel("Paste URL(s) (YouTube / YouTube Music / Spotify / Apple / Others):"), 0, 0, 1, 3)
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("Paste one or multiple links here...")
        self.url_input.setFixedHeight(110)
        grid.addWidget(self.url_input, 1, 0, 1, 3)

        grid.addWidget(QLabel("Output Folder:"), 2, 0)
        self.output_input = QLineEdit(str(Path.home() / "Music" / "sully's music downloader"))
        grid.addWidget(self.output_input, 2, 1)
        self.browse_btn = QPushButton("Browse")
        grid.addWidget(self.browse_btn, 2, 2)

        mode_wrap = QHBoxLayout()
        mode_wrap.addWidget(QLabel("If duplicate found:"))
        self.dup_skip = QRadioButton("Warn + Skip")
        self.dup_force = QRadioButton("Warn + Download anyway")
        self.dup_skip.setChecked(True)
        mode_wrap.addWidget(self.dup_skip)
        mode_wrap.addWidget(self.dup_force)
        mode_wrap.addStretch(1)
        grid.addLayout(mode_wrap, 3, 0, 1, 3)

        self.analyze_btn = QPushButton("Analyze + Preview + Download")
        self.reset_memory_btn = QPushButton("Reset Download Memory")
        actions = QHBoxLayout()
        actions.addWidget(self.analyze_btn)
        actions.addWidget(self.reset_memory_btn)
        actions.addStretch(1)
        grid.addLayout(actions, 4, 0, 1, 3)

        grid.addWidget(QLabel("Terminal / Logs:"), 5, 0, 1, 3)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        font = QFont("Menlo")
        font.setStyleHint(QFont.Monospace)
        self.log_box.setFont(font)
        grid.addWidget(self.log_box, 6, 0, 1, 3)

        status = QStatusBar()
        self.setStatusBar(status)
        self.set_status("Ready")

        self.browse_btn.clicked.connect(self.on_browse)
        self.analyze_btn.clicked.connect(self.on_analyze)
        self.reset_memory_btn.clicked.connect(self.on_reset_memory)

        self.log("Notes: Only download content you have rights to use.")

    def log(self, text: str):
        self.log_box.append(text)

    def set_status(self, text: str):
        self.statusBar().showMessage(text)

    def set_busy(self, busy: bool):
        self.analyze_btn.setEnabled(not busy)
        self.reset_memory_btn.setEnabled(not busy)
        self.browse_btn.setEnabled(not busy)
        self.url_input.setEnabled(not busy)
        self.output_input.setEnabled(not busy)
        self.dup_skip.setEnabled(not busy)
        self.dup_force.setEnabled(not busy)

    def on_reset_memory(self):
        confirm = QMessageBox.question(
            self,
            "Reset Download Memory",
            "This will clear duplicate history of downloaded songs. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        tracker = DownloadTracker(DB_PATH)
        tracker.reset_download_memory()
        self.log("Download memory reset. Duplicate history cleared.")

    def on_browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_input.text())
        if folder:
            self.output_input.setText(folder)

    def on_analyze(self):
        raw = self.url_input.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "Missing Input", "Paste at least one URL.")
            return

        self.pending_tasks = []
        self.set_busy(True)
        self.set_status("Analyzing links...")

        self.resolve_thread = QThread(self)
        self.resolver = ResolverWorker(raw)
        self.resolver.moveToThread(self.resolve_thread)

        self.resolve_thread.started.connect(self.resolver.run)
        self.resolver.log.connect(self.log)
        self.resolver.status.connect(self.set_status)
        self.resolver.done.connect(self.on_resolve_done)
        self.resolver.failed.connect(self.on_resolve_failed)
        self.resolver.done.connect(self.resolve_thread.quit)
        self.resolver.failed.connect(self.resolve_thread.quit)
        self.resolve_thread.finished.connect(self.resolve_thread.deleteLater)

        self.resolve_thread.start()

    def on_resolve_done(self, result: ResolveResult):
        self.set_busy(False)
        deduped_tasks = result.tasks
        self.log(f"Prepared {len(deduped_tasks)} item(s). Waiting for your confirmation...")

        initial_urls = [t.youtube_url for t in deduped_tasks]
        dialog = PreviewDialog(initial_urls, self)
        if dialog.exec() == QDialog.Accepted:
            edited_urls = dialog.get_urls()
            if not edited_urls:
                self.pending_tasks = []
                self.set_status("Ready")
                self.log("No valid URL in confirmation dialog. Canceled.")
                return

            task_by_url = {t.youtube_url: t for t in deduped_tasks}
            final_tasks = []
            seen = set()
            for u in edited_urls:
                if u in seen:
                    continue
                seen.add(u)
                final_tasks.append(task_by_url.get(u) or DownloadTask(youtube_url=u, source_input_url=u))

            self.pending_tasks = final_tasks
            self.set_status("Confirmed. Starting download...")
            self.on_download()
        else:
            self.pending_tasks = []
            self.set_status("Canceled")
            self.log("Download canceled by user.")

    def on_resolve_failed(self, message: str):
        self.set_busy(False)
        self.set_status("Ready")
        self.log(f"Error: {message}")

    def on_download(self):
        if not self.pending_tasks:
            QMessageBox.information(self, "No Tasks", "Analyze and confirm links first.")
            return

        out = self.output_input.text().strip()
        if not out:
            QMessageBox.warning(self, "Missing Output", "Choose an output folder.")
            return

        dup_mode = "skip" if self.dup_skip.isChecked() else "force"

        self.set_busy(True)
        self.set_status("Downloading...")

        self.download_thread = QThread(self)
        self.downloader = DownloaderWorker(self.pending_tasks, out, dup_mode)
        self.downloader.moveToThread(self.download_thread)

        self.download_thread.started.connect(self.downloader.run)
        self.downloader.log.connect(self.log)
        self.downloader.status.connect(self.set_status)
        self.downloader.done.connect(self.on_download_done)
        self.downloader.failed.connect(self.on_download_failed)
        self.downloader.done.connect(self.download_thread.quit)
        self.downloader.failed.connect(self.download_thread.quit)
        self.download_thread.finished.connect(self.download_thread.deleteLater)

        self.download_thread.start()

    def on_download_done(self, downloaded: int, skipped: int):
        self.set_busy(False)
        self.pending_tasks = []
        self.set_status("Ready")
        self.log(f"Done. Downloaded: {downloaded}, skipped/failed: {skipped}")

    def on_download_failed(self, message: str):
        self.set_busy(False)
        self.pending_tasks = []
        self.set_status("Ready")
        self.log(f"Error: {message}")


def main():
    def _qt_message_filter(mode, context, message):
        # Suppress noisy Qt cursor warnings that do not affect behavior.
        if "QTextCursor::setPosition: Position '1' out of range" in message:
            return
        print(message)

    qInstallMessageHandler(_qt_message_filter)
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
