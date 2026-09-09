# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from .ui_helpers import install_persistent_window_geometry


class ShortcutDialog(QDialog):
    def __init__(self, entries: list[tuple[str, str, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shortcuts")
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Verfügbare Shortcuts</b>"))

        table = QTableWidget(len(entries), 3, self)
        table.setHorizontalHeaderLabels(["Shortcut", "Aktion", "Bereich"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        for row, (shortcut, action, area) in enumerate(entries):
            table.setItem(row, 0, QTableWidgetItem(shortcut))
            table.setItem(row, 1, QTableWidgetItem(action))
            table.setItem(row, 2, QTableWidgetItem(area))

        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        install_persistent_window_geometry(self, "shortcut_dialog")
