# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from ..core.tool_paths import get_tool_paths
from ..core.settings_storage import SET_KEY_WHISPER_MODEL_DIR, SET_KEY_WHISPER_USE_LOCAL_MODEL
from ..core.settings_media_library import DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL, SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL


class MainWindowSystemActionsMixin:
    def _diagnostic_tool_props(self) -> dict[str, str]:
        tools = get_tool_paths()
        return {
            "ffmpeg":         tools.ffmpeg,
            "ffprobe":        tools.ffprobe,
            "mkvmerge":       tools.mkvmerge,
            "makemkvcon":     tools.makemkvcon,
            "mkvextract":     tools.mkvextract,
            "mkvpropedit":    tools.mkvpropedit,
            "rmts":           tools.rmts,
            "handbrake":      tools.handbrake,
            "mediainfo":      tools.mediainfo,
            "dovi_tool":      tools.dovi_tool,
            "hdr10plus_tool": tools.hdr10plus_tool,
            "hdr10plus_generator": tools.hdr10plus_generator,
            "davinci_resolve": tools.davinci_resolve,
            "comfyui":        tools.comfyui,
            "mp4box":         tools.mp4box,
            "tesseract":      tools.tesseract,
        }

    def _check_tools(self):
        from ..core.tool_diagnostics import build_tool_diagnostics, format_tool_diagnostics

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = build_tool_diagnostics(self._diagnostic_tool_props())
            from ..core.whisper_runtime import build_whisper_diagnostic
            model_dir = self._settings.value(SET_KEY_WHISPER_MODEL_DIR, "", type=str)
            use_local_model = self._settings.value(
                SET_KEY_WHISPER_USE_LOCAL_MODEL,
                bool(str(model_dir).strip()),
                type=bool,
            )
            model_name = self._settings.value(
                SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL,
                DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL,
                type=str,
            )
            rows.append(
                build_whisper_diagnostic(
                    model_dir,
                    use_local_model=use_local_model,
                    model_name=model_name,
                )
            )
        finally:
            QApplication.restoreOverrideCursor()
        from .tool_diagnostics_dialog import show_tool_diagnostics_dialog
        show_tool_diagnostics_dialog(
            self,
            title="System prüfen / Werkzeuge (F9)",
            text=format_tool_diagnostics(rows) or "Keine Tools konfiguriert.",
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
            "HandBrake.exe":        ("handbrake", ["HandBrake.exe"]),
            "Resolve.exe":          ("davinci_resolve", ["Resolve.exe", "resolve"]),
            "RenameMyTVSeries.exe": ("rmts", ["RenameMyTVSeries.exe", "rmts.exe"]),
            "mkvtoolnix-gui.exe":   ("mkv", ["mkvtoolnix-gui.exe"]),
        }

        # 1) Konfigurierter Ordner aus Einstellungen (settings_dialog Tool-Pfade)
        if exe_name in tool_map:
            tool_key, exe_names = tool_map[exe_name]
            result = get_tool_paths().find_in_settings(tool_key, *exe_names)
            if result and Path(result).exists():
                _open_external(result)
                return

        # Resolve is commonly installed outside PATH. Reuse the central
        # ToolPaths fallback so a standard Blackmagic installation opens
        # without forcing the user to configure the directory manually.
        if exe_name == "Resolve.exe":
            resolved = get_tool_paths().davinci_resolve
            if resolved and Path(resolved).is_file():
                _open_external(resolved)
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
