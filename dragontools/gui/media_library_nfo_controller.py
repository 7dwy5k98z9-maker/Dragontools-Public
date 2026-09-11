# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from PyQt6.QtWidgets import QMessageBox, QWidget

from .media_library_nfo_scan_controller import MediaLibraryNfoScanCoordinator


class _NfoView(Protocol):
    nfo_progress: object
    nfo_status_label: object
    nfo_abort_btn: object

    def set_nfo_scan_running(self, running: bool) -> None: ...


class MediaLibraryNfoController:
    """Steuert NFO-Lightscan und Vollprüfung außerhalb des Hauptdialogs."""

    def __init__(
        self,
        *,
        parent: QWidget,
        view: _NfoView,
        presenter: object,
        get_db_path: Callable[[], str],
        save_state: Callable[[], None],
        refresh_stats: Callable[[], None],
        is_storage_scan_running: Callable[[], bool],
    ) -> None:
        self._parent = parent
        self._view = view
        self._presenter = presenter
        self._get_db_path = get_db_path
        self._save_state = save_state
        self._refresh_stats = refresh_stats
        self._is_storage_scan_running = is_storage_scan_running
        self._scan = MediaLibraryNfoScanCoordinator(
            parent=parent,
            on_progress=self._on_progress,
            on_log=self._on_log,
            on_result=self._on_result,
            on_failed=self._on_failed,
            on_running_changed=self._view.set_nfo_scan_running,
        )

    @property
    def is_running(self) -> bool:
        return self._scan.is_running

    def scan_light(self) -> None:
        self._start(full_audit=False)

    def scan_full(self) -> None:
        answer = QMessageBox.question(
            self._parent,
            "NFO vollständig prüfen",
            "Alle aktiven Film-/Serien-/Episoden-NFOs werden direkt über die bereits bekannten "
            "Mediathek-Pfade gelesen und mit der DragonTools-Datenbank verglichen. "
            "Videodateien werden nicht analysiert. Fortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start(full_audit=True)

    def abort(self) -> None:
        if self._scan.abort():
            self._view.nfo_abort_btn.setEnabled(False)
            self._view.nfo_status_label.setText("NFO-Scan wird abgebrochen ...")

    def _start(self, *, full_audit: bool) -> None:
        if self._scan.is_running or self._is_storage_scan_running():
            QMessageBox.information(self._parent, "NFO-Scan", "Es läuft bereits ein Mediathek-Scan.")
            return
        self._save_state()
        self._view.nfo_progress.setValue(0)
        self._view.nfo_status_label.setText(
            "NFO-Bestand wird geprüft ..."
            if full_audit
            else "Fehlende/geänderte NFO-Einträge werden gezielt geprüft ..."
        )
        self._scan.start(db_path=self._get_db_path(), full_audit=full_audit)

    def _on_progress(self, current: int, total: int, path: str) -> None:
        pct = int((current / max(1, total)) * 100)
        self._view.nfo_progress.setValue(max(0, min(100, pct)))
        self._view.nfo_status_label.setText(f"NFO {current}/{total}: {Path(path).name}")

    def _on_log(self, message: str) -> None:
        if message:
            self._view.nfo_status_label.setText(message)

    def _on_result(self, result: object) -> None:
        self._refresh_stats()
        self._view.nfo_progress.setValue(0 if getattr(result, "aborted", False) else 100)
        self._view.nfo_status_label.setText(
            "NFO-Scan abgebrochen." if getattr(result, "aborted", False) else "NFO-Prüfung abgeschlossen."
        )
        QMessageBox.information(
            self._parent,
            "NFO-Prüfung",
            self._presenter.format_nfo_scan_result(result),
        )

    def _on_failed(self, message: str) -> None:
        self._view.nfo_status_label.setText("NFO-Prüfung fehlgeschlagen.")
        QMessageBox.critical(self._parent, "NFO-Prüfung fehlgeschlagen", message)
