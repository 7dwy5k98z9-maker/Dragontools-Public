# -*- coding: utf-8 -*-
"""Gemeinsame Datei-/Drag&Drop-Helfer für einfache Video-Worker-Widgets."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QListWidget, QListWidgetItem, QWidget

from ..core.callback_dispatch import invoke_callback, is_callback_like
from ..core.path_syntax import normalize_user_path, path_compare_key
from .drop_path_extractor import _extract_paths_from_mime_data, _mime_has_file_payload


VIDEO_EXTENSIONS = frozenset({
    ".mkv", ".mp4", ".m4v", ".mov", ".avi", ".ts", ".m2ts", ".wmv", ".webm"
})
VIDEO_FILE_FILTER = (
    "Video (*.mkv *.mp4 *.m4v *.mov *.avi *.ts *.m2ts *.wmv *.webm);;Alle Dateien (*)"
)


class VideoDropListWidget(QListWidget):
    """QListWidget mit explizitem Callback für abgelegte lokale Pfade."""

    def __init__(self, parent=None, *, on_paths_dropped: Callable[[list[str]], None] | None = None):
        super().__init__(parent)
        self._on_paths_dropped = on_paths_dropped
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

    def dragEnterEvent(self, event):
        if event.mimeData() and _mime_has_file_payload(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData() and _mime_has_file_payload(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime is None or not _mime_has_file_payload(mime):
            super().dropEvent(event)
            return

        callback = self._on_paths_dropped
        if not is_callback_like(callback):
            event.ignore()
            return

        paths = _extract_paths_from_mime_data(mime)
        if not paths:
            event.ignore()
            return
        invoke_callback(callback, paths)
        event.acceptProposedAction()


def iter_video_files_from_dir(
    folder: str,
    *,
    extensions: Iterable[str] = VIDEO_EXTENSIONS,
) -> list[str]:
    allowed = {str(ext).lower() for ext in extensions}
    out: list[str] = []
    for root, _, files in os.walk(folder):
        for name in files:
            path = Path(root) / name
            if path.suffix.lower() in allowed:
                out.append(str(path.resolve()))
    return out


def add_video_paths_to_list(
    file_list: QListWidget,
    paths: Iterable[str],
    *,
    extensions: Iterable[str] = VIDEO_EXTENSIONS,
) -> int:
    """Fügt Video-Dateien dedupliziert hinzu und liefert die Anzahl neuer Einträge."""
    allowed = {str(ext).lower() for ext in extensions}
    existing = {
        path_compare_key(normalize_user_path(file_list.item(i).data(Qt.ItemDataRole.UserRole)))
        for i in range(file_list.count())
        if file_list.item(i).data(Qt.ItemDataRole.UserRole)
    }

    added = 0
    for raw in paths:
        normalized_raw = normalize_user_path(raw)
        if not normalized_raw:
            continue
        path = Path(normalized_raw)
        candidates = (
            iter_video_files_from_dir(str(path), extensions=allowed)
            if path.is_dir()
            else [normalize_user_path(path.resolve())] if path.is_file() and path.suffix.lower() in allowed else []
        )
        for candidate in candidates:
            candidate = normalize_user_path(candidate)
            key = path_compare_key(candidate)
            if key in existing:
                continue
            item = QListWidgetItem(Path(candidate).name)
            item.setToolTip(candidate)
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            file_list.addItem(item)
            existing.add(key)
            added += 1
    return added


def choose_video_files(parent: QWidget, title: str = "Videodateien wählen") -> list[str]:
    files, _ = QFileDialog.getOpenFileNames(parent, title, "", VIDEO_FILE_FILTER)
    return list(files or [])


def choose_directory(parent: QWidget, title: str = "Ordner wählen", start: str = "") -> str:
    return str(QFileDialog.getExistingDirectory(parent, title, start) or "")


__all__ = [
    "VIDEO_EXTENSIONS",
    "VIDEO_FILE_FILTER",
    "VideoDropListWidget",
    "iter_video_files_from_dir",
    "add_video_paths_to_list",
    "choose_video_files",
    "choose_directory",
]
