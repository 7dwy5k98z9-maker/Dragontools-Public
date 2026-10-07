# -*- coding: utf-8 -*-
from __future__ import annotations

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
        from .external_program_launch import launch_external_program
        from .tab_manager import _find_bundled_exe, _open_external
        from PyQt6.QtWidgets import QFileDialog

        launch_external_program(
            self, exe_name, tools=get_tool_paths(), find_bundled=_find_bundled_exe,
            open_external=_open_external, choose=QFileDialog.getOpenFileName,
        )
