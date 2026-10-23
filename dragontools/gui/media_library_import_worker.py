# -*- coding: utf-8 -*-
"""Jellyfin-Import im Hintergrund; Widgets bleiben im GUI-Thread."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from weakref import WeakSet

_ACTIVE_IMPORT_WORKERS: WeakSet = WeakSet()


def active_media_library_import_workers():
    return tuple(worker for worker in _ACTIVE_IMPORT_WORKERS if worker.isRunning())


class MediaLibraryImportWorker(QThread):
    progress = pyqtSignal(int, int, str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, service, jellyfin_db, db_path, mappings,
                 analyze_existing_files, tools, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._jellyfin_db = jellyfin_db
        self._db_path = db_path
        self._mappings = list(mappings)
        self._analyze_existing_files = analyze_existing_files
        self._tools = tools
        _ACTIVE_IMPORT_WORKERS.add(self)
        self.finished.connect(self._release_registration)

    def _release_registration(self) -> None:
        _ACTIVE_IMPORT_WORKERS.discard(self)

    def run(self) -> None:
        try:
            result = self._service.import_jellyfin(
                self._jellyfin_db, self._db_path, self._mappings,
                analyze_existing_files=self._analyze_existing_files,
                tools=self._tools, progress=self.progress.emit,
            )
            self.result_ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
