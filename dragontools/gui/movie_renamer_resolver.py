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
from .movie_renamer_job_queue import RenamerResolveJobQueue
from .movie_renamer_resolve_search import MovieRenamerResolveSearchMixin


class MovieRenameResolveThread(QThread):
    proposal_ready = pyqtSignal(str, int, object)
    failed = pyqtSignal(str)

    def __init__(self, jobs: list[tuple], config: OnlineMetadataConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._jobs = RenamerResolveJobQueue(jobs)
        self._config = config

    def enqueue_priority(self, jobs: list[tuple]) -> int:
        return self._jobs.prepend(jobs)

    def cancel_paths(self, paths: list[str]) -> int:
        return self._jobs.cancel_paths(paths)

    def run(self) -> None:
        try:
            movie_client = None
            series_client = None
            while not self.isInterruptionRequested():
                job = self._jobs.take()
                if job is None:
                    return
                _row, path = job[0], str(job[1])
                force_kind = str(job[2] if len(job) > 2 else "" or "").strip().lower() or None
                query_override = str(job[3] if len(job) > 3 else "" or "").strip() or None
                show_all_candidates = bool(job[4]) if len(job) > 4 else False
                season_override = job[5] if len(job) > 5 else None
                # Alte 7er-Jobs bleiben ohne Episoden-Override lesbar.
                episode_override = job[6] if len(job) > 7 else None
                request_id = int(job[-1]) if len(job) > 6 else 0
                parsed = parse_movie_release_name(path)
                use_series = force_kind == "series" or (force_kind != "movie" and parsed.is_probable_series)
                if use_series:
                    if series_client is None:
                        series_client = client_from_config(self._config, "series")
                elif movie_client is None:
                    movie_client = client_from_config(self._config, "movie")
                proposal = build_rename_proposal(
                    path,
                    movie_client=movie_client,
                    series_client=series_client,
                    series_query_override=query_override if use_series else None,
                    movie_query_override=query_override if not use_series else None,
                    force_kind=force_kind,
                    show_all_candidates=show_all_candidates,
                    series_season_override=season_override,
                    series_episode_override=episode_override,
                )
                self.proposal_ready.emit(path, request_id, proposal)
        except OnlineMetadataError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unerwarteter Fehler bei der Metadaten-Suche: {exc}")


class MovieRenamerResolveCoordinator(MovieRenamerResolveSearchMixin):
    def __init__(self, owner, settings: QSettings, table_controller, view) -> None:
        self.owner = owner
        self.settings = settings
        self.table_controller = table_controller
        self.view = view
        self.thread: MovieRenameResolveThread | None = None
        self.auto_resolve_pending = False
        self.is_automatic = False
        self._request_versions: dict[str, int] = {}

    def resolve_all(self) -> None:
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self.owner, "Metadaten-Suche", "Die Vorschlagssuche läuft bereits.")
            return
        jobs = [
            (row, self.table_controller.row_path(row), "", "", False,
             self.table_controller.row_season_override(row),
             self.table_controller.row_episode_override(row))
            for row in range(self.view.table.rowCount())
            if self.table_controller.row_path(row)
        ]
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
        jobs: list[tuple] = []
        for row in range(self.view.table.rowCount()):
            path = self.table_controller.row_path(row)
            if not path or self.table_controller.row_proposal(row) is not None:
                continue
            if self.table_controller.row_item(row, self.table_controller.columns.STATUS).text() != "bereit":
                continue
            jobs.append((
                row, path, "", "", False,
                self.table_controller.row_season_override(row),
                self.table_controller.row_episode_override(row),
            ))
        self.auto_resolve_pending = False
        if jobs:
            self.start_jobs(jobs, automatic=True)

    def start_jobs(self, jobs: list[tuple], *, automatic: bool, priority: bool = False) -> None:
        if not jobs:
            return
        versioned = self._version_jobs(jobs)
        for job in jobs:
            row = job[0]
            if 0 <= row < self.view.table.rowCount():
                self.table_controller.set_status(row, "🔎 Suche")

        if priority and self.thread is not None and self.thread.isRunning():
            self.thread.enqueue_priority(versioned)
            self.is_automatic = False
            self.view.set_busy(True)
            self.view.status_lbl.setText(
                f"Manuelle Suche priorisiert: {len(versioned)} Datei(en); laufende Suche wird fortgesetzt."
            )
            return

        try:
            config = config_from_settings(self.settings, require_enabled=False)
        except OnlineMetadataAuthError as exc:
            for job in jobs:
                row = job[0]
                if 0 <= row < self.view.table.rowCount():
                    self.table_controller.set_status(row, "⚠️ Metadaten fehlen")
            self.view.status_lbl.setText("Automatische Vorschlagssuche nicht möglich: Metadaten-Provider nicht eingerichtet.")
            if not automatic:
                QMessageBox.warning(
                    self.owner, "Metadaten nicht eingerichtet",
                    f"{exc}\n\nÖffne Online-Metadaten und prüfe die Provider-Zugänge.",
                )
            return

        self.is_automatic = automatic
        self.view.set_busy(True)
        prefix = "Neue Dateien: " if automatic else ""
        self.view.status_lbl.setText(f"{prefix}Metadaten-Vorschläge werden geladen: {len(jobs)} Datei(en).")
        thread = MovieRenameResolveThread(versioned, config, self.owner)
        thread.proposal_ready.connect(self.on_proposal_ready)
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
            self.view.status_lbl.setText("Vorschlagssuche abgeschlossen. Neue Dateien werden jetzt geprüft …")
            QTimer.singleShot(0, self.resolve_new)
        else:
            self.view.status_lbl.setText("Vorschlagssuche abgeschlossen.")

    def shutdown(self, timeout_ms: int = 1500) -> None:
        if self.thread is not None and self.thread.isRunning():
            self.thread.requestInterruption()
            self.thread.wait(timeout_ms)
