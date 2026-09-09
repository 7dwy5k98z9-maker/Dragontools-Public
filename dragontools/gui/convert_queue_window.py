# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .convert_widget_file_queue import FileListWidget
from .ui_helpers import restore_window_geometry, save_window_geometry


class QueueWindowListWidget(FileListWidget):
    def dragEnterEvent(self, e):
        if e.source() is self:
            super().dragEnterEvent(e)
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.source() is self:
            super().dragMoveEvent(e)
        else:
            e.ignore()

    def dropEvent(self, e):
        if e.source() is self:
            super().dropEvent(e)
        else:
            e.ignore()


class ConvertQueueWindow(QWidget):
    """Standalone queue view with explicit callbacks to the converter facade."""

    def __init__(
        self,
        parent_widget,
        *,
        default_codec: str,
        source_list: FileListWidget,
        is_queue_blocking_move_active,
        active_worker,
        apply_queue_order,
        toggle_pause,
        abort,
        on_closed,
    ):
        super().__init__(parent_widget, Qt.WindowType.Window)
        self.source_list = source_list
        self.is_queue_blocking_move_active = is_queue_blocking_move_active
        self.active_worker = active_worker
        self.apply_queue_order = apply_queue_order
        self.toggle_pause = toggle_pause
        self.abort = abort
        self.on_closed = on_closed
        self._syncing = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_from_owner)

        self.setWindowTitle(f"Warteschlange – {default_codec.upper()}")
        self.resize(700, 520)
        self._geometry_id = f"convert_queue_window/{default_codec}"
        restore_window_geometry(self, self._geometry_id)

        root = QVBoxLayout(self)
        self.file_list = QueueWindowListWidget(self)
        self.file_list.setMinimumHeight(420)
        self.file_list.order_changed.connect(self._on_order_changed)
        root.addWidget(self.file_list)

        buttons = QHBoxLayout()
        self.pause_btn = QPushButton("⏸ Pause")
        self.abort_btn = QPushButton("❌ Abbrechen")
        self.pause_btn.clicked.connect(self._on_pause_clicked)
        self.abort_btn.clicked.connect(self._on_abort_clicked)
        buttons.addWidget(self.pause_btn)
        buttons.addWidget(self.abort_btn)
        root.addLayout(buttons)

        self.refresh_from_owner()

    def schedule_refresh_from_owner(self, delay_ms: int = 200) -> None:
        if not self.isVisible():
            return
        if delay_ms <= 0:
            self._refresh_timer.stop()
            self.refresh_from_owner()
            return
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(delay_ms)

    def refresh_from_owner(self) -> None:
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()

        self._syncing = True
        try:
            self.file_list.set_edit_locked(bool(self.is_queue_blocking_move_active()))
            selected = {
                item.data(Qt.ItemDataRole.UserRole)
                for item in self.file_list.selectedItems()
            }
            rows = self._owner_rows()
            paths = [path for path, _text, _tooltip in rows]

            if self.file_list.get_paths() == paths:
                self._update_existing_rows(rows, selected)
            else:
                self._rebuild_rows(rows, selected)

            self._refresh_controls()
        finally:
            self._syncing = False

    def _owner_rows(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for i in range(self.source_list.count()):
            owner_item = self.source_list.item(i)
            if owner_item is None:
                continue
            path = owner_item.data(Qt.ItemDataRole.UserRole)
            if not path:
                continue
            rows.append((path, owner_item.text(), owner_item.toolTip()))
        return rows

    def _with_quiet_list_updates(self, callback) -> None:
        signals_were_blocked = self.file_list.blockSignals(True)
        updates_were_enabled = self.file_list.updatesEnabled()
        self.file_list.setUpdatesEnabled(False)
        try:
            callback()
        finally:
            self.file_list.setUpdatesEnabled(updates_were_enabled)
            self.file_list.blockSignals(signals_were_blocked)
            self.file_list.viewport().update()

    def _update_existing_rows(
        self,
        rows: list[tuple[str, str, str]],
        selected: set[str],
    ) -> None:
        def update() -> None:
            for idx, (path, text, tooltip) in enumerate(rows):
                item = self.file_list.item(idx)
                if item is None:
                    continue
                if item.text() != text:
                    item.setText(text)
                if item.toolTip() != tooltip:
                    item.setToolTip(tooltip)
                item.setSelected(path in selected)

        self._with_quiet_list_updates(update)

    def _rebuild_rows(
        self,
        rows: list[tuple[str, str, str]],
        selected: set[str],
    ) -> None:
        def rebuild() -> None:
            self.file_list.clear()
            for path, text, tooltip in rows:
                item = QListWidgetItem(text)
                item.setToolTip(tooltip)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.file_list.addItem(item)
                if path in selected:
                    item.setSelected(True)
            self.file_list.update_empty_banner()

        self._with_quiet_list_updates(rebuild)

    def _refresh_controls(self) -> None:
        # Pause nur anbieten wenn der Worker sie wirklich kann.
        # Abort dagegen ist für jeden laufenden Worker verfügbar.
        thread = self.active_worker()
        can_pause = bool(thread) and hasattr(thread, "pause") \
            and hasattr(thread, "resume") and hasattr(thread, "_paused")
        self.pause_btn.setEnabled(can_pause)
        self.abort_btn.setEnabled(bool(thread))
        if can_pause and getattr(thread, "_paused", False):
            self.pause_btn.setText("▶ Fortsetzen")
        else:
            self.pause_btn.setText("⏸ Pause")
        if bool(thread) and getattr(thread, "abort_requested", False) and getattr(thread, "abort_type", None) == "nach_datei":
            self.abort_btn.setText("↩️ Abbruch zurücknehmen")
            self.abort_btn.setToolTip("Vorgemerkten Abbruch nach der aktuellen Datei zurücknehmen")
        else:
            self.abort_btn.setText("❌ Abbrechen")
            self.abort_btn.setToolTip("Aktiven Vorgang abbrechen")

    def _on_order_changed(self) -> None:
        if self._syncing:
            return
        self.apply_queue_order(self.file_list.get_paths())

    def _on_pause_clicked(self) -> None:
        # Defensive: Klick nur verarbeiten, wenn der Worker Pause wirklich kann.
        # setEnabled() wird in refresh_from_owner() entsprechend gesteuert.
        thread = self.active_worker()
        if not (thread and hasattr(thread, "pause")
                and hasattr(thread, "resume") and hasattr(thread, "_paused")):
            return
        self.toggle_pause()
        self.refresh_from_owner()

    def _on_abort_clicked(self) -> None:
        self.abort()
        self.refresh_from_owner()

    def closeEvent(self, event):
        self._refresh_timer.stop()
        save_window_geometry(self, self._geometry_id)
        self.on_closed()
        super().closeEvent(event)
