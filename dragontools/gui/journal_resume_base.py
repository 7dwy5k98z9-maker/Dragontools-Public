# -*- coding: utf-8 -*-
"""Gemeinsame Aktions-/Button-Logik für Journal-Recovery-Dialoge."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QVBoxLayout


class JournalResumeDialogBase(QDialog):
    ACTION_LOAD = "load"
    ACTION_KEEP = "keep"
    ACTION_ARCHIVE = "archive"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._action = self.ACTION_KEEP

    def action(self) -> str:
        return self._action

    def _add_action_buttons(
        self,
        root: QVBoxLayout,
        *,
        load_text: str,
        load_enabled: bool = True,
    ) -> None:
        buttons = QDialogButtonBox()
        self._load_btn = buttons.addButton(load_text, QDialogButtonBox.ButtonRole.AcceptRole)
        self._archive_btn = buttons.addButton(
            "Journal archivieren",
            QDialogButtonBox.ButtonRole.DestructiveRole,
        )
        self._keep_btn = buttons.addButton(
            "Später entscheiden",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        self._load_btn.setEnabled(bool(load_enabled))
        buttons.clicked.connect(self._on_button_clicked)
        root.addWidget(buttons)

    def _on_button_clicked(self, button: QPushButton) -> None:
        if button is self._load_btn:
            self._action = self.ACTION_LOAD
            self.accept()
            return
        if button is self._archive_btn:
            self._action = self.ACTION_ARCHIVE
            self.accept()
            return
        self._action = self.ACTION_KEEP
        self.reject()


__all__ = ["JournalResumeDialogBase"]
