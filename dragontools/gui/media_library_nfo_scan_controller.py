# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..core.media_library_nfo_scan import scan_nfo_inventory


class MediaLibraryNfoScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    log_line = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, db_path: str, full_audit: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._full_audit = full_audit
        self._abort = False

    def request_abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            result = scan_nfo_inventory(
                self._db_path,
                full_audit=self._full_audit,
                backup=True,
                logger=self.log_line.emit,
                progress=self.progress.emit,
                should_abort=lambda: self._abort,
            )
            self.result_ready.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class MediaLibraryNfoScanCoordinator:
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
        self._worker: MediaLibraryNfoScanWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._worker is not None

    def start(self, *, db_path: str, full_audit: bool) -> bool:
        if self._worker is not None:
            return False
        worker = MediaLibraryNfoScanWorker(db_path=db_path, full_audit=full_audit, parent=self._parent)
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
