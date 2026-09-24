# -*- coding: utf-8 -*-
"""Background workers for media-library Fix Queue discovery and execution."""
from __future__ import annotations

import threading

from PyQt6.QtCore import QSettings, QThread, pyqtSignal

from ..core.settings_app import APP_NAME, APP_ORG
from ..worker.media_library_fix_service import MediaLibraryFixService


class MediaLibraryFixDiscoveryThread(QThread):
    completed = pyqtSignal(object, object)  # result, error

    def __init__(self, *, service, db_path: str, categories: set[str], parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._db_path = str(db_path)
        self._categories = set(categories)

    def run(self) -> None:
        try:
            result = self._service.discover_fix_issues(self._db_path, categories=self._categories)
        except Exception as exc:  # QThread boundary: transport into GUI thread.
            self.completed.emit(None, exc)
            return
        self.completed.emit(result, None)


class MediaLibraryFixWorker(QThread):
    item_started = pyqtSignal(int, int, object)
    item_finished = pyqtSignal(int, int, object)
    completed = pyqtSignal(object, bool)  # outcomes, aborted
    log_line = pyqtSignal(str)

    def __init__(self, *, db_path: str, issues: list, tools, parent=None) -> None:
        super().__init__(parent)
        self._db_path = str(db_path)
        self._issues = list(issues)
        self._tools = tools
        self.abort_requested = False
        self.metadata_commit_lock = threading.RLock()
        self._process_lock = threading.RLock()
        self._current_process = None

    def request_abort(self) -> None:
        with self.metadata_commit_lock:
            self.abort_requested = True

    def run(self) -> None:
        settings = QSettings(APP_ORG, APP_NAME)
        service = MediaLibraryFixService(
            db_path=self._db_path,
            settings=settings,
            tools=self._tools,
            log=self._log,
            worker=self,
        )
        outcomes = []
        total = len(self._issues)
        for index, issue in enumerate(self._issues, start=1):
            if self.abort_requested:
                break
            self.item_started.emit(index, total, issue)
            outcome = service.execute(issue)
            outcomes.append(outcome)
            self.item_finished.emit(index, total, outcome)
            if self.abort_requested:
                break
        self.completed.emit(outcomes, bool(self.abort_requested))

    def _log(self, message: str, level: str = "info") -> None:
        prefix = "⚠️ " if str(level).casefold() in {"warn", "warning", "error"} else ""
        self.log_line.emit(prefix + str(message))


__all__ = ["MediaLibraryFixDiscoveryThread", "MediaLibraryFixWorker"]
