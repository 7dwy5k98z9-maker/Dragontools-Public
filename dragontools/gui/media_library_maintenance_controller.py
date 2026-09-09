# -*- coding: utf-8 -*-
"""GUI-Controller für Mediathek-Wartung, Import und Export."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox


class MediaLibraryMaintenanceController:
    def __init__(
        self,
        *,
        parent,
        view,
        service,
        presenter,
        settings,
        get_db_path: Callable[[], str],
        get_mappings: Callable[[], list],
        save_state: Callable[[], None],
    ) -> None:
        self._parent = parent
        self._view = view
        self._service = service
        self._presenter = presenter
        self._settings = settings
        self._get_db_path = get_db_path
        self._get_mappings = get_mappings
        self._save_state = save_state

    def create_empty_database(self) -> None:
        try:
            db_path = self._service.create_database(self._get_db_path(), self._get_mappings())
            self._save_state()
            self.refresh_stats()
            QMessageBox.information(self._parent, "Mediathek", f"Neue DragonTools-Datenbank angelegt:\n{db_path}")
        except Exception as exc:
            QMessageBox.critical(self._parent, "Mediathek", f"Datenbank konnte nicht angelegt werden:\n{exc}")

    def import_jellyfin(self, browse_jellyfin_db: Callable[[], None]) -> None:
        jellyfin_db = self._view.jellyfin_path_edit.text().strip()
        if not jellyfin_db:
            browse_jellyfin_db()
            jellyfin_db = self._view.jellyfin_path_edit.text().strip()
        if not jellyfin_db:
            return
        answer = QMessageBox.question(
            self._parent,
            "Jellyfin importieren",
            "Dragon Tools liest eine Kopie der Jellyfin-Datenbank und ersetzt danach die eigene Mediathek-DB. Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self._service.import_jellyfin(
                jellyfin_db,
                self._get_db_path(),
                self._get_mappings(),
                analyze_existing_files=self._view.analyze_import_cb.isChecked(),
                tools=self._service.tool_paths(self._settings),
            )
            self._save_state()
            self.refresh_stats()
        except Exception as exc:
            QMessageBox.critical(self._parent, "Import fehlgeschlagen", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self._parent, "Mediathek", self._presenter.format_import_result(result))

    def export_database(self) -> None:
        folder = QFileDialog.getExistingDirectory(self._parent, "Exportordner wählen", str(Path.home()))
        if not folder:
            return
        try:
            target = self._service.export_database(self._get_db_path(), folder)
            QMessageBox.information(self._parent, "Export", f"Export erstellt:\n{target}")
        except Exception as exc:
            QMessageBox.critical(self._parent, "Export fehlgeschlagen", str(exc))

    def export_database_csv(self) -> None:
        folder = QFileDialog.getExistingDirectory(self._parent, "CSV-Exportordner wählen", str(Path.home()))
        if not folder:
            return
        try:
            targets = self._service.export_database_csv(self._get_db_path(), folder)
            QMessageBox.information(
                self._parent,
                "CSV-Export",
                "CSV-Export erstellt. Die Medienübersicht enthält die zusammengeführten Technikdaten:\n"
                + "\n".join(str(path) for path in targets),
            )
        except Exception as exc:
            QMessageBox.critical(self._parent, "CSV-Export fehlgeschlagen", str(exc))

    def normalize_stream_types(self) -> None:
        answer = QMessageBox.question(
            self._parent,
            "Streamtypen normalisieren",
            "Dragon Tools normalisiert ältere Streamtypen in der eigenen Mediathek-DB "
            "auf Video, Audio, Subtitle, Image und Data. Vorher wird eine Sicherung erstellt. Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            changed = self._service.normalize_stream_types(self._get_db_path())
            self.refresh_stats()
            QMessageBox.information(
                self._parent,
                "Streamtypen normalisiert",
                f"{changed} Stream-Eintrag(e) wurden auf das DragonTools-Schema normalisiert.",
            )
        except Exception as exc:
            QMessageBox.critical(self._parent, "Normalisierung fehlgeschlagen", str(exc))

    def cleanup_inactive_items(self) -> None:
        answer = QMessageBox.question(
            self._parent,
            "Inaktive Einträge bereinigen",
            "Dragon Tools löscht ausschließlich inaktive Mediathek-Einträge (active=0) "
            "inklusive ihrer Streamdaten. Vorher wird eine Sicherung der eigenen DB erstellt.\n\nFortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            count = self._service.cleanup_inactive_items(self._get_db_path())
            self.refresh_stats()
            QMessageBox.information(
                self._parent,
                "Bereinigung abgeschlossen",
                f"{count} inaktive Mediathek-Eintrag(e) wurden dauerhaft entfernt.",
            )
        except Exception as exc:
            QMessageBox.critical(self._parent, "Bereinigung fehlgeschlagen", str(exc))

    def refresh_stats(self) -> None:
        try:
            self._view.stats_label.setText(self._presenter.format_stats(self._service.stats(self._get_db_path())))
        except Exception as exc:
            self._view.stats_label.setText(f"Status konnte nicht gelesen werden:\n{exc}")
