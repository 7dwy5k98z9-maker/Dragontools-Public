# -*- coding: utf-8 -*-
"""Start-Workflows für Convert, Move-Only und DV-Remux."""
from __future__ import annotations

import traceback
from typing import Callable

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox

from ..core.disk_space import check_conversion_disk_space, format_disk_space_issues
from ..core.parallel_settings import parallel_jobs_for_encoder
from ..core.settings import APP_NAME, APP_ORG


class ConversionStartCoordinator:
    """Orchestriert ausschließlich den Start neuer Runs.

    Worker-Erzeugung, Worker-Lifecycle und Fortschrittsdarstellung liegen in
    separaten Services und werden hier nur zusammengesetzt.
    """

    def __init__(
        self,
        *,
        state,
        ui,
        log: Callable,
        collect_encoder_options: Callable[[], dict],
        get_target_paths: Callable[[], dict[str, str]],
        refresh_queue: Callable[[], None],
        set_start_enabled: Callable[[bool], None],
        set_queue_edit: Callable[[bool], None],
        preflight,
        worker_factory,
        lifecycle,
        progress_presenter,
        qt_parent,
    ) -> None:
        self._state = state
        self._ui = ui
        self._log = log
        self._collect_encoder_options = collect_encoder_options
        self._get_target_paths = get_target_paths
        self._refresh_queue = refresh_queue
        self._set_start_enabled = set_start_enabled
        self._set_queue_edit = set_queue_edit
        self._preflight = preflight
        self._worker_factory = worker_factory
        self._lifecycle = lifecycle
        self._progress = progress_presenter
        self._qt_parent = qt_parent

    def get_start_files(self) -> list[str]:
        files = self._ui.file_list.get_paths()
        if not files:
            QMessageBox.warning(self._qt_parent, "Keine Dateien", "Bitte zuerst Dateien hinzufügen.")
            return []
        return files

    def start_convert(self) -> None:
        try:
            if self._lifecycle.active_worker():
                self._log("Start während laufender Verarbeitung oder Verschieben gesperrt.", "warn")
                return
            files = self.get_start_files()
            if not files or not self._preflight.run_if_needed(files):
                return

            self._progress.reset(len(files))
            encoder_options = self._collect_encoder_options()
            settings = getattr(self._qt_parent, "settings", None) or QSettings(APP_ORG, APP_NAME)
            parallel_jobs = parallel_jobs_for_encoder(
                settings,
                str(encoder_options.get("encoder", "cpu")),
            )
            if not self.confirm_disk_space(files, parallel_jobs):
                return
            worker = self._worker_factory.create_converter(
                files,
                encoder_options=encoder_options,
                parallel_jobs=parallel_jobs,
            )
            self._state.thread = worker
            self._lifecycle.connect_worker_signals(
                worker,
                total_progress_slot=self._progress.on_total_progress,
            )
            self._ui.pause_btn.setEnabled(True)
            self._lifecycle.start_worker_ui_state(
                worker,
                f"▶ Starte {len(files)} Datei(en) ...",
                mode="convert",
                files=files,
            )
        except Exception:
            self._log("❌ Unbehandelte Ausnahme in start_convert()", "error")
            self._log(traceback.format_exc(), "error")

    def start_move_only(self) -> None:
        try:
            from PyQt6.QtWidgets import QDialog
            from .preflight_dialog import PreFlightDialog

            files = self.get_start_files()
            if not files:
                return

            paths = self._get_target_paths()
            restore_context = dict(getattr(self._state, "restored_move_context", {}) or {})
            restore_target_paths = (
                restore_context.get("target_paths")
                if isinstance(restore_context.get("target_paths"), dict)
                else {}
            )
            use_restored_move_context = bool(restore_context) and all(
                str(path) in self._state.planned_targets for path in files
            )
            preserved_planned_targets = dict(self._state.planned_targets)
            preserved_sidecars = dict(self._state.sidecar_outputs_by_video)

            if use_restored_move_context:
                for key in ("tv", "anime", "film"):
                    value = str((restore_target_paths or {}).get(key) or "")
                    if value:
                        paths[key] = value
                self._log(
                    "🚚 Move-Only: gespeicherte Ziele aus Move-Journal werden verwendet.",
                    "info",
                )
            else:
                dlg = PreFlightDialog(
                    files,
                    tv_path=paths.get("tv") or None,
                    anime_path=paths.get("anime") or None,
                    filme_path=paths.get("film") or None,
                    parent=self._qt_parent,
                )
                dlg.setWindowTitle("Zielordner festlegen – Move-Only")
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                self._state.planned_targets = dlg.get_planned_targets()
                preserved_planned_targets = dict(self._state.planned_targets)
                preserved_sidecars = dict(self._state.sidecar_outputs_by_video)
                self._state.restored_move_context.clear()
                restore_context = {}
                if dlg.should_save_report():
                    self._preflight.save_report(
                        files,
                        self._state.planned_targets,
                        paths,
                        title="Preflight-Bericht - Move-Only",
                    )

            self._progress.reset(len(files))
            self._state.planned_targets.update(preserved_planned_targets)
            self._state.sidecar_outputs_by_video.update(preserved_sidecars)
            self._state.restored_move_context.update(restore_context)
            for path in files:
                self._state.fertig.add(path)

            self._log(f"🚚 Move-Only: Verschiebe {len(files)} Datei(en) …")
            self._set_start_enabled(False)
            self._set_queue_edit(False)
            self._ui.abort_btn.setEnabled(True)
            self._ui.pause_btn.setEnabled(False)
            self._ui.pause_btn.setText("⏸ Pause")
            self._refresh_queue()
            self._preflight.start_move(files, None)
        except Exception:
            self._log("❌ Unbehandelte Ausnahme in start_move_only()", "error")
            self._log(traceback.format_exc(), "error")

    def start_dv_remux(self) -> None:
        try:
            if self._lifecycle.active_worker():
                self._log("Start während laufender Verarbeitung oder Verschieben gesperrt.", "warn")
                return
            files = self.get_start_files()
            if not files:
                return

            self._progress.reset(len(files))
            thread = self._worker_factory.create_dv_remux(files)
            self._state.thread = thread
            self._lifecycle.connect_worker_signals(
                thread,
                total_progress_slot=self._ui.progress_bar.setValue,
            )
            self._ui.pause_btn.setEnabled(False)
            self._ui.pause_btn.setText("⏸ Pause")
            self._lifecycle.start_worker_ui_state(
                thread,
                f"📦 DV-Remux startet für {len(files)} Datei(en) ...",
                mode="dv_remux",
                files=files,
            )
        except Exception:
            self._log("❌ Unbehandelte Ausnahme in start_dv_remux()", "error")
            self._log(traceback.format_exc(), "error")

    def confirm_disk_space(self, files: list[str], parallel_jobs: int) -> bool:
        try:
            result = check_conversion_disk_space(
                files,
                parallel_jobs=parallel_jobs,
                overwrite_original=bool(self._ui.over_cb.isChecked()),
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._log(f"Speicherplatzprüfung konnte nicht ausgeführt werden: {exc}", "warn")
            return True

        if not result.issues:
            return True

        text = format_disk_space_issues(result)
        for line in text.splitlines():
            self._log(line, "warn")

        if result.has_critical:
            QMessageBox.critical(self._qt_parent, "Zu wenig Speicherplatz", text)
            return False

        answer = QMessageBox.question(
            self._qt_parent,
            "Speicherplatz knapp",
            text + "\n\nTrotzdem starten?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
