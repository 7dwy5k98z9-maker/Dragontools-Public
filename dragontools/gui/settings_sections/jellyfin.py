# -*- coding: utf-8 -*-
"""Jellyfin API section of the global settings dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from ...core import settings as cfg
from ...core.jellyfin_api import JellyfinApiError, normalize_server_url
from ...core.secret_settings import read_secret, write_secret
from ..info_button import InfoButton
from ..jellyfin_connection_test import JellyfinConnectionTestThread
from .base import SettingsSection


class JellyfinIntegrationSection(SettingsSection):
    section_keys = ("jellyfin_api",)

    def build(self, layout) -> None:
        d = self.dialog
        grp = QGroupBox("Jellyfin API")
        d._section_widgets["jellyfin_api"] = grp
        grid = QGridLayout(grp)

        desc = QLabel(
            "Optionale direkte Jellyfin-Anbindung nach erfolgreichem Verschieben oder Umbenennen. "
            "API-Fehler beeinflussen den bereits abgeschlossenen Datei-Job nicht. Vollständige Bibliotheksscans "
            "dürfen nur nach dem Move-Workflow ausgelöst werden; der Renamer meldet höchstens gezielt."
        )
        desc.setWordWrap(True)
        grid.addWidget(desc, 0, 0, 1, 3)

        d.jellyfin_api_enabled_cb = QCheckBox("Jellyfin-API-Integration aktivieren")
        grid.addWidget(d.jellyfin_api_enabled_cb, 1, 0, 1, 2)
        grid.addWidget(InfoButton(
            "Ist diese Option aus, führt Dragon Tools keinerlei automatische Jellyfin-API-Aufrufe aus."
        ), 1, 2)

        grid.addWidget(QLabel("Server:"), 2, 0)
        d.jellyfin_server_url_edit = QLineEdit()
        d.jellyfin_server_url_edit.setPlaceholderText("http://192.168.1.10:8096")
        grid.addWidget(d.jellyfin_server_url_edit, 2, 1)
        grid.addWidget(InfoButton(
            "Jellyfin-Basisadresse inklusive Port und optionalem Base-Pfad. Ohne Schema wird http:// ergänzt."
        ), 2, 2)

        grid.addWidget(QLabel("API-Key:"), 3, 0)
        d.jellyfin_api_key_edit = QLineEdit()
        d.jellyfin_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(d.jellyfin_api_key_edit, 3, 1)
        grid.addWidget(InfoButton(
            "Persönlicher Jellyfin-API-Key. Er wird lokal in den Dragon-Tools-Einstellungen gespeichert."
        ), 3, 2)

        d.jellyfin_test_btn = QPushButton("Verbindung testen")
        d.jellyfin_test_btn.clicked.connect(self.test_connection)
        grid.addWidget(d.jellyfin_test_btn, 4, 0)
        d.jellyfin_test_status_lbl = QLabel("")
        d.jellyfin_test_status_lbl.setWordWrap(True)
        grid.addWidget(d.jellyfin_test_status_lbl, 4, 1, 1, 2)

        d.jellyfin_notify_move_cb = QCheckBox("Nach erfolgreichem Verschieben aktualisieren")
        grid.addWidget(d.jellyfin_notify_move_cb, 5, 0, 1, 2)
        grid.addWidget(InfoButton(
            "Meldet nur erfolgreich verschobene Videodateien. Fehlerhafte oder abgebrochene Moves werden nicht gemeldet."
        ), 5, 2)

        d.jellyfin_notify_rename_cb = QCheckBox("Nach erfolgreichem Renamer-Lauf gezielt informieren")
        grid.addWidget(d.jellyfin_notify_rename_cb, 6, 0, 1, 2)
        grid.addWidget(InfoButton(
            "Optional. Meldet den alten Pfad als gelöscht und den neuen Pfad als erstellt. "
            "Der Renamer startet dabei niemals einen vollständigen Bibliotheksscan; Vollscan/Fallback ist nur dem Move-Workflow vorbehalten."
        ), 6, 2)

        grid.addWidget(QLabel("Aktualisierung:"), 7, 0)
        d.jellyfin_refresh_mode_combo = QComboBox()
        d.jellyfin_refresh_mode_combo.addItem("Gezielte Erkennung + Metadatenanalyse (empfohlen)", "targeted")
        d.jellyfin_refresh_mode_combo.addItem("Vollständigen Bibliotheksscan starten", "full")
        d.jellyfin_refresh_mode_combo.currentIndexChanged.connect(self._sync_mode)
        grid.addWidget(d.jellyfin_refresh_mode_combo, 7, 1)
        grid.addWidget(InfoButton(
            "Gezielt meldet Dragon Tools die neue Datei und ihren Zielordner. Jellyfin erkennt das neue Medium "
            "daraufhin über seinen normalen Refresh-Pfad und führt die übliche Medien-/Metadatenanalyse aus. "
            "Vollscan lässt Jellyfin die komplette Mediathek neu prüfen."
        ), 7, 2)

        d.jellyfin_fallback_scan_cb = QCheckBox(
            "Bei fehlgeschlagener Pfadmeldung vollständigen Scan als Fallback starten"
        )
        grid.addWidget(d.jellyfin_fallback_scan_cb, 8, 0, 1, 2)
        grid.addWidget(InfoButton(
            "Standardmäßig aus, damit ein temporärer API-/Pfadfehler nicht automatisch einen großen Library-Scan auslöst."
        ), 8, 2)

        mapping_note = QLabel(
            "Pfadzuordnung: Dragon Tools verwendet die gespeicherten Mediathek-Mappings; die Mediathek-DB "
            "liefert den Jellyfin-Pfad (z. B. /TVSerien, /Anime, /Filme). Vor der Meldung werden die Pfade "
            "gegen die tatsächlich vom Jellyfin-Server gemeldeten Mediathekspfade geprüft. Ein lokaler Windows-/"
            "UNC-Pfad wird nicht mehr stillschweigend als erfolgreiche Jellyfin-Aktualisierung akzeptiert."
        )
        mapping_note.setWordWrap(True)
        grid.addWidget(mapping_note, 9, 0, 1, 3)
        layout.addWidget(grp)

    def load(self) -> None:
        d, s = self.dialog, self.settings
        d.jellyfin_api_enabled_cb.setChecked(s.value(
            cfg.SET_KEY_JELLYFIN_API_ENABLED, cfg.DEFAULT_JELLYFIN_API_ENABLED, type=bool
        ))
        d.jellyfin_server_url_edit.setText(s.value(
            cfg.SET_KEY_JELLYFIN_SERVER_URL, cfg.DEFAULT_JELLYFIN_SERVER_URL, type=str
        ))
        d.jellyfin_api_key_edit.setText(read_secret(
            s, cfg.SET_KEY_JELLYFIN_API_KEY, cfg.DEFAULT_JELLYFIN_API_KEY
        ))
        d.jellyfin_notify_move_cb.setChecked(s.value(
            cfg.SET_KEY_JELLYFIN_NOTIFY_AFTER_MOVE, cfg.DEFAULT_JELLYFIN_NOTIFY_AFTER_MOVE, type=bool
        ))
        d.jellyfin_notify_rename_cb.setChecked(s.value(
            cfg.SET_KEY_JELLYFIN_NOTIFY_AFTER_RENAME, cfg.DEFAULT_JELLYFIN_NOTIFY_AFTER_RENAME, type=bool
        ))
        mode = s.value(cfg.SET_KEY_JELLYFIN_REFRESH_MODE, cfg.DEFAULT_JELLYFIN_REFRESH_MODE, type=str)
        idx = d.jellyfin_refresh_mode_combo.findData(mode)
        d.jellyfin_refresh_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        d.jellyfin_fallback_scan_cb.setChecked(s.value(
            cfg.SET_KEY_JELLYFIN_FALLBACK_FULL_SCAN, cfg.DEFAULT_JELLYFIN_FALLBACK_FULL_SCAN, type=bool
        ))
        self._sync_mode()

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        server_url = d.jellyfin_server_url_edit.text().strip()
        api_key = d.jellyfin_api_key_edit.text().strip()
        was_enabled = s.value(cfg.SET_KEY_JELLYFIN_API_ENABLED, cfg.DEFAULT_JELLYFIN_API_ENABLED, type=bool)
        previous_server_url = s.value(cfg.SET_KEY_JELLYFIN_SERVER_URL, cfg.DEFAULT_JELLYFIN_SERVER_URL, type=str).strip()
        if d.jellyfin_api_enabled_cb.isChecked():
            if not server_url or not api_key:
                QMessageBox.warning(
                    d,
                    "Jellyfin API",
                    "Für die aktive Jellyfin-Integration werden Serveradresse und API-Key benötigt.",
                )
                return False
            try:
                server_url = normalize_server_url(server_url)
            except JellyfinApiError as exc:
                QMessageBox.warning(d, "Jellyfin API", str(exc))
                return False
            previous_normalized = ""
            if previous_server_url:
                try:
                    previous_normalized = normalize_server_url(previous_server_url)
                except JellyfinApiError:
                    previous_normalized = previous_server_url
            if server_url.casefold().startswith("http://") and (
                server_url != previous_normalized or not was_enabled
            ):
                QMessageBox.warning(
                    d,
                    "Jellyfin API – unverschlüsselte Verbindung",
                    "Die gespeicherte Jellyfin-Adresse verwendet HTTP. Der API-Key wird auf dieser "
                    "Verbindung nicht transportverschlüsselt. In einem vertrauenswürdigen internen "
                    "Netz kann das bewusst so konfiguriert sein; für Verbindungen außerhalb des LAN "
                    "sollte HTTPS verwendet werden.",
                )

        s.setValue(cfg.SET_KEY_JELLYFIN_API_ENABLED, d.jellyfin_api_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_JELLYFIN_SERVER_URL, server_url)
        write_secret(s, cfg.SET_KEY_JELLYFIN_API_KEY, api_key)
        s.setValue(cfg.SET_KEY_JELLYFIN_NOTIFY_AFTER_MOVE, d.jellyfin_notify_move_cb.isChecked())
        s.setValue(cfg.SET_KEY_JELLYFIN_NOTIFY_AFTER_RENAME, d.jellyfin_notify_rename_cb.isChecked())
        s.setValue(
            cfg.SET_KEY_JELLYFIN_REFRESH_MODE,
            d.jellyfin_refresh_mode_combo.currentData() or cfg.DEFAULT_JELLYFIN_REFRESH_MODE,
        )
        s.setValue(cfg.SET_KEY_JELLYFIN_FALLBACK_FULL_SCAN, d.jellyfin_fallback_scan_cb.isChecked())
        return True

    def _sync_mode(self) -> None:
        targeted = self.dialog.jellyfin_refresh_mode_combo.currentData() == "targeted"
        self.dialog.jellyfin_fallback_scan_cb.setEnabled(targeted)

    def test_connection(self) -> None:
        d = self.dialog
        thread = getattr(d, "_jellyfin_connection_test_thread", None)
        if thread is not None and thread.isRunning():
            return
        server_url = d.jellyfin_server_url_edit.text().strip()
        api_key = d.jellyfin_api_key_edit.text().strip()
        if not server_url or not api_key:
            d.jellyfin_test_status_lbl.setText("❌ Serveradresse und API-Key eintragen.")
            return
        d.jellyfin_test_btn.setEnabled(False)
        d.jellyfin_test_status_lbl.setText("🔄 Verbindung wird geprüft …")
        thread = JellyfinConnectionTestThread(server_url, api_key)
        d._jellyfin_connection_test_thread = thread
        thread.completed.connect(self._connection_test_finished)
        thread.finished.connect(self._connection_test_stopped)
        thread.start()

    def _connection_test_finished(self, ok: bool, message: str) -> None:
        from PyQt6 import sip
        if sip.isdeleted(self.dialog):
            return
        prefix = "✅" if ok else "❌"
        self.dialog.jellyfin_test_status_lbl.setText(f"{prefix} {message}")

    def _connection_test_stopped(self) -> None:
        from PyQt6 import sip
        if not sip.isdeleted(self.dialog):
            self.dialog.jellyfin_test_btn.setEnabled(True)
