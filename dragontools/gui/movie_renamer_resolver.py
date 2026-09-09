# -*- coding: utf-8 -*-
"""Metadata worker and lifecycle coordinator for the renamer GUI."""
from __future__ import annotations

from PyQt6.QtCore import QSettings, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from ..core.movie_renamer import build_rename_proposal, parse_movie_release_name
from ..core.online_metadata import (
    OnlineMetadataAuthError,
    OnlineMetadataConfig,
    OnlineMetadataError,
    client_from_config,
    config_from_settings,
)


class MovieRenameResolveThread(QThread):
    proposal_ready = pyqtSignal(int, object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        jobs: list[tuple],
        config: OnlineMetadataConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._config = config

    def run(self) -> None:
        try:
            movie_client = None
            series_client = None
            for job in self._jobs:
                row, path = job[0], job[1]
                series_query_override = job[2] if len(job) > 2 else None
                if self.isInterruptionRequested():
                    return
                parsed = parse_movie_release_name(path)
                if parsed.is_probable_series:
                    if series_client is None:
                        series_client = client_from_config(self._config, "series")
                elif movie_client is None:
                    movie_client = client_from_config(self._config, "movie")
                proposal = build_rename_proposal(
                    path,
                    movie_client=movie_client,
                    series_client=series_client,
                    series_query_override=series_query_override,
                )
                self.proposal_ready.emit(row, proposal)
        except OnlineMetadataError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            # QThread boundary: convert unexpected provider/runtime errors into a GUI signal.
            self.failed.emit(f"Unerwarteter Fehler bei der Metadaten-Suche: {exc}")


class MovieRenamerResolveCoordinator:
    def __init__(self, owner, settings: QSettings, table_controller, view) -> None:
        self.owner = owner
        self.settings = settings
        self.table_controller = table_controller
        self.view = view
        self.thread: MovieRenameResolveThread | None = None
        self.auto_resolve_pending = False
        self.is_automatic = False

    def resolve_all(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self.owner, "Metadaten-Suche", "Die Vorschlagssuche läuft bereits.")
            return
        jobs = [
            (row, self.table_controller.row_path(row))
            for row in range(self.view.table.rowCount())
        ]
        jobs = [(row, path) for row, path in jobs if path]
        if not jobs:
            QMessageBox.information(self.owner, "Renamer", "Bitte zuerst Video-Dateien hinzufügen.")
            return
        self.start_jobs(jobs, automatic=False)

    def schedule_new(self) -> None:
        self.auto_resolve_pending = True
        QTimer.singleShot(0, self.resolve_new)

    def resolve_new(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.auto_resolve_pending = True
            return

        jobs: list[tuple[int, str]] = []
        for row in range(self.view.table.rowCount()):
            path = self.table_controller.row_path(row)
            if not path:
                continue
            if self.table_controller.row_proposal(row) is not None:
                continue
            if self.table_controller.row_item(row, self.table_controller.columns.STATUS).text() != "bereit":
                continue
            jobs.append((row, path))

        self.auto_resolve_pending = False
        if jobs:
            self.start_jobs(jobs, automatic=True)

    def resolve_series_query(self, rows: list[int], query: str) -> None:
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self.owner, "Metadaten-Suche", "Die Vorschlagssuche läuft bereits.")
            return

        normalized_query = str(query or "").strip()
        if not normalized_query:
            return

        jobs: list[tuple[int, str, str]] = []
        for row in sorted(set(rows)):
            path = self.table_controller.row_path(row)
            if not path:
                continue
            self.table_controller.prepare_manual_series_search(row, normalized_query)
            jobs.append((row, path, normalized_query))
        self.start_jobs(jobs, automatic=False)

    def start_jobs(self, jobs: list[tuple], *, automatic: bool) -> None:
        if not jobs:
            return
        try:
            config = config_from_settings(self.settings, require_enabled=False)
        except OnlineMetadataAuthError as exc:
            for job in jobs:
                row = job[0]
                self.table_controller.set_status(row, "⚠️ Metadaten fehlen")
            self.view.status_lbl.setText(
                "Automatische Vorschlagssuche nicht möglich: Metadaten-Provider nicht eingerichtet."
            )
            if not automatic:
                QMessageBox.warning(
                    self.owner,
                    "Metadaten nicht eingerichtet",
                    f"{exc}\n\nÖffne Online-Metadaten und prüfe die Provider-Zugänge.",
                )
            return

        for job in jobs:
            self.table_controller.set_status(job[0], "🔎 Suche")

        self.is_automatic = automatic
        self.view.set_busy(True)
        prefix = "Neue Dateien: " if automatic else ""
        self.view.status_lbl.setText(
            f"{prefix}Metadaten-Vorschläge werden geladen: {len(jobs)} Datei(en)."
        )

        thread = MovieRenameResolveThread(jobs, config, self.owner)
        thread.proposal_ready.connect(self.table_controller.on_proposal_ready)
        thread.failed.connect(self.on_failed)
        thread.finished.connect(self.on_finished)
        self.thread = thread
        thread.start()

    def on_failed(self, message: str) -> None:
        for row in range(self.view.table.rowCount()):
            if self.table_controller.row_item(row, self.table_controller.columns.STATUS).text() == "🔎 Suche":
                self.table_controller.set_status(row, "❌ Fehler")
        self.view.status_lbl.setText(f"Metadaten-Suche fehlgeschlagen: {message}")
        if not self.is_automatic:
            QMessageBox.warning(self.owner, "Metadaten-Suche fehlgeschlagen", message)

    def on_finished(self) -> None:
        self.view.set_busy(False)
        self.thread = None
        self.is_automatic = False
        if self.auto_resolve_pending:
            self.view.status_lbl.setText(
                "Vorschlagssuche abgeschlossen. Neue Dateien werden jetzt geprüft …"
            )
            QTimer.singleShot(0, self.resolve_new)
        else:
            self.view.status_lbl.setText("Vorschlagssuche abgeschlossen.")

    def shutdown(self, timeout_ms: int = 1500) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.thread.requestInterruption()
            self.thread.wait(timeout_ms)
