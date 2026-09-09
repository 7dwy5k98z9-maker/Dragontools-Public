# -*- coding: utf-8 -*-
"""
Created on Thu Apr 16 01:49:23 2026

@author: Dragon Developer
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QCheckBox,
    QProgressBar, QTextEdit, QGroupBox, QMessageBox
)

from ..worker.audio_mux_thread import AudioMuxThread
from .video_file_input import (
    VIDEO_EXTENSIONS as _VIDEO_EXTS,
    VideoDropListWidget as _DropListWidget,
    add_video_paths_to_list,
    choose_directory,
    choose_video_files,
    iter_video_files_from_dir,
)


class AudioMuxerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: AudioMuxThread | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        info = QLabel(
            "Audio Muxer: Video/Untertitel/Attachments werden kopiert. "
            "Auf alle Audio-Spuren greift nur der Konvertierungs-Teil der Audio-Regeln. "
            "Ausgabe immer als MKV."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        files_box = QGroupBox("Quelldateien")
        files_layout = QVBoxLayout(files_box)

        self.file_list = _DropListWidget(self, on_paths_dropped=self._add_paths)
        self.file_list.setAlternatingRowColors(True)
        files_layout.addWidget(self.file_list)

        row = QHBoxLayout()
        btn_add_files = QPushButton("➕ Dateien")
        btn_add_dir = QPushButton("📁 Ordner")
        btn_remove = QPushButton("➖ Entfernen")
        btn_clear = QPushButton("🗑️ Leeren")

        btn_add_files.clicked.connect(self._pick_files)
        btn_add_dir.clicked.connect(self._pick_dir)
        btn_remove.clicked.connect(self._remove_selected)
        btn_clear.clicked.connect(self.file_list.clear)

        row.addWidget(btn_add_files)
        row.addWidget(btn_add_dir)
        row.addWidget(btn_remove)
        row.addWidget(btn_clear)
        row.addStretch(1)

        files_layout.addLayout(row)
        root.addWidget(files_box)

        options_box = QGroupBox("Optionen")
        options_layout = QVBoxLayout(options_box)

        self.chk_overwrite = QCheckBox("Original überschreiben")
        self.chk_overwrite.setChecked(False)
        options_layout.addWidget(self.chk_overwrite)

        note = QLabel(
            "Ist 'Original überschreiben' deaktiviert, wird die Ausgabe "
            "neben der Quelle als *_Audiomux.mkv gespeichert."
        )
        note.setWordWrap(True)
        options_layout.addWidget(note)

        root.addWidget(options_box)

        prog_box = QGroupBox("Fortschritt")
        prog_layout = QVBoxLayout(prog_box)

        self.lbl_current = QLabel("Aktuelle Datei: –")
        self.progress_file = QProgressBar()
        self.progress_total = QProgressBar()

        prog_layout.addWidget(self.lbl_current)
        prog_layout.addWidget(QLabel("Datei"))
        prog_layout.addWidget(self.progress_file)
        prog_layout.addWidget(QLabel("Gesamt"))
        prog_layout.addWidget(self.progress_total)

        root.addWidget(prog_box)

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout(log_box)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(220)
        log_layout.addWidget(self.log)
        root.addWidget(log_box)

        ctrl = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start")
        self.btn_cancel = QPushButton("❌ Abbrechen")
        self.btn_cancel.setEnabled(False)

        self.btn_start.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self._cancel)

        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_cancel)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

    def _iter_video_files_from_dir(self, folder: str) -> list[str]:
        return iter_video_files_from_dir(folder, extensions=_VIDEO_EXTS)

    def _add_paths(self, paths: list[str]) -> None:
        added = add_video_paths_to_list(self.file_list, paths, extensions=_VIDEO_EXTS)
        if added:
            self.log.append(f"ℹ️  {added} Datei(en) hinzugefügt.")

    def _pick_files(self) -> None:
        files = choose_video_files(self)
        if files:
            self._add_paths(files)

    def _pick_dir(self) -> None:
        folder = choose_directory(self)
        if folder:
            self._add_paths([folder])

    def _remove_selected(self) -> None:
        for item in self.file_list.selectedItems():
            row = self.file_list.row(item)
            self.file_list.takeItem(row)

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.chk_overwrite.setEnabled(not running)

    def _start(self) -> None:
        try:
            files = [
                str(self.file_list.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.file_list.count())
            ]
            if not files:
                QMessageBox.warning(self, "Keine Dateien", "Bitte mindestens eine Datei hinzufügen.")
                return

            self.progress_file.setValue(0)
            self.progress_total.setValue(0)
            self.lbl_current.setText("Aktuelle Datei: –")
            self.log.clear()

            self._worker = AudioMuxThread(
                files=files,
                overwrite_original=self.chk_overwrite.isChecked(),
                parent=self,
            )
            self._worker.log_line.connect(self.log.append)
            self._worker.progress_total.connect(self.progress_total.setValue)
            self._worker.progress_file.connect(self._on_file_progress)
            self._worker.file_result.connect(self._on_file_result)
            self._worker.finished.connect(self._on_finished)

            self._set_running(True)
            self._worker.start()

        except Exception:
            self.log.append("❌ Unbehandelte Ausnahme in _start()")
            self.log.append(traceback.format_exc())
            self._set_running(False)

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.log.append("⚠️  Abbruch angefordert ...")

    def _on_file_progress(self, path: str, pct: int) -> None:
        self.lbl_current.setText(f"Aktuelle Datei: {Path(path).name}")
        self.progress_file.setValue(pct)

    def _on_file_result(self, path: str, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self.log.append(f"{icon} {Path(path).name} → {message}")

    def _on_finished(self) -> None:
        self._set_running(False)
        self.progress_file.setValue(0)
        self.lbl_current.setText("Aktuelle Datei: –")
        self.log.append("")
        self.log.append("🏁 Audio-Mux abgeschlossen.")
        self._worker = None
