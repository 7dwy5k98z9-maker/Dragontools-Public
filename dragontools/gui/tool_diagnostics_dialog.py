# -*- coding: utf-8 -*-
"""Scrollable tool-diagnostics dialog used by F9 and live path checks."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout


def show_tool_diagnostics_dialog(parent, *, title: str, text: str) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.resize(760, 600)
    dialog.setMinimumSize(560, 360)

    layout = QVBoxLayout(dialog)
    viewer = QPlainTextEdit(dialog)
    viewer.setReadOnly(True)
    viewer.setPlainText(text or "Keine Tools konfiguriert.")
    viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    layout.addWidget(viewer, 1)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()


__all__ = ["show_tool_diagnostics_dialog"]
