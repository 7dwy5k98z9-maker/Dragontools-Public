from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QCheckBox,
    QProgressBar,
    QTextEdit,
    QMessageBox,
    QGroupBox,
)

from ..rules.rule_loader import load_subtitle_rules
from ..worker.mp4_remux_thread import MP4RemuxThread
from .video_file_input import (
    VIDEO_EXTENSIONS as _VIDEO_EXTS,
    VideoDropListWidget as _DropListWidget,
    add_video_paths_to_list,
    choose_directory,
    choose_video_files,
    iter_video_files_from_dir,
)


class MP4RemuxWidget(QWidget):
    """Lokales MP4-Remux-Widget ohne DV-Logik."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: MP4RemuxThread | None = None
        self.output_edit: QLineEdit | None = None
        self.file_list: _DropListWidget | None = None
        self.audio_rules_cb: QCheckBox | None = None
        self.export_subs_cb: QCheckBox | None = None
        self.ignore_subs_cb: QCheckBox | None = None
        self.faststart_cb: QCheckBox | None = None
        self.progress_bar: QProgressBar | None = None
        self.log_edit: QTextEdit | None = None
        self.start_button: QPushButton | None = None
        self.abort_button: QPushButton | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        info = QLabel(
            "MP4-Remux ohne DV: Video wird nie reencodiert, sondern nur kopiert. "
            "Audio wird nach den bestehenden Audio-Regeln MP4-kompatibel gemacht. "
            "Untertitel folgen der globalen MP4-Regel: Sidecar oder, soweit kompatibel, intern als mov_text."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        files_box = QGroupBox("Quelldateien")
        files_layout = QVBoxLayout(files_box)

        self.file_list = _DropListWidget(self, on_paths_dropped=self._add_paths)
        self.file_list.setAlternatingRowColors(True)
        files_layout.addWidget(self.file_list)

        file_btn_row = QHBoxLayout()
        btn_add_files = QPushButton("➕ Dateien")
        btn_add_dir = QPushButton("📁 Ordner")
        btn_remove = QPushButton("➖ Entfernen")
        btn_clear = QPushButton("🗑️ Leeren")

        btn_add_files.clicked.connect(self._add_files)
        btn_add_dir.clicked.connect(self._add_dir)
        btn_remove.clicked.connect(self._remove_selected)
        btn_clear.clicked.connect(self._clear_files)

        file_btn_row.addWidget(btn_add_files)
        file_btn_row.addWidget(btn_add_dir)
        file_btn_row.addWidget(btn_remove)
        file_btn_row.addWidget(btn_clear)
        file_btn_row.addStretch(1)
        files_layout.addLayout(file_btn_row)
        root.addWidget(files_box)

        out_box = QGroupBox("Ziel")
        out_layout = QHBoxLayout(out_box)
        out_layout.addWidget(QLabel("Zielordner:"))
        self.output_edit = QLineEdit()
        out_layout.addWidget(self.output_edit)
        browse_btn = QPushButton("Durchsuchen")
        browse_btn.clicked.connect(self._browse_output)
        out_layout.addWidget(browse_btn)
        root.addWidget(out_box)

        options_box = QGroupBox("Optionen")
        options_layout = QVBoxLayout(options_box)
        self.audio_rules_cb = QCheckBox("Audio-Regeln aktiv")
        self.audio_rules_cb.setChecked(True)
        self.export_subs_cb = QCheckBox("Untertitel übernehmen (globale MP4-Regel)")
        self.export_subs_cb.setChecked(True)
        self.ignore_subs_cb = QCheckBox("Untertitel ignorieren")
        self.faststart_cb = QCheckBox("faststart aktiv")
        self.faststart_cb.setChecked(True)
        options_layout.addWidget(self.audio_rules_cb)
        options_layout.addWidget(self.export_subs_cb)
        options_layout.addWidget(self.ignore_subs_cb)
        options_layout.addWidget(self.faststart_cb)
        root.addWidget(options_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(220)
        root.addWidget(self.log_edit)

        btn_row = QHBoxLayout()
        self.start_button = QPushButton("MP4-Remux starten")
        self.abort_button = QPushButton("Abbrechen")
        self.abort_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        self.abort_button.clicked.connect(self._abort)
        btn_row.addWidget(self.start_button)
        btn_row.addWidget(self.abort_button)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

    def _append_log(self, text: str) -> None:
        if self.log_edit is not None:
            self.log_edit.append(text)

    def _iter_video_files_from_dir(self, folder: str) -> list[str]:
        return iter_video_files_from_dir(folder, extensions=_VIDEO_EXTS)

    def _add_paths(self, paths: list[str]) -> None:
        if self.file_list is None:
            return
        added = add_video_paths_to_list(self.file_list, paths, extensions=_VIDEO_EXTS)
        if added:
            self._append_log(f"ℹ️  {added} Datei(en) hinzugefügt.")

    def _add_files(self) -> None:
        files = choose_video_files(self)
        if files:
            self._add_paths(files)

    def _add_dir(self) -> None:
        folder = choose_directory(self)
        if folder:
            self._add_paths([folder])

    def _remove_selected(self) -> None:
        if self.file_list is None:
            return
        for item in self.file_list.selectedItems():
            row = self.file_list.row(item)
            self.file_list.takeItem(row)

    def _clear_files(self) -> None:
        if self.file_list is not None:
            self.file_list.clear()

    def _browse_output(self) -> None:
        if self.output_edit is None:
            return
        folder = choose_directory(self, "Zielordner wählen", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def _set_running(self, running: bool) -> None:
        if self.start_button is not None:
            self.start_button.setEnabled(not running)
        if self.abort_button is not None:
            self.abort_button.setEnabled(running)
        if self.file_list is not None:
            self.file_list.setEnabled(not running)
        if self.output_edit is not None:
            self.output_edit.setEnabled(not running)
        if self.audio_rules_cb is not None:
            self.audio_rules_cb.setEnabled(not running)
        if self.export_subs_cb is not None:
            self.export_subs_cb.setEnabled(not running)
        if self.ignore_subs_cb is not None:
            self.ignore_subs_cb.setEnabled(not running)
        if self.faststart_cb is not None:
            self.faststart_cb.setEnabled(not running)

    def _start(self) -> None:
        try:
            if self.file_list is None:
                return

            files = [
                str(self.file_list.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.file_list.count())
            ]
            if not files:
                QMessageBox.warning(self, "Keine Dateien", "Bitte mindestens eine Datei hinzufügen.")
                return

            output_dir = self.output_edit.text().strip() if self.output_edit is not None else ""
            if output_dir:
                out_path = Path(output_dir)
                if not out_path.exists() or not out_path.is_dir():
                    QMessageBox.warning(self, "Ungültiger Zielordner", "Bitte einen gültigen Zielordner wählen.")
                    return

            if self.progress_bar is not None:
                self.progress_bar.setValue(0)
            if self.log_edit is not None:
                self.log_edit.clear()

            self._worker = MP4RemuxThread(
                files=files,
                output_dir=output_dir or None,
                apply_audio_rules=bool(self.audio_rules_cb and self.audio_rules_cb.isChecked()),
                export_subtitles=bool(self.export_subs_cb and self.export_subs_cb.isChecked()),
                ignore_subtitles=bool(self.ignore_subs_cb and self.ignore_subs_cb.isChecked()),
                subtitle_rules=load_subtitle_rules(default={}, reporter=self._append_log),
                faststart=bool(self.faststart_cb and self.faststart_cb.isChecked()),
                parent=self,
            )
            self._worker.log_line.connect(self._append_log)
            self._worker.progress.connect(self._on_progress)
            self._worker.file_progress.connect(self._on_file_progress)
            self._worker.file_result.connect(self._on_file_result)
            self._worker.finished.connect(self._on_finished)

            self._set_running(True)
            self._append_log(f"▶ Starte MP4-Remux für {len(files)} Datei(en) …")
            self._worker.start()
        except Exception:
            self._append_log("❌ Unbehandelte Ausnahme in _start()")
            self._append_log(traceback.format_exc())
            self._set_running(False)

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _abort(self) -> None:
        if self._worker is not None:
            self._worker.request_abort()
            self._append_log("⚠️  Abbruch angefordert ...")

    def _on_progress(self, pct: int) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)

    def _on_file_progress(self, path: str, pct: int, _obj) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)
        self._append_log(f"ℹ️  {Path(path).name}: {pct}%")

    def _on_file_result(self, path: str, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self._append_log(f"{icon} {Path(path).name} → {message}")

    def _on_finished(self) -> None:
        self._set_running(False)
        self._append_log("")
        self._append_log("🏁 MP4-Remux abgeschlossen.")
        self._worker = None
