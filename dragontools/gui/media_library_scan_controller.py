# -*- coding: utf-8 -*-
"""Thread-Lifecycle des Speicherpfad-Scans für die Mediathek-GUI."""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..core.media_library_scan import scan_storage_paths_to_database
from ..core.media_library_types import PathMapping


class MediaLibraryStorageScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    log_line = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        db_path: str,
        scan_roots: list[PathMapping],
        tools: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._scan_roots = scan_roots
        self._tools = tools
        self._abort = False

    def request_abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            result = scan_storage_paths_to_database(
                self._db_path,
                self._scan_roots,
                tools=self._tools,
                replace_existing=True,
                logger=self.log_line.emit,
                progress=self.progress.emit,
                should_abort=lambda: self._abort,
            )
            self.result_ready.emit(result)
        except Exception as exc:
            # QThread-Grenze: Fehler müssen als Signal in den GUI-Thread transportiert werden.
            self.failed.emit(str(exc))


class MediaLibraryScanCoordinator:
    """Besitzt genau einen Scan-Worker und dessen Signal-Lifecycle."""

    def __init__(
        self,
        *,
        parent: QWidget,
        on_progress: Callable[[int, int, str], None],
        on_log: Callable[[str], None],
        on_result: Callable[[object], None],
        on_failed: Callable[[str], None],
        on_running_changed: Callable[[bool], None],
    ) -> None:
        self._parent = parent
        self._on_progress = on_progress
        self._on_log = on_log
        self._on_result = on_result
        self._on_failed = on_failed
        self._on_running_changed = on_running_changed
        self._worker: MediaLibraryStorageScanWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._worker is not None

    @property
    def worker(self) -> MediaLibraryStorageScanWorker | None:
        return self._worker

    def start(self, *, db_path: str, scan_roots: list[PathMapping], tools: Any) -> bool:
        if self._worker is not None:
            return False
        worker = MediaLibraryStorageScanWorker(
            db_path=db_path,
            scan_roots=scan_roots,
            tools=tools,
            parent=self._parent,
        )
        self._worker = worker
        worker.progress.connect(self._on_progress)
        worker.log_line.connect(self._on_log)
        worker.result_ready.connect(self._on_result)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._finished)
        self._on_running_changed(True)
        worker.start()
        return True

    def abort(self) -> bool:
        if self._worker is None:
            return False
        self._worker.request_abort()
        return True

    def _finished(self) -> None:
        self._worker = None
        self._on_running_changed(False)
