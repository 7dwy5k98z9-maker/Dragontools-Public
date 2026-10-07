# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from copy import deepcopy

from PyQt6.QtWidgets import QMessageBox

from ..core.tool_paths import get_tool_paths
from ..worker.source_visual_check import (
    SourceVisualCheckSettings,
    source_visual_settings_from_qsettings,
)
from ..worker.source_visual_thread import SourceVisualCheckThread
from .dialog_ownership import exec_owned_dialog


class ConvertWidgetSourceVisualActionsMixin:

    def _source_visual_settings_for_manual_check(self) -> SourceVisualCheckSettings:
        settings_cfg = source_visual_settings_from_qsettings(self.settings)
        if settings_cfg.enabled:
            return settings_cfg
        return SourceVisualCheckSettings(
            enabled=True,
            interval_percent=settings_cfg.interval_percent,
            sample_duration_s=settings_cfg.sample_duration_s,
            fps=settings_cfg.fps,
            block_percent=settings_cfg.block_percent,
            min_hits=settings_cfg.min_hits,
        )

    def _show_source_visual_check(self, path: str) -> None:
        existing = getattr(self, "_source_visual_check_thread", None)
        if existing is not None:
            try:
                if existing.isRunning():
                    QMessageBox.information(
                        self,
                        "Quellbildprüfung",
                        "Es läuft bereits eine Quellbildprüfung. Bitte diese zuerst abschließen oder abbrechen.",
                    )
                    return
            except RuntimeError:
                self._source_visual_check_thread = None

        tools = get_tool_paths()
        worker = SourceVisualCheckThread(
            path=path,
            settings=self._source_visual_settings_for_manual_check(),
            ffmpeg_path=getattr(tools, "ffmpeg", ""),
            ffprobe_path=getattr(tools, "ffprobe", ""),
        )
        self._source_visual_check_thread = worker
        # Bound QObject methods are deliberate here: Qt can then queue these
        # callbacks back to the ConvertWidget's GUI thread.  Lambdas/free
        # functions have no QObject thread affinity and could otherwise show a
        # QMessageBox from the worker thread.
        worker.result_ready.connect(self._source_visual_result_ready)
        worker.failed.connect(self._source_visual_failed)
        worker.finished.connect(self._source_visual_finished)
        self._log(f"Quellbildprüfung gestartet: {Path(path).name}", "info")
        worker.start()

    def _source_visual_result_ready(self, result) -> None:
        worker = self.sender()
        if getattr(self, "_source_visual_check_thread", None) is not worker:
            return
        path = str(getattr(worker, "path", "") or "")
        text = "\n".join(result.report_lines(include_ok=True))
        if not result.blocked:
            QMessageBox.information(self, "Quellbildprüfung", text)
            return

        box = QMessageBox(self)
        box.setWindowTitle("Quellbild auffällig")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText("Die Quellbildprüfung stuft diese Datei als auffällig ein.")
        box.setInformativeText(text)
        allow_btn = box.addButton("Trotzdem konvertieren", QMessageBox.ButtonRole.YesRole)
        remove_btn = box.addButton("Aus Queue entfernen", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Schließen", QMessageBox.ButtonRole.NoRole)
        exec_owned_dialog(box)

        clicked = box.clickedButton()
        if clicked is allow_btn:
            self._allow_suspicious_source(path)
        elif clicked is remove_btn:
            self._remove_path(path)

    def _source_visual_failed(self, details: str) -> None:
        worker = self.sender()
        if getattr(self, "_source_visual_check_thread", None) is not worker:
            return
        self._log("Quellbildprüfung fehlgeschlagen:\n" + str(details), "error")
        QMessageBox.warning(
            self,
            "Quellbildprüfung fehlgeschlagen",
            "Die Quellbildprüfung konnte nicht abgeschlossen werden. Details stehen im Log.",
        )

    def _source_visual_finished(self) -> None:
        worker = self.sender()
        if getattr(self, "_source_visual_check_thread", None) is worker:
            self._source_visual_check_thread = None

    def _allow_suspicious_source(self, path: str) -> None:
        if not self._guard_queue_edit_allowed("Quellbildprüfung übergehen"):
            return
        ov = deepcopy(self._state.file_overrides.get(path) or {})
        ov["allow_suspicious_source"] = True
        if self._state.thread and hasattr(self._state.thread, "update_override"):
            ok = self._state.thread.update_override(path, ov)
            if not ok:
                QMessageBox.warning(
                    self,
                    "Freigabe abgelehnt",
                    f"'{Path(path).name}' wird gerade verarbeitet\n"
                    "oder ist bereits abgeschlossen.\n\n"
                    "Die Quellbildfreigabe kann nur für wartende Dateien gesetzt werden.",
                )
                return
        self._state.file_overrides[path] = ov
        if hasattr(self._controller, "persist_file_override"):
            self._controller.persist_file_override(path, ov)
        getattr(self._state, "preflight_rows_by_path", {}).pop(path, None)
        self.update_queue_label(path)
        self._log(f"Quellbildprüfung für Datei übergangen: {Path(path).name}", "warn")
