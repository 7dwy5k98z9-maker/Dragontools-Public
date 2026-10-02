# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog

from ..core.media_analyzer import analyze_media

# A cancelled dialog must not destroy a still-running QThread. Analysis calls
# have their own timeouts; retain the worker until it really finishes.
_ACTIVE_LOADERS: set[QThread] = set()


def active_override_loaders() -> tuple:
    return tuple(_ACTIVE_LOADERS)


def _release_loader(loader):
    _ACTIVE_LOADERS.discard(loader)
    loader.deleteLater()

class _OverrideAnalyzeThread(QThread):
    """Führt analyze_media() im Hintergrund aus damit der Dialog nicht blockt."""

    loaded = pyqtSignal(object, object, object)
    failed = pyqtSignal(str)

    def __init__(self, path: str, tools, parent=None):
        super().__init__(None)
        _ACTIVE_LOADERS.add(self)
        self.finished.connect(lambda: _release_loader(self))
        self._path = path
        self._tools = tools
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def request_abort(self, mode="sofort") -> None:
        self.abort()

    def run(self) -> None:
        if self._abort:
            return
        try:
            mi = analyze_media(self._path, self._tools)
            if self._abort:
                return
            if getattr(mi, "analysis_source", "Unbekannt") == "Unbekannt" or not any(
                getattr(mi, name, None) for name in ("video_streams", "audio_streams", "subtitle_streams")
            ):
                self.failed.emit("Keine Analysequelle lieferte verwertbare Mediendaten.")
                return
            audio_streams = list(getattr(mi, "audio_streams", []) or [])
            subtitle_streams = list(getattr(mi, "subtitle_streams", []) or [])
            if self._abort:
                return
            self.loaded.emit(mi, audio_streams, subtitle_streams)
        except Exception:
            if self._abort:
                return
            self.failed.emit(traceback.format_exc())


class _OverrideDialog(QDialog):
    """Dialog, der beim Schliessen einen evtl. laufenden Loader korrekt beendet."""

    def done(self, result: int) -> None:
        loader = getattr(self, "_override_loader", None)
        if loader is not None:
            try:
                # Also cancel a loader whose zero-delay start is still queued.
                loader.abort()
            except RuntimeError:
                pass
            finally:
                self._override_loader = None

        super().done(result)
