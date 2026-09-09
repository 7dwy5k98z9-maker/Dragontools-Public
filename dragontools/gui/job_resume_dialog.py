# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from ..core.job_journal import build_resume_plan, format_unfinished_job_summary
from .ui_helpers import install_persistent_window_geometry
from .journal_resume_base import JournalResumeDialogBase


class JobResumeDialog(JournalResumeDialogBase):
    """Dialog für die Wiederherstellung einer nicht sauber beendeten Queue."""

    def __init__(self, data: dict, parent=None) -> None:
        super().__init__(parent)
        self._data = data
        self.setWindowTitle("Unvollständigen Lauf wiederherstellen")
        self.setMinimumWidth(620)
        self._init_ui()
        self._update_preview()
        install_persistent_window_geometry(self, "job_resume_dialog")

    def resume_plan(self) -> dict:
        return build_resume_plan(
            self._data,
            retry_running=self._retry_running_cb.isChecked(),
            retry_failed=self._retry_failed_cb.isChecked(),
        )

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)

        intro = QLabel(
            "Dragon Tools hat einen nicht sauber abgeschlossenen Lauf gefunden. "
            "Du kannst die offenen Dateien wieder in die passende Warteschlange laden. "
            "Der Start bleibt danach manuell."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setMinimumHeight(120)
        summary.setPlainText(format_unfinished_job_summary(self._data))
        root.addWidget(summary)

        self._retry_running_cb = QCheckBox("laufende/abgebrochene Datei erneut einreihen")
        self._retry_running_cb.setChecked(True)
        self._retry_running_cb.toggled.connect(self._update_preview)
        root.addWidget(self._retry_running_cb)

        self._retry_failed_cb = QCheckBox("Dateien mit Fehler/Warnung ebenfalls erneut einreihen")
        self._retry_failed_cb.setChecked(False)
        self._retry_failed_cb.toggled.connect(self._update_preview)
        root.addWidget(self._retry_failed_cb)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        root.addWidget(self._preview)

        self._add_action_buttons(
            root,
            load_text="Restqueue laden",
            load_enabled=True,
        )

    def _update_preview(self) -> None:
        plan = self.resume_plan()
        counts = plan.get("counts", {})
        resume_count = len(plan.get("files") or [])
        self._preview.setText(
            "Wiederaufnahme: "
            f"{resume_count} Datei(en) werden geladen. "
            f"OK: {counts.get('ok', 0)}, "
            f"übersprungen: {counts.get('skipped', 0)}, "
            f"offen: {counts.get('queued', 0)}, "
            f"laufend: {counts.get('running', 0)}, "
            f"Fehler/Warnungen: {counts.get('failed', 0)}."
        )
        self._load_btn.setEnabled(resume_count > 0)
