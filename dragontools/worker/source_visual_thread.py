# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import traceback

from PyQt6.QtCore import QThread, pyqtSignal

from .process_control import terminate_process_tree
from .source_visual_check import SourceVisualCheckService
from .source_visual_models import SourceVisualCheckSettings


_ACTIVE_SOURCE_VISUAL_THREADS: set[QThread] = set()


def active_source_visual_workers() -> tuple:
    """Return manual source-visual workers that must participate in shutdown."""
    return tuple(_ACTIVE_SOURCE_VISUAL_THREADS)


def _release_worker(worker: QThread) -> None:
    _ACTIVE_SOURCE_VISUAL_THREADS.discard(worker)
    worker.deleteLater()


class SourceVisualCheckThread(QThread):
    """Cancelable manual source-visual check that never blocks the GUI thread."""

    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        path: str,
        settings: SourceVisualCheckSettings,
        ffmpeg_path: str,
        ffprobe_path: str,
    ) -> None:
        # Keep no QObject parent: the worker may outlive a closing widget until
        # the coordinated shutdown gate has actually stopped its subprocess.
        super().__init__(None)
        self.path = str(path)
        self.settings = settings
        self.ffmpeg_path = str(ffmpeg_path or "")
        self.ffprobe_path = str(ffprobe_path or "")
        self.abort_requested = False
        self.abort_type: str | None = None
        self._current_process = None
        self._process_lock = threading.Lock()
        _ACTIVE_SOURCE_VISUAL_THREADS.add(self)
        self.finished.connect(lambda: _release_worker(self))

    @property
    def current_process(self):
        with self._process_lock:
            return self._current_process

    def request_abort(self, mode: str = "sofort") -> None:
        self.abort_requested = True
        self.abort_type = mode
        if mode == "sofort":
            terminate_process_tree(
                self,
                self._process_lock,
                attr_name="_current_process",
                label="Quellbildprüfung",
            )

    def cancel(self) -> None:
        self.request_abort("sofort")

    def run(self) -> None:
        if self.abort_requested:
            return
        try:
            service = SourceVisualCheckService(
                ffmpeg_path=self.ffmpeg_path,
                ffprobe_path=self.ffprobe_path,
                worker=self,
            )
            result = service.check(self.path, self.settings)
            if not self.abort_requested:
                self.result_ready.emit(result)
        except Exception:
            if not self.abort_requested:
                self.failed.emit(traceback.format_exc())


__all__ = ["SourceVisualCheckThread", "active_source_visual_workers"]
