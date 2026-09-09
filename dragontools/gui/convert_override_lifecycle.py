# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog

from ..core.media_analyzer import analyze_media

class _OverrideAnalyzeThread(QThread):
    """Führt analyze_media() im Hintergrund aus damit der Dialog nicht blockt."""

    loaded = pyqtSignal(object, object, object)
    failed = pyqtSignal(str)

    def __init__(self, path: str, tools, parent=None):
        super().__init__(parent)
        self._path = path
        self._tools = tools
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        if self._abort:
            return
        try:
            mi = analyze_media(self._path, self._tools)
            if self._abort:
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

    def closeEvent(self, event) -> None:
        loader = getattr(self, "_override_loader", None)
        if loader is not None:
            try:
                if loader.isRunning():
                    loader.abort()
                    loader.quit()
                    loader.wait(1500)
            except RuntimeError:
                pass
            finally:
                self._override_loader = None

        super().closeEvent(event)
