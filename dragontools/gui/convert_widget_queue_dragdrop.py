# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt

from .convert_widget_file_queue import _mime_has_file_payload


class ConvertWidgetQueueDragDropMixin:

    def _collect_video_paths_from_urls(self, urls) -> list[str]:
        return self._file_queue.collect_video_paths_from_urls(urls)

    def dragEnterEvent(self, e):
        if _mime_has_file_payload(e.mimeData()):
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
            return
        e.ignore()
        return

    def dragMoveEvent(self, e):
        if _mime_has_file_payload(e.mimeData()):
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
            return
        e.ignore()
        return

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type not in {
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        }:
            return super().eventFilter(obj, event)

        mime = getattr(event, "mimeData", lambda: None)()
        if mime is None or not _mime_has_file_payload(mime):
            return super().eventFilter(obj, event)

        source = event.source()
        internal_sources = {self.file_list, self.file_list.viewport()}
        if source in internal_sources and obj in internal_sources:
            return super().eventFilter(obj, event)

        if event_type == QEvent.Type.DragEnter:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return True

        if event_type == QEvent.Type.DragMove:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return True

        added = self._file_queue.collect_video_paths_from_mime_data(mime)
        if added:
            self.add_dropped_files(added)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        return True

    def dropEvent(self, e):
        e.setDropAction(Qt.DropAction.CopyAction)
        e.accept()
        if not _mime_has_file_payload(e.mimeData()):
            e.ignore()
            return
        added = self._file_queue.collect_video_paths_from_mime_data(e.mimeData())
        if added:
            self.add_dropped_files(added)
