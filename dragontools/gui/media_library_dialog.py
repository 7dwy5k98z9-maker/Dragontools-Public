# -*- coding: utf-8 -*-
"""Schlanke Orchestrierungs-Fassade für die DragonTools-Mediathek-GUI."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox, QTableWidget, QWidget

from ..core.media_library_types import PathMapping
from ..core.settings import APP_NAME, APP_ORG, APP_VERSION
from .media_library_dialog_presenter import MediaLibraryDialogPresenter
from .media_library_dialog_service import MediaLibraryDialogService, MediaLibraryDialogState
from .media_library_dialog_view import (
    SEARCH_ITEM_TYPES,
    SEARCH_MODES,
    SEARCH_OPTIONS,
    SEARCH_SCOPES,
    MediaLibraryDialogView,
)
from .media_library_maintenance_controller import MediaLibraryMaintenanceController
from .media_library_mapping_controller import MediaLibraryMappingController
from .media_library_scan_controller import MediaLibraryScanCoordinator
from .media_library_nfo_controller import MediaLibraryNfoController
from .media_library_search_controller import MediaLibrarySearchController
from .ui_helpers import install_persistent_window_geometry, save_window_geometry

__all__ = [
    "MediaLibraryDialog",
    "SEARCH_MODES",
    "SEARCH_SCOPES",
    "SEARCH_ITEM_TYPES",
    "SEARCH_OPTIONS",
]


class MediaLibraryDialog(QDialog):
    """Orchestriert spezialisierte Mediathek-GUI-Komponenten.

    Businesslogik, Tabellenaufbereitung und QThread-Lifecycle liegen bewusst
    außerhalb der Dialogklasse. Der Dialog greift auf Widgets ausschließlich
    über seine View zu und exponiert keine gespiegelte Legacy-Widgetoberfläche.
    """

    TAB_KEYS = {"status": 0, "import": 0, "mapping": 1, "search": 2, "sql": 3}

    def __init__(self, parent: QWidget | None = None, initial_tab: str = "status") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Mediathek-Datenbank - Dragon Tools V{APP_VERSION}")
        self.setMinimumSize(920, 640)
        self.settings = QSettings(APP_ORG, APP_NAME)
        self._service = MediaLibraryDialogService()
        self._presenter = MediaLibraryDialogPresenter()
        self._view = MediaLibraryDialogView(self, self)

        self._init_controllers()

        self._load()
        self._search.refresh_saved_queries()
        self._view.tabs.setCurrentIndex(self.TAB_KEYS.get(initial_tab, 0))
        self._refresh_stats()
        install_persistent_window_geometry(self, "media_library_dialog", self.settings)

    def _init_controllers(self) -> None:
        self._mapping = MediaLibraryMappingController(
            parent=self,
            view=self._view,
            service=self._service,
            settings=self.settings,
            get_db_path=self._db_path,
        )
        self._maintenance = MediaLibraryMaintenanceController(
            parent=self,
            view=self._view,
            service=self._service,
            presenter=self._presenter,
            settings=self.settings,
            get_db_path=self._db_path,
            get_mappings=self._mappings_from_table,
            save_state=self._save_without_popup,
        )
        self._search = MediaLibrarySearchController(
            parent=self,
            view=self._view,
            service=self._service,
            presenter=self._presenter,
            get_db_path=self._db_path,
            refresh_stats=self._refresh_stats,
        )
        self._scan = MediaLibraryScanCoordinator(
            parent=self,
            on_progress=self._on_storage_scan_progress,
            on_log=self._on_storage_scan_log,
            on_result=self._on_storage_scan_result,
            on_failed=self._on_storage_scan_failed,
            on_running_changed=self._set_scan_running,
        )
        self._nfo = MediaLibraryNfoController(
            parent=self,
            view=self._view,
            presenter=self._presenter,
            get_db_path=self._db_path,
            save_state=self._save_without_popup,
            refresh_stats=self._refresh_stats,
            is_storage_scan_running=lambda: self._scan.is_running,
        )

    # ── Settings / Fenster-Lifecycle ────────────────────────────────

    def _load(self) -> None:
        state = self._service.load_state(self.settings)
        self._view.enabled_cb.setChecked(state.enabled)
        self._view.preflight_cb.setChecked(state.preflight_enabled)
        self._view.analyze_import_cb.setChecked(state.analyze_on_import)
        self._view.db_path_edit.setText(state.db_path)
        self._view.jellyfin_path_edit.setText(state.jellyfin_db_path)
        self._mapping.set_rows(list(state.mappings))
        self.update_enabled_state(state.enabled)

    def _current_state(self) -> MediaLibraryDialogState:
        return MediaLibraryDialogState(
            enabled=self._view.enabled_cb.isChecked(),
            preflight_enabled=self._view.preflight_cb.isChecked(),
            analyze_on_import=self._view.analyze_import_cb.isChecked(),
            db_path=self._db_path(),
            jellyfin_db_path=self._view.jellyfin_path_edit.text().strip(),
            mappings=tuple(self._mapping.mappings()),
        )

    def update_enabled_state(self, enabled: bool) -> None:
        self._view.preflight_cb.setEnabled(bool(enabled))

    def _save_without_popup(self) -> None:
        self._service.save_state(self.settings, self._current_state())

    def save(self) -> None:
        self._save_without_popup()
        QMessageBox.information(self, "Gespeichert", "Mediathek-Einstellungen wurden gespeichert.")

    def save_and_close(self) -> None:
        self._save_without_popup()
        self.reject()

    def closeEvent(self, event) -> None:
        if self._scan.is_running or self._nfo.is_running:
            QMessageBox.information(
                self,
                "Mediathek-Scan läuft",
                "Ein Mediathek-Scan läuft noch. Bitte zuerst abbrechen oder vollständig abschließen.",
            )
            event.ignore()
            return
        self._save_without_popup()
        save_window_geometry(self, "media_library_dialog", self.settings)
        super().closeEvent(event)

    # ── Pfade / Mapping ─────────────────────────────────────────────

    def _db_path(self) -> str:
        return self._service.resolve_db_path(self._view.db_path_edit.text())

    def browse_db_path(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "DragonTools-Mediathek wählen",
            self._db_path(),
            "SQLite-Datenbanken (*.sqlite *.sqlite3 *.db);;Alle Dateien (*)",
        )
        if file_name:
            self._view.db_path_edit.setText(file_name)
            self._search.refresh_saved_queries()

    def browse_jellyfin_db(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Jellyfin-Datenbank wählen",
            self._view.jellyfin_path_edit.text().strip() or str(Path.home()),
            "SQLite-Datenbanken (*.db *.sqlite *.sqlite3);;Alle Dateien (*)",
        )
        if file_name:
            self._view.jellyfin_path_edit.setText(file_name)

    def save_mappings(self) -> None:
        self._mapping.save()

    def _set_mapping_rows(self, mappings: list[PathMapping]) -> None:
        self._mapping.set_rows(mappings)

    def add_mapping_row(self, mapping: PathMapping | None = None) -> None:
        self._mapping.add_row(mapping)

    def remove_mapping_rows(self) -> None:
        self._mapping.remove_selected_rows()

    def _mappings_from_table(self) -> list[PathMapping]:
        return self._mapping.mappings()

    def fill_mapping_from_storage_paths(self) -> None:
        self._mapping.fill_from_storage_paths()

    def _storage_scan_roots(self) -> list[PathMapping]:
        return self._service.storage_scan_roots(self.settings)

    def _storage_path_mappings(self) -> list[PathMapping]:
        return self._service.storage_path_mappings(self.settings)

    @staticmethod
    def _table_text(table: QTableWidget, row: int, column: int) -> str:
        return MediaLibraryMappingController.table_text(table, row, column)

    # ── Wartung / Import / Export als Delegates ────────────────────

    def create_empty_database(self) -> None:
        self._maintenance.create_empty_database()

    def import_jellyfin(self) -> None:
        self._maintenance.import_jellyfin(self.browse_jellyfin_db)

    def export_database(self) -> None:
        self._maintenance.export_database()

    def export_database_csv(self) -> None:
        self._maintenance.export_database_csv()

    def normalize_stream_types(self) -> None:
        self._maintenance.normalize_stream_types()

    def cleanup_inactive_items(self) -> None:
        self._maintenance.cleanup_inactive_items()

    def _refresh_stats(self) -> None:
        self._maintenance.refresh_stats()

    # ── Speicherpfad-Scan ───────────────────────────────────────────

    def scan_storage_paths(self) -> None:
        if self._scan.is_running or self._nfo.is_running:
            return
        scan_roots = self._storage_scan_roots()
        if not scan_roots:
            QMessageBox.information(
                self,
                "Speicherpfade scannen",
                "In den Speicherpfaden ist aktuell kein erreichbarer Zielordner hinterlegt.",
            )
            return
        root_lines = "\n".join(f"- {root.label}: {root.local_prefix}" for root in scan_roots)
        answer = QMessageBox.question(
            self,
            "Speicherpfade scannen",
            "Dragon Tools durchsucht die hinterlegten Speicherpfade und baut daraus eine neue "
            "Mediathek-Datenbank. Die vorhandene DragonTools-DB wird erst nach einem vollständig "
            "abgeschlossenen Scan ersetzt.\n\n"
            f"Scan-Ordner:\n{root_lines}\n\nFortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._save_without_popup()
        self._view.scan_progress.setValue(0)
        self._view.scan_status_label.setText("Speicherpfade werden durchsucht ...")
        self._scan.start(
            db_path=self._db_path(),
            scan_roots=scan_roots,
            tools=self._service.tool_paths(self.settings),
        )

    def abort_storage_scan(self) -> None:
        if not self._scan.abort():
            return
        self._view.scan_abort_btn.setEnabled(False)
        self._view.scan_status_label.setText("Scan wird nach der aktuellen Datei abgebrochen ...")

    def _on_storage_scan_progress(self, current: int, total: int, path: str) -> None:
        pct = int((current / max(1, total)) * 100)
        self._view.scan_progress.setValue(max(0, min(100, pct)))
        self._view.scan_status_label.setText(f"Analysiere {current}/{total}: {Path(path).name}")

    def _on_storage_scan_log(self, message: str) -> None:
        if message:
            self._view.scan_status_label.setText(message)

    def _on_storage_scan_result(self, result: object) -> None:
        self._set_scan_running(False)
        self._refresh_stats()
        if getattr(result, "aborted", False):
            self._view.scan_progress.setValue(0)
            self._view.scan_status_label.setText("Scan abgebrochen. Die vorhandene Datenbank wurde nicht ersetzt.")
            QMessageBox.information(
                self,
                "Speicherpfad-Scan",
                "Scan abgebrochen. Die vorhandene DragonTools-Mediathek wurde nicht ersetzt.",
            )
            return
        self._view.scan_progress.setValue(100)
        self._view.scan_status_label.setText("Speicherpfad-Scan abgeschlossen.")
        QMessageBox.information(self, "Speicherpfad-Scan", self._presenter.format_scan_result(result))

    def _on_storage_scan_failed(self, message: str) -> None:
        self._set_scan_running(False)
        self._view.scan_status_label.setText("Speicherpfad-Scan fehlgeschlagen.")
        QMessageBox.critical(self, "Speicherpfad-Scan fehlgeschlagen", message)

    def _on_storage_scan_thread_finished(self) -> None:
        self._set_scan_running(False)

    def _set_scan_running(self, running: bool) -> None:
        self._view.set_scan_running(running)

    # ── NFO-Lightscan / Konsistenzprüfung ─────────────────────────

    def scan_nfo_light(self) -> None:
        self._nfo.scan_light()

    def scan_nfo_full(self) -> None:
        self._nfo.scan_full()

    def abort_nfo_scan(self) -> None:
        self._nfo.abort()

    # ── Suche / SQL als Delegates ──────────────────────────────────

    def _update_search_options(self, _index: int | None = None) -> None:
        self._view.update_search_options(_index)

    def run_search(self) -> None:
        self._search.run_search()

    def export_search_csv(self) -> None:
        self._search.export_search_csv()

    def save_current_search(self) -> None:
        self._search.save_current_search()

    def load_saved_search(self) -> None:
        self._search.load_saved_search()

    def delete_saved_search(self) -> None:
        self._search.delete_saved_search()

    def run_sql(self) -> None:
        self._search.run_sql()

    def save_current_sql(self) -> None:
        self._search.save_current_sql()

    def load_saved_sql(self) -> None:
        self._search.load_saved_sql()

    def delete_saved_sql(self) -> None:
        self._search.delete_saved_sql()

    def show_sql_help(self) -> None:
        self._search.show_sql_help()

    def export_sql_help(self) -> None:
        self._search.export_sql_help()
