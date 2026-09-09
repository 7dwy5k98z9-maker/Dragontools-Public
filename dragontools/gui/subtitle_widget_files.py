# -*- coding: utf-8 -*-
"""Dateifilter und Drag-and-Drop-Liste des Untertitel-Widgets."""
from __future__ import annotations

import re
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QListWidgetItem

def _parse_exts(qt_filter: str) -> set[str]:
    """Extrahiert Dateiendungen aus einem Qt-Filterstring, z.B. '(*.mkv *.mp4)' → {'mkv','mp4'}."""
    return {m.lower() for m in re.findall(r'\*\.(\w+)', qt_filter)}


class _FileDropList(QListWidget):
    """QListWidget mit Drag-and-Drop-Unterstützung für lokale Dateien."""

    def __init__(self, filter_exts: set[str] | None = None, parent=None):
        super().__init__(parent)
        self._filter_exts = {e.lower() for e in (filter_exts or [])}
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        existing = {
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
        }
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if not path or path in existing:
                continue
            ext = Path(path).suffix.lower().lstrip('.')
            if self._filter_exts and ext not in self._filter_exts:
                continue
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.addItem(item)
            existing.add(path)
        event.acceptProposedAction()
