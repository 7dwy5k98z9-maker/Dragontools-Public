# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QMessageBox

from .media_info_dialog import MediaInfoDialog
from ..core.models import normalize_override_dict
from ..core.paths import display_name
from ..rules.move_rules import planned_target_dir


class ConvertWidgetQueueContextActionsMixin:

    def _ctx_menu(self, pos) -> None:
        item = self._ui.file_list.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("\U0001F6C8 Medieninfo", lambda: self._show_media_info(path))
        menu.addAction("\U0001F9EA Regel-/Profil-Simulator", lambda: self._show_rule_test(path))
        if self._controller.is_file_active(path):
            menu.addSeparator()
            menu.addAction(
                "⏹ FFmpeg für diese laufende Datei beenden",
                lambda: self._terminate_current_ffmpeg_for_path(path),
            )
        if self._is_queue_blocking_move_active():
            menu.exec(self._ui.file_list.mapToGlobal(pos))
            return
        menu.addSeparator()
        processing_mode = normalize_override_dict(
            self._state.file_overrides.get(path, {})
        ).get("processing_mode")
        strip_action = menu.addAction(
            "🧹 Nur diese Datei Strip-Only AN/AUS",
            lambda: self._toggle_strip_only(path),
        )
        strip_action.setCheckable(True)
        strip_action.setChecked(processing_mode == "strip_only")
        menu.addAction("⚙️ Datei-Einstellungen …", lambda: self._edit_override(path))
        selected_paths = [
            str(selected.data(Qt.ItemDataRole.UserRole))
            for selected in self._ui.file_list.selectedItems()
            if selected.data(Qt.ItemDataRole.UserRole)
        ]
        if path not in selected_paths:
            selected_paths = [path]
        encoder_label = (
            f"🎛️ Encoder / Skalierung für Auswahl ({len(selected_paths)}) …"
            if len(selected_paths) > 1
            else "🎛️ Encoder / Skalierung …"
        )
        menu.addAction(
            encoder_label,
            lambda paths=tuple(selected_paths): self._override_dialog.edit_encoder_override(paths),
        )
        menu.addAction("🏷 Encoder-Profil …", lambda: self._assign_encoder_profile(path))
        menu.addAction("\U0001F3AC IMAX AN/AUS", lambda: self._toggle_imax(path))
        menu.addAction("\U0001F50E Quellbildprüfung ausführen", lambda: self._show_source_visual_check(path))
        menu.addAction("\u26a0\ufe0f Quellbildprüfung übergehen", lambda: self._allow_suspicious_source(path))
        menu.addAction("\u2796 Entfernen", lambda: self._remove_path(path))
        menu.exec(self._ui.file_list.mapToGlobal(pos))

    def _terminate_current_ffmpeg_for_path(self, path: str) -> None:
        if not self._controller.is_file_active(path):
            QMessageBox.information(
                self,
                "FFmpeg beenden",
                "Diese Datei wird aktuell nicht mehr verarbeitet.",
            )
            return
        reply = QMessageBox.question(
            self,
            "Aktuelles Encoding beenden",
            f"FFmpeg für '{Path(path).name}' wirklich beenden?\n\n"
            "Nur diese Datei wird abgebrochen. Die restliche Queue läuft weiter.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._controller.terminate_current_ffmpeg(path):
            self._log(f"⏹ Aktuelles Encoding beendet: {display_name(path)}", "warn")
        else:
            QMessageBox.information(
                self,
                "FFmpeg beenden",
                "Für diese Datei läuft gerade kein FFmpeg-Prozess mehr.",
            )
        self._refresh_queue_window()

    def _show_media_info(self, path: str) -> None:
        dlg = MediaInfoDialog(
            path,
            self,
            file_override=dict(self._state.file_overrides.get(path) or {}),
            planned_target=planned_target_dir(self._state.planned_targets.get(path)),
            subtitle_rules=self._get_subtitle_rules(),
            codec=self.default_codec,
        )
        dlg.exec()

    def _show_rule_test(self, path: str) -> None:
        from PyQt6.QtWidgets import QApplication

        from ..core.batch_preflight import build_batch_preflight_rows
        from .batch_preflight_dialog import BatchPreflightDialog

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = build_batch_preflight_rows(
                [path],
                codec=self.default_codec,
                file_overrides={path: dict(self._state.file_overrides.get(path) or {})},
                planned_targets={path: self._state.planned_targets.get(path)},
                subtitle_rules=self._get_subtitle_rules(),
                overwrite_original=self.over_cb.isChecked(),
                filesystem_checks=True,
            )
        finally:
            QApplication.restoreOverrideCursor()

        dlg = BatchPreflightDialog(
            rows,
            parent=self,
            title=f"Regel-/Profil-Simulator - {Path(path).name}",
            read_only=True,
        )
        dlg.exec()

    def show_batch_rule_test(self) -> None:
        from PyQt6.QtWidgets import QApplication

        from ..core.batch_preflight import build_batch_preflight_rows
        from .batch_preflight_dialog import BatchPreflightDialog

        files = self.file_list.get_paths()
        if not files:
            QMessageBox.information(self, "Regel-/Profil-Simulator", "Die Warteschlange ist leer.")
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = build_batch_preflight_rows(
                files,
                codec=self.default_codec,
                file_overrides=dict(self._state.file_overrides),
                planned_targets=dict(self._state.planned_targets),
                subtitle_rules=self._get_subtitle_rules(),
                overwrite_original=self.over_cb.isChecked(),
                filesystem_checks=True,
            )
        finally:
            QApplication.restoreOverrideCursor()

        dlg = BatchPreflightDialog(
            rows,
            parent=self,
            title=f"Regel-/Profil-Simulator - aktuelle Queue ({len(files)} Datei(en))",
            read_only=True,
        )
        dlg.exec()
