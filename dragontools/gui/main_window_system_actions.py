# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from ..core.paths import get_tool_paths


class MainWindowSystemActionsMixin:
    def _diagnostic_tool_props(self) -> dict[str, str]:
        tools = get_tool_paths()
        return {
            "ffmpeg":         tools.ffmpeg,
            "ffprobe":        tools.ffprobe,
            "mkvmerge":       tools.mkvmerge,
            "makemkvcon":     tools.makemkvcon,
            "mkvextract":     tools.mkvextract,
            "rmts":           tools.rmts,
            "handbrake":      tools.handbrake_cli,
            "mediainfo":      tools.mediainfo,
            "dovi_tool":      tools.dovi_tool,
            "hdr10plus_tool": tools.hdr10plus_tool,
            "mp4box":         tools.mp4box,
        }

    def _check_tools(self):
        from ..core.tool_diagnostics import build_tool_diagnostics, format_tool_diagnostics

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = build_tool_diagnostics(self._diagnostic_tool_props())
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self,
            "System prüfen / Werkzeuge (F9)",
            format_tool_diagnostics(rows) or "Keine Tools konfiguriert.",
        )

    def _check_tools_extended(self):
        from ..core.tool_diagnostics import format_extended_system_test, run_extended_system_test

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = run_extended_system_test(self._diagnostic_tool_props())
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self,
            "Erweiterter Systemtest",
            format_extended_system_test(rows) or "Keine Tests ausgeführt.",
        )

    def _check_release_build(self):
        from ..core.release_validation import format_release_checks, validate_release

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            checks = validate_release()
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self,
            "Release-/Build prüfen",
            format_release_checks(checks, plain=False),
        )

    def _launch_external(self, exe_name: str):
        """
        Öffnet ein externes Programm. Sucht in dieser Reihenfolge:
        1. Konfigurierter Ordner aus Einstellungen (TOOL_KEYS)
        2. Direkt gespeicherter Pfad (legacy tools/external/...)
        3. Bundle-Verzeichnis
        4. FileDialog (nur wenn alles andere fehlschlägt)
        """
        from .tab_manager import _find_bundled_exe, _open_external
        from PyQt6.QtWidgets import QFileDialog

        # Mapping: exe_name → TOOL_KEYS-Schlüssel + mögliche Exe-Namen
        tool_map = {
            "HandBrake.exe":          ("handbrake", ["HandBrake.exe", "HandBrakeCLI.exe"]),
            "RenameMyTVSeries.exe":   ("rmts",       ["RenameMyTVSeries.exe", "rmts.exe"]),
            "mkvtoolnix-gui.exe":   ("mkv",       ["mkvtoolnix-gui.exe"]),
        }

        # 1) Konfigurierter Ordner aus Einstellungen (settings_dialog Tool-Pfade)
        if exe_name in tool_map:
            tool_key, exe_names = tool_map[exe_name]
            result = get_tool_paths().find_in_settings(tool_key, *exe_names)
            if result and Path(result).exists():
                _open_external(result)
                return

        # 2) Legacy: direkt gespeicherter Pfad
        stored = self._settings.value(f"tools/external/{exe_name}", "", type=str)
        if stored and Path(stored).exists():
            _open_external(stored); return

        # 3) Bundle-Verzeichnis
        found = _find_bundled_exe(exe_name)
        if found:
            _open_external(found); return

        # 4) Nutzer manuell fragen (nur als letzter Ausweg)
        path, _ = QFileDialog.getOpenFileName(
            self, f"{exe_name} wählen", "",
            f"Programm ({exe_name});;Alle Dateien (*)"
        )
        if path:
            # Für nächstes Mal merken
            self._settings.setValue(f"tools/external/{exe_name}", path)
            _open_external(path)
