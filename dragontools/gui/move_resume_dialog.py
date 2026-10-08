# -*- coding: utf-8 -*-
from __future__ import annotations

from copy import deepcopy

from PyQt6.QtWidgets import (
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from ..core.move_journal import build_move_resume_plan, format_unfinished_move_summary
from .ui_helpers import install_persistent_window_geometry
from .journal_resume_base import JournalResumeDialogBase


class MoveResumeDialog(JournalResumeDialogBase):
    """Dialog für eine nicht vollständig abgeschlossene Verschiebequeue."""

    def __init__(self, data: dict, parent=None, *, prepared_plan: dict | None = None) -> None:
        super().__init__(parent)
        self._data = data
        self._prepared_plan = deepcopy(prepared_plan)
        self.setWindowTitle("Unvollständiges Verschieben gefunden")
        self.setMinimumWidth(620)
        self._init_ui()
        install_persistent_window_geometry(self, "move_resume_dialog")

    def resume_plan(self) -> dict:
        if self._prepared_plan is not None:
            return deepcopy(self._prepared_plan)
        return build_move_resume_plan(self._data)

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        intro = QLabel(
            "Dragon Tools hat einen nicht vollständig abgeschlossenen Verschiebevorgang gefunden. "
            "Die noch offenen Dateien können wieder in eine Konverter-Warteschlange geladen werden. "
            "Danach bitte 'Nur verschieben' verwenden; es wird nichts automatisch neu konvertiert."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setMinimumHeight(130)
        summary.setPlainText(format_unfinished_move_summary(self._data, plan=self.resume_plan()))
        root.addWidget(summary)

        plan = self.resume_plan()
        preview = QLabel(f"Erneut zu verschieben: {len(plan.get('files') or [])} Datei(en).")
        preview.setWordWrap(True)
        root.addWidget(preview)

        self._add_action_buttons(
            root,
            load_text="Zum erneuten Verschieben laden",
            load_enabled=bool(plan.get("files")),
        )
