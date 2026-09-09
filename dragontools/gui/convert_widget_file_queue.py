# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QListWidget, QListWidgetItem
from .convert_widget_custom_widgets import BannerLabel, _find_banner_single
from .drop_path_extractor import (
    _debug_mime_data, _extract_paths_from_mime_data, _iter_video_files_in_folder,
    _log_drop_message, _log_drop_rejection, _log_long_path_dragdrop_warning,
    _mime_has_file_payload, _resolve_drop_logger, _warn_non_video_file,
)
from ..core.paths import display_name, display_path, is_video_file, normalize_user_path, path_compare_key, strip_long_path_prefix, to_long_path
from .convert_widget_queue_add import ConvertWidgetQueueAddMixin, VIDEO_FILE_DIALOG_PATTERNS
from .convert_widget_queue_remove import ConvertWidgetQueueRemoveMixin

class FileListWidget(QListWidget):
    """
    Dateiliste mit zwei Drag-&-Drop-Modi:
      1. Dateien/Ordner von außerhalb hineinziehen -> neue Dateien hinzufügen
      2. Items innerhalb der Liste verschieben -> Reihenfolge aendern (Queue-Sortierung)
    """

    remove_requested = pyqtSignal(list)
    order_changed = pyqtSignal()
    files_dropped = pyqtSignal(list)

    def __init__(self, p=None):
        super().__init__(p)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setDragEnabled(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._dragging_internal = False
        self._edit_locked = False
        self._allow_reorder_when_locked = False
        self._path_items: dict[str, QListWidgetItem] = {}

        # Leerer Zustand: Banner direkt in der Liste anzeigen.
        # Sobald Dateien geladen sind, wird das Overlay ausgeblendet und die
        # Liste ist wieder normal: weißer Hintergrund, schwarze Schrift.
        self._empty_banner = BannerLabel(self.viewport())
        self._empty_banner.setScaleMode("contain")
        # Wichtig: Das Overlay darf Drag & Drop/Klicks der Liste nicht abfangen.
        self._empty_banner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        banner_img = _find_banner_single()
        if banner_img:
            self._empty_banner.setBannerPixmap(QPixmap(banner_img))
        else:
            self._empty_banner.setText("🐉 Dragon Tools\nDateien oder Ordner hier ablegen")
            self._empty_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_banner.setStyleSheet("""
            background: transparent;
            color: #202020;
            font-size: 16px;
            font-weight: bold;
        """)

        self.setStyleSheet("""
            FileListWidget {
                background: #ffffff;
                color: #000000;
                border: 1px solid #b8b8b8;
                selection-background-color: #2d7dff;
                selection-color: #ffffff;
            }
        """)
        self.update_empty_banner()

    def set_edit_locked(self, locked: bool, *, allow_reorder: bool = False) -> None:
        self._edit_locked = bool(locked)
        self._allow_reorder_when_locked = bool(allow_reorder)
        self.setDragEnabled(not self._edit_locked or self._allow_reorder_when_locked)

    def _reorder_locked(self) -> bool:
        return self._edit_locked and not self._allow_reorder_when_locked

    def add_path(self, path: str) -> bool:
        path = normalize_user_path(path)
        if not path:
            return False
        if not is_video_file(path):
            return False
        key = path_compare_key(path)
        if key in {
            path_compare_key(item.data(Qt.ItemDataRole.UserRole))
            for item in self._path_items.values()
            if item is not None
        }:
            return False

        item = QListWidgetItem(display_name(path))
        item.setToolTip(display_path(path, max_len=220))
        item.setData(Qt.ItemDataRole.UserRole, path)
        self.addItem(item)
        self._path_items[path] = item
        self.update_empty_banner()
        return True

    def dragEnterEvent(self, e):
        log_fn = _resolve_drop_logger(self)
        _debug_mime_data(log_fn, "FileListWidget.dragEnterEvent", e.mimeData())
        if e.source() is self:
            self._dragging_internal = True
            if self._reorder_locked():
                e.ignore()
                return
            e.acceptProposedAction()
            return
        if self._edit_locked:
            e.ignore()
            return
        if _mime_has_file_payload(e.mimeData()):
            self._dragging_internal = False
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
            return
        e.ignore()
        return

    def dragMoveEvent(self, e):
        log_fn = _resolve_drop_logger(self)
        _debug_mime_data(log_fn, "FileListWidget.dragMoveEvent", e.mimeData())
        if e.source() is self:
            if self._reorder_locked():
                e.ignore()
                return
            e.acceptProposedAction()
            return
        if self._edit_locked:
            e.ignore()
            return
        if _mime_has_file_payload(e.mimeData()):
            e.setDropAction(Qt.DropAction.CopyAction)
            e.accept()
            return
        e.ignore()
        return

    def dropEvent(self, e):
        log_fn = _resolve_drop_logger(self)
        _debug_mime_data(log_fn, "FileListWidget.dropEvent", e.mimeData())

        if e.source() is self:
            if self._reorder_locked():
                e.ignore()
                return
            super().dropEvent(e)
            self.order_changed.emit()
            return

        e.setDropAction(Qt.DropAction.CopyAction)
        e.accept()
        if self._edit_locked:
            e.ignore()
            return
        if _mime_has_file_payload(e.mimeData()):
            added_paths: list[str] = []
            dropped_paths = _extract_paths_from_mime_data(e.mimeData(), log_fn=log_fn)

            if not dropped_paths:
                visible = e.mimeData().text().strip() or "<leer>"
                _log_long_path_dragdrop_warning(log_fn, e.mimeData())
                _log_drop_rejection(log_fn, e.mimeData(), visible)

            for p in dropped_paths:
                if os.path.isfile(to_long_path(p)):
                    if not is_video_file(p):
                        _warn_non_video_file(log_fn, p)
                        continue
                    if self.add_path(p):
                        added_paths.append(p)
                elif os.path.isdir(to_long_path(p)):
                    folder_paths, ignored_count = _iter_video_files_in_folder(p)
                    for path in folder_paths:
                        if self.add_path(path):
                            added_paths.append(path)
                    if ignored_count:
                        _log_drop_message(log_fn, "Nicht-Videodateien wurden ignoriert.")
                else:
                    visible = strip_long_path_prefix(p)
                    _log_drop_rejection(log_fn, e.mimeData(), visible)

            if added_paths:
                self.files_dropped.emit(added_paths)
            return
        else:
            e.ignore()

    def get_paths(self) -> list[str]:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def rebuild_path_index(self) -> None:
        self._path_items = {}
        for i in range(self.count()):
            item = self.item(i)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                self._path_items[str(path)] = item

    def item_for_path(self, path: str):
        key = str(path)
        item = self._path_items.get(key)
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == path:
            return item
        self.rebuild_path_index()
        return self._path_items.get(key)

    def remove_path(self, path: str) -> bool:
        cached = self.item_for_path(path)
        if cached is not None:
            row = self.row(cached)
            if row >= 0:
                self.takeItem(row)
                self._path_items.pop(str(path), None)
                self.update_empty_banner()
                return True
        for i in range(self.count()):
            if self.item(i).data(Qt.ItemDataRole.UserRole) == path:
                self.takeItem(i)
                self._path_items.pop(str(path), None)
                self.update_empty_banner()
                return True
        return False

    def clear(self) -> None:
        super().clear()
        self._path_items.clear()
        self.update_empty_banner()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._position_empty_banner()

    def update_empty_banner(self) -> None:
        is_empty = self.count() == 0
        self._empty_banner.setVisible(is_empty)
        if is_empty:
            self._position_empty_banner()
            self._empty_banner.raise_()

    def _position_empty_banner(self) -> None:
        if not hasattr(self, "_empty_banner"):
            return
        viewport_rect = self.viewport().rect()
        aspect = self._empty_banner.sourceAspectRatio() or 2.5
        max_w = max(1, viewport_rect.width())
        max_h = max(1, viewport_rect.height())
        if max_w / max_h > aspect:
            banner_h = max_h
            banner_w = int(round(banner_h * aspect))
        else:
            banner_w = max_w
            banner_h = int(round(banner_w / aspect))
        banner_w = max(1, min(banner_w, viewport_rect.width()))
        banner_h = max(1, min(banner_h, viewport_rect.height()))
        x = max(0, (viewport_rect.width() - banner_w) // 2)
        y = max(0, (viewport_rect.height() - banner_h) // 2)
        self._empty_banner.setGeometry(x, y, banner_w, banner_h)

    def keyPressEvent(self, e):
        super().keyPressEvent(e)
        self.update_empty_banner()

class ConvertWidgetFileQueueHelper(ConvertWidgetQueueAddMixin, ConvertWidgetQueueRemoveMixin):
    def __init__(
        self,
        *,
        parent_widget,
        file_list: FileListWidget,
        state,
        log,
        guard_queue_edit_allowed,
        maybe_preflight_new_files,
        reset_progress_ui,
        update_label=None,
    ) -> None:
        self.parent_widget = parent_widget
        self.file_list = file_list
        self.state = state
        self.log = log
        self.guard_queue_edit_allowed = guard_queue_edit_allowed
        self.maybe_preflight_new_files = maybe_preflight_new_files
        self.reset_progress_ui = reset_progress_ui
        self.update_label = update_label

    def _sync_total_files(self) -> None:
        self.state.total_files = self.file_list.count()

    def _refresh_labels(self, paths: list[str]) -> None:
        updater = self.update_label
        if not callable(updater):
            return
        for path in paths:
            try:
                updater(path)
            except Exception:
                pass
