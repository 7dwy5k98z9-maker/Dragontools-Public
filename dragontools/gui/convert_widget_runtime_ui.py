# -*- coding: utf-8 -*-
"""Runtime UI state for the converter widget."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox


class ConvertWidgetRuntimeUI:
    """Own queue-lock and progress-widget state transitions."""

    def __init__(self, *, parent_widget, state, ui, log, refresh_queue) -> None:
        self.parent_widget = parent_widget
        self.state = state
        self.ui = ui
        self.log = log
        self.refresh_queue = refresh_queue

    def is_move_active(self) -> bool:
        return bool(self.state.move_thread and self.state.move_thread.isRunning())

    def is_incremental_move_active(self) -> bool:
        return self.is_move_active() and bool(
            getattr(self.state, "incremental_move_active", False)
        )

    def is_queue_blocking_move_active(self) -> bool:
        return self.is_move_active() and not self.is_incremental_move_active()

    def set_start_controls_enabled(self, enabled: bool) -> None:
        self.ui.start_btn.setEnabled(enabled)
        self.ui.dv_remux_btn.setEnabled(enabled)
        self.ui.move_only_btn.setEnabled(enabled)

    def set_queue_edit_enabled(self, enabled: bool) -> None:
        allow_reorder_when_locked = (
            not enabled
            and self.state.thread is not None
            and not self.is_queue_blocking_move_active()
        )
        self.ui.file_list.set_edit_locked(
            not enabled,
            allow_reorder=allow_reorder_when_locked,
        )
        owner = self.parent_widget
        owner.add_files_btn.setEnabled(enabled)
        owner.add_folder_btn.setEnabled(enabled)
        owner.remove_btn.setEnabled(enabled)
        owner.clear_btn.setEnabled(enabled)
        self.refresh_queue()

    def guard_queue_edit_allowed(self, action: str) -> bool:
        if not self.is_queue_blocking_move_active():
            return True
        self.log(f"Warteschlange während Verschieben gesperrt: {action}.", "warn")
        QMessageBox.information(
            self.parent_widget,
            "Warteschlange gesperrt",
            "Während des Verschiebens sind Queue-Änderungen gesperrt.",
        )
        return False

    def reset_progress(self) -> None:
        self.state.last_total_pct = 0
        self.ui.file_bar.setValue(0)
        self.ui.file_bar.setFormat("%p%  –  aktuelle Datei")
        self.ui.progress_bar.setValue(0)
        self.ui.file_lbl.setText("")
        self.ui.eta_lbl.setText("")
        self.ui.total_lbl.setText("")
