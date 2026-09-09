from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.replacement_reminders import (
    dismiss_replacement_reminders,
    list_replacement_reminders,
)
from .ui_helpers import install_persistent_window_geometry


class ReplacementReminderDialog(QDialog):
    ACTION_DEFER = "defer"
    ACTION_CONFIRM = "confirm"

    _COLUMNS = ["ID", "Serie", "Folge", "Alte Datei", "Neue Datei", "Grund"]

    def __init__(self, reminders: Iterable[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reminders = [dict(item) for item in reminders]
        self._action = self.ACTION_DEFER
        self.setWindowTitle("Wichtige Ersetzungs-Erinnerung")
        self.resize(980, 460)

        layout = QVBoxLayout(self)
        warning = QLabel(
            "Automatische SxxExx-Ersetzung erkannt: Bitte prüfe diese Dateien, "
            "weil Titel oder Container vom bisherigen Ziel abweichen."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color:#b00020;font-size:16px;font-weight:700;"
            "background:#fff1f2;border:1px solid #f4a3ad;padding:10px;"
        )
        layout.addWidget(warning)

        self._table = QTableWidget(self)
        self._table.setColumnCount(len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._confirm_btn = QPushButton("Bestätigen", self)
        self._defer_btn = QPushButton("Erneut vorlegen", self)
        buttons.addWidget(self._confirm_btn)
        buttons.addWidget(self._defer_btn)
        layout.addLayout(buttons)

        self._confirm_btn.clicked.connect(self._confirm)
        self._defer_btn.clicked.connect(self._defer)
        self._fill_table()
        install_persistent_window_geometry(self, "replacement_reminder_dialog")

    def action(self) -> str:
        return self._action

    def reminder_ids(self) -> list[str]:
        return [str(item.get("id") or "") for item in self._reminders if str(item.get("id") or "")]

    def _fill_table(self) -> None:
        self._table.setRowCount(len(self._reminders))
        for row_index, reminder in enumerate(self._reminders):
            old_names = ", ".join(str(name) for name in reminder.get("old_filenames", []) if str(name))
            old_paths = "\n".join(str(path) for path in reminder.get("old_paths", []) if str(path))
            new_name = str(reminder.get("new_filename") or Path(str(reminder.get("new_path") or "")).name)
            values = [
                reminder.get("id", ""),
                reminder.get("series_name", ""),
                reminder.get("episode_label", ""),
                old_names,
                new_name,
                reminder.get("reason", ""),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if col_index == 0:
                    item.setForeground(QColor("#b00020"))
                if col_index == 3:
                    item.setToolTip(old_paths or str(value))
                elif col_index == 4:
                    item.setToolTip(str(reminder.get("new_path") or value))
                else:
                    item.setToolTip(str(value))
                self._table.setItem(row_index, col_index, item)
        widths = [145, 190, 90, 250, 250, 240]
        for col_index, width in enumerate(widths):
            self._table.setColumnWidth(col_index, width)

    def _confirm(self) -> None:
        self._action = self.ACTION_CONFIRM
        self.accept()

    def _defer(self) -> None:
        self._action = self.ACTION_DEFER
        self.reject()


def show_pending_replacement_reminders(parent: QWidget | None = None) -> int:
    reminders = list_replacement_reminders()
    if not reminders:
        return 0
    dlg = ReplacementReminderDialog(reminders, parent)
    dlg.exec()
    if dlg.action() != ReplacementReminderDialog.ACTION_CONFIRM:
        return 0
    return dismiss_replacement_reminders(dlg.reminder_ids())
