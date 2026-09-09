# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from ..core.paths import get_tool_paths
from ..worker.source_visual_check import (
    SourceVisualCheckSettings,
    SourceVisualCheckService,
    source_visual_settings_from_qsettings,
)


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
        tools = get_tool_paths()
        service = SourceVisualCheckService(
            ffmpeg_path=getattr(tools, "ffmpeg", ""),
            ffprobe_path=getattr(tools, "ffprobe", ""),
        )
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = service.check(path, self._source_visual_settings_for_manual_check())
        finally:
            QApplication.restoreOverrideCursor()

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
        box.exec()

        clicked = box.clickedButton()
        if clicked is allow_btn:
            self._allow_suspicious_source(path)
        elif clicked is remove_btn:
            self._remove_path(path)

    def _allow_suspicious_source(self, path: str) -> None:
        if not self._guard_queue_edit_allowed("Quellbildprüfung übergehen"):
            return
        ov = dict(self._state.file_overrides.get(path) or {})
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
        self.update_queue_label(path)
        self._log(f"Quellbildprüfung für Datei übergangen: {Path(path).name}", "warn")
