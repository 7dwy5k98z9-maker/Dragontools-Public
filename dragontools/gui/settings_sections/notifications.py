# -*- coding: utf-8 -*-
"""Desktop notification settings panel."""
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel

from ...core import settings as cfg
from ..info_button import InfoButton


class DesktopNotificationPanel:
    def __init__(self, dialog) -> None:
        self.dialog = dialog
        self.settings = dialog.settings

    def build(self, layout) -> None:
        d = self.dialog
        grp = QGroupBox("Windows-Benachrichtigungen")
        d._section_widgets["notifications"] = grp
        grid = QGridLayout(grp)

        desc = QLabel(
            "Optionale Desktop-Meldungen für lange Konvertierungsläufe. "
            "Die Zustellung ist best effort und beeinflusst niemals den Jobstatus."
        )
        desc.setWordWrap(True)
        grid.addWidget(desc, 0, 0, 1, 3)

        d.notifications_enabled_cb = QCheckBox("Windows-Benachrichtigungen aktivieren")
        grid.addWidget(d.notifications_enabled_cb, 1, 0, 1, 2)
        grid.addWidget(InfoButton("Globaler Hauptschalter. Standardmäßig deaktiviert."), 1, 2)

        d.notifications_queue_cb = QCheckBox("Wenn eine Queue vollständig abgeschlossen ist")
        grid.addWidget(d.notifications_queue_cb, 2, 0, 1, 2)
        grid.addWidget(InfoButton(
            "Wird erst nach dem kompletten Lauf einschließlich optionalem Verschieben ausgelöst. "
            "Ein abgebrochener Lauf gilt nicht als abgeschlossen."
        ), 2, 2)

        d.notifications_errors_cb = QCheckBox("Bei Fehlern")
        grid.addWidget(d.notifications_errors_cb, 3, 0, 1, 2)
        grid.addWidget(InfoButton(
            "Meldet fehlgeschlagene Dateien sofort und Verschiebefehler spätestens beim Laufabschluss."
        ), 3, 2)

        d.notifications_file_cb = QCheckBox("Nach jeder erfolgreich abgeschlossenen Datei")
        grid.addWidget(d.notifications_file_cb, 4, 0, 1, 2)
        grid.addWidget(InfoButton(
            "Optional für lange Einzeljobs. Bei großen Queues kann diese Einstellung viele Meldungen erzeugen."
        ), 4, 2)

        d.notifications_enabled_cb.toggled.connect(self._sync_enabled)
        layout.addWidget(grp)

    def load(self) -> None:
        d, s = self.dialog, self.settings
        d.notifications_enabled_cb.setChecked(s.value(
            cfg.SET_KEY_NOTIFICATIONS_ENABLED, cfg.DEFAULT_NOTIFICATIONS_ENABLED, type=bool
        ))
        d.notifications_queue_cb.setChecked(s.value(
            cfg.SET_KEY_NOTIFICATIONS_QUEUE_FINISHED,
            cfg.DEFAULT_NOTIFICATIONS_QUEUE_FINISHED,
            type=bool,
        ))
        d.notifications_errors_cb.setChecked(s.value(
            cfg.SET_KEY_NOTIFICATIONS_ERRORS, cfg.DEFAULT_NOTIFICATIONS_ERRORS, type=bool
        ))
        d.notifications_file_cb.setChecked(s.value(
            cfg.SET_KEY_NOTIFICATIONS_FILE_FINISHED,
            cfg.DEFAULT_NOTIFICATIONS_FILE_FINISHED,
            type=bool,
        ))
        self._sync_enabled(d.notifications_enabled_cb.isChecked())

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        s.setValue(cfg.SET_KEY_NOTIFICATIONS_ENABLED, d.notifications_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_NOTIFICATIONS_QUEUE_FINISHED, d.notifications_queue_cb.isChecked())
        s.setValue(cfg.SET_KEY_NOTIFICATIONS_ERRORS, d.notifications_errors_cb.isChecked())
        s.setValue(cfg.SET_KEY_NOTIFICATIONS_FILE_FINISHED, d.notifications_file_cb.isChecked())
        return True

    def _sync_enabled(self, enabled: bool) -> None:
        d = self.dialog
        for widget in (
            d.notifications_queue_cb,
            d.notifications_errors_cb,
            d.notifications_file_cb,
        ):
            widget.setEnabled(bool(enabled))
