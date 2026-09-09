# -*- coding: utf-8 -*-
"""Desktop/log/shutdown actions used by the converter widget."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

from ..core.logger import resolve_log_month_dir
from ..core.system_shutdown import schedule_system_shutdown


class ConvertWidgetHostActions:
    def __init__(self, *, parent_widget, state) -> None:
        self.parent_widget = parent_widget
        self.state = state

    def log(self, msg, level: str = "info") -> None:
        lv = (level or "info").lower()
        if lv in ("error", "err"):
            line = f"[ERR] {msg}"
        elif lv in ("warn", "warning"):
            line = f"[WARN] {msg}"
        elif lv == "debug":
            line = f"[DBG] {msg}"
        else:
            line = str(msg)
        edit = self.parent_widget.log_edit
        edit.append(line)
        sb = edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    @staticmethod
    def _open_path(path: str) -> None:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def open_log_dir(self) -> None:
        self._open_path(str(resolve_log_month_dir(self.state.current_log_path)))

    def open_current_log(self) -> None:
        path = self.state.current_log_path
        if not path or not Path(path).exists():
            QMessageBox.information(self.parent_widget, "Log", "Noch kein Log vorhanden.")
            return
        self._open_path(str(path))

    def confirm_shutdown(self) -> None:
        res = QMessageBox.question(
            self.parent_widget,
            "Herunterfahren",
            "Jetzt herunterfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            schedule_system_shutdown(delay_seconds=5, log=self.log)
