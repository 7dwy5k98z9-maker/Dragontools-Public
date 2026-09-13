# -*- coding: utf-8 -*-
"""Preflight-Dialog als schlanker Orchestrator.

Zielwidgets, View-Aufbau und Hintergrund-Metadatensuche liegen in fokussierten
Modulen. Die bisherigen öffentlichen/private Einstiegspunkte bleiben kompatibel.
"""
from __future__ import annotations

import queue
import threading
from typing import Any

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QDialog, QCheckBox, QMessageBox

from ..core.settings import (
    APP_ORG,
    APP_NAME,
    SET_KEY_PREFLIGHT_SAVE_REPORT,
    SET_KEY_SERIES_DEFAULT_TYPE,
)
from .ui_helpers import install_persistent_window_geometry, save_window_geometry
from .preflight_widgets import (
    SeriesGroupWidget,
    FilmWidget,
    _safe_stem,
    _fmt_path,
    _sep,
    _planned_target_entry,
    _series_root_from_input,
    _series_season_target,
    _base_path_key,
)
from .preflight_view import build_preflight_view
from .preflight_metadata import (
    media_library_preflight_enabled,
    online_metadata_enabled,
    run_metadata_lookup,
    apply_metadata_result,
)


class PreFlightDialog(QDialog):
    """Orchestriert Zielauswahl, Validierung und asynchrone Metadatenhinweise."""

    def __init__(
        self,
        files: list[str],
        tv_path: str | None,
        anime_path: str | None,
        filme_path: str | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Zielordner bestätigen – Pre-Flight")
        self.setMinimumWidth(700)
        self.setMinimumHeight(520)
        self._widgets: list[SeriesGroupWidget | FilmWidget] = []
        self._metadata_queue: queue.Queue | None = None
        self._metadata_timer: QTimer | None = None
        self._metadata_cancelled = False
        self._metadata_started = False
        self._metadata_single_timers: list[QTimer] = []
        self._metadata_targets: dict[tuple[str, str], SeriesGroupWidget | FilmWidget] = {}
        self._save_report_cb: QCheckBox | None = None
        try:
            settings = QSettings(APP_ORG, APP_NAME)
            self._series_default_type = settings.value(
                SET_KEY_SERIES_DEFAULT_TYPE, "Anime", type=str
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            self._series_default_type = "Anime"

        self._build(files, tv_path, anime_path, filme_path)
        install_persistent_window_geometry(self, "preflight_dialog")

    def _build(self, files, tv_path, anime_path, filme_path) -> None:
        build_preflight_view(
            self,
            files,
            tv_path,
            anime_path,
            filme_path,
            series_default_type=self._series_default_type,
        )

    def reject(self) -> None:
        self._metadata_cancelled = True
        super().reject()

    def accept(self) -> None:
        self._metadata_cancelled = True
        super().accept()

    def closeEvent(self, event) -> None:
        self._metadata_cancelled = True
        save_window_geometry(self, "preflight_dialog")
        super().closeEvent(event)

    def _start_online_metadata_lookup(self) -> None:
        if self._metadata_cancelled or self._metadata_started:
            return
        self._metadata_started = True
        online_enabled = self._online_metadata_enabled()
        library_enabled = media_library_preflight_enabled()
        jobs: list[tuple[str, str, Any]] = []
        targets: dict[tuple[str, str], SeriesGroupWidget | FilmWidget] = {}

        for widget in self._widgets:
            job = widget.metadata_lookup_job()
            if job is None:
                continue
            kind, key, _payload = job
            if kind == "movie" and not online_enabled and not library_enabled:
                continue
            jobs.append(job)
            targets[(kind, key)] = widget
            if isinstance(widget, SeriesGroupWidget):
                widget.mark_metadata_lookup_started(online_enabled)
            else:
                widget.mark_metadata_lookup_started()
        if not jobs:
            return

        self._metadata_targets = targets
        self._metadata_queue = queue.Queue()
        self._metadata_cancelled = False
        thread = threading.Thread(
            target=self._run_online_metadata_lookup,
            args=(jobs, self._metadata_queue, online_enabled),
            daemon=True,
        )
        thread.start()

        self._metadata_timer = QTimer(self)
        self._metadata_timer.timeout.connect(self._poll_online_metadata_results)
        self._metadata_timer.start(150)

    def _lookup_widget_metadata(self, widget) -> None:
        """Startet eine unabhängige Metadatensuche für genau ein Preflight-Widget."""
        if self._metadata_cancelled:
            return
        job = widget.metadata_lookup_job()
        if job is None:
            return
        online_enabled = self._online_metadata_enabled()
        library_enabled = media_library_preflight_enabled()
        kind, _key, _payload = job
        if kind == "movie" and not online_enabled and not library_enabled:
            return
        if isinstance(widget, SeriesGroupWidget):
            widget.mark_metadata_lookup_started(online_enabled)
        else:
            widget.mark_metadata_lookup_started()

        local_queue: queue.Queue = queue.Queue()
        thread = threading.Thread(
            target=self._run_online_metadata_lookup,
            args=([job], local_queue, online_enabled),
            daemon=True,
        )
        thread.start()
        timer = QTimer(self)
        self._metadata_single_timers.append(timer)

        def poll() -> None:
            while True:
                try:
                    result_kind, _result_key, suggestion = local_queue.get_nowait()
                except queue.Empty:
                    break
                if result_kind == "done":
                    timer.stop()
                    timer.deleteLater()
                    if timer in self._metadata_single_timers:
                        self._metadata_single_timers.remove(timer)
                    return
                if not self._metadata_cancelled:
                    apply_metadata_result(widget, suggestion)

        timer.timeout.connect(poll)
        timer.start(120)

    def _online_metadata_enabled(self) -> bool:
        return online_metadata_enabled()

    def _run_online_metadata_lookup(
        self,
        jobs,
        result_queue,
        online_enabled: bool = True,
    ) -> None:
        run_metadata_lookup(
            jobs,
            result_queue,
            online_enabled=online_enabled,
            is_cancelled=lambda: bool(getattr(self, "_metadata_cancelled", False)),
        )

    def _poll_online_metadata_results(self) -> None:
        result_queue = self._metadata_queue
        if result_queue is None:
            return
        processed = 0
        while processed < 4:
            try:
                kind, key, suggestion = result_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if kind == "done":
                if self._metadata_timer is not None:
                    self._metadata_timer.stop()
                    self._metadata_timer.deleteLater()
                    self._metadata_timer = None
                return
            widget = self._metadata_targets.get((kind, key))
            if widget is not None and not self._metadata_cancelled:
                apply_metadata_result(widget, suggestion)

    def _accept_with_validation(self) -> None:
        for widget in self._widgets:
            if isinstance(widget, SeriesGroupWidget):
                ok, error = widget.validate()
                if not ok:
                    QMessageBox.warning(self, "Serienordner auswählen", error or "Bitte Zielordner wählen.")
                    return
            if not isinstance(widget, FilmWidget):
                continue
            ok, error = widget.validate()
            if ok:
                continue
            QMessageBox.warning(
                self,
                "Ungueltiger Unterordner",
                error or "Ungueltiger Zielpfad.",
            )
            return
        QSettings(APP_ORG, APP_NAME).setValue(
            SET_KEY_PREFLIGHT_SAVE_REPORT,
            self.should_save_report(),
        )
        self.accept()

    def get_planned_targets(self) -> dict[str, str | dict]:
        result: dict[str, str | dict] = {}
        for widget in self._widgets:
            result.update(widget.get_planned_targets())
        return result

    def should_save_report(self) -> bool:
        return bool(self._save_report_cb and self._save_report_cb.isChecked())


__all__ = [
    "PreFlightDialog",
    "SeriesGroupWidget",
    "FilmWidget",
    "_safe_stem",
    "_fmt_path",
    "_sep",
    "_planned_target_entry",
    "_series_root_from_input",
    "_series_season_target",
    "_base_path_key",
]
