# -*- coding: utf-8 -*-
"""Wiederverwendbare Qt-Widgets für DragonTools-Datei-Dropflächen."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTableWidget, QWidget

from .drop_path_extractor import _extract_paths_from_mime_data, _mime_has_file_payload


class FileDropTable(QTableWidget):
    """QTableWidget mit einheitlichem lokalem Datei-/Ordner-Drop-Vertrag."""

    paths_dropped = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData() and _mime_has_file_payload(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData() and _mime_has_file_payload(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        paths = _extract_paths_from_mime_data(event.mimeData())
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


__all__ = ["FileDropTable"]
