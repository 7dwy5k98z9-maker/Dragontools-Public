# -*- coding: utf-8 -*-
"""Background worker for potentially expensive media-library searches."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal


class MediaLibrarySearchThread(QThread):
    """Execute one SQLite library search outside the Qt GUI thread."""

    completed = pyqtSignal(object, object, object)  # request, rows, error

    def __init__(self, *, service, db_path: str, request: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._db_path = str(db_path)
        self._request = dict(request)

    def run(self) -> None:
        try:
            rows = self._service.search(
                self._db_path,
                self._request["preset"],
                self._request["text"],
                scope=self._request["scope"],
                media_type=self._request["media_type"],
                limit=500,
            )
        except Exception as exc:  # Worker boundary: transport error to GUI thread.
            self.completed.emit(self._request, [], exc)
            return
        self.completed.emit(self._request, rows, None)
