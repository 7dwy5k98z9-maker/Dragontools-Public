# -*- coding: utf-8 -*-
"""Converter tab composition root.

``ConvertWidget`` exposes a small public tab API while fachliche responsibilities live in
focused collaborators:

* layout/widgets: :mod:`convert_widget_layout`
* dependency graph/signal wiring: :mod:`convert_widget_composition`
* target paths: :mod:`convert_widget_paths`
* queue/progress runtime state: :mod:`convert_widget_runtime_ui`
* journal restore + batch preflight: :mod:`convert_widget_recovery`
* log/desktop/shutdown actions: :mod:`convert_widget_host_actions`
* conversion orchestration: :mod:`conversion_controller`
* result handling: :mod:`conversion_result_service`
* move/preflight lifecycle: :mod:`move_preflight_controller`
"""
from __future__ import annotations

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QWidget

from ..core.paths import get_tool_paths
from ..core.settings import (
    APP_NAME,
    APP_ORG,
    DEFAULT_OUTPUT_CONTAINER_DV,
    SET_KEY_OUTPUT_CONTAINER_DV,
    settings_text,
)
from .conversion_session_state import ConversionSessionState
from .convert_widget_composition import ConvertWidgetComposition
from .convert_widget_file_queue import FileListWidget
from .convert_widget_host_actions import ConvertWidgetHostActions
from .convert_widget_paths import ConvertWidgetTargetPathService
from .convert_widget_queue_actions import ConvertWidgetQueueActionsMixin


class ConvertWidget(ConvertWidgetQueueActionsMixin, QWidget):
    """Thin Qt facade for the converter tab."""

    def __init__(self, default_codec: str = "h265", parent=None) -> None:
        super().__init__(parent)
        self.default_codec = default_codec
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.tools = get_tool_paths()
        self.setAcceptDrops(True)
        self._state = ConversionSessionState()
        self._path_service = ConvertWidgetTargetPathService(
            default_codec=default_codec,
            settings=self.settings,
        )
        self._host_actions = ConvertWidgetHostActions(
            parent_widget=self,
            state=self._state,
        )
        self._composition = ConvertWidgetComposition(self)
        self._composition.initialize()
        self._refresh_dv_remux_target_ui()

    @property
    def _total_files(self) -> int:
        return self._state.total_files

    @_total_files.setter
    def _total_files(self, value: int) -> None:
        self._state.total_files = value

    @property
    def file_list(self) -> FileListWidget:
        return self._ui.file_list

    # Job-/Move-Wiederaufnahme -------------------------------------------------
    def restore_job_files(
        self,
        paths: list[str],
        *,
        context: str = "job",
        planned_targets: dict | None = None,
        sidecar_outputs_by_video: dict | None = None,
        target_paths: dict | None = None,
        conflict_mode: str | None = None,
        journal_path: str | None = None,
        companion_resume_sources: dict | None = None,
    ) -> dict[str, int]:
        return self._recovery_service.restore_job_files(
            paths,
            context=context,
            planned_targets=planned_targets,
            sidecar_outputs_by_video=sidecar_outputs_by_video,
            target_paths=target_paths,
            conflict_mode=conflict_mode,
            journal_path=journal_path,
            companion_resume_sources=companion_resume_sources,
        )
    def _refresh_enc_panel(self):
        self._enc_settings.refresh_enc_panel()

    def _detect_encoders(self):
        return self._enc_settings.detect_encoders()

    # Target paths -------------------------------------------------------------
    def reload_paths(self) -> None:
        self.tools = self._path_service.reload_tools()
        self._refresh_dv_remux_target_ui()

    def _dv_remux_target_container(self) -> str:
        return settings_text(
            self.settings,
            SET_KEY_OUTPUT_CONTAINER_DV,
            DEFAULT_OUTPUT_CONTAINER_DV,
            allowed=("mp4", "mkv"),
        )

    def _refresh_dv_remux_target_ui(self) -> None:
        # Wird beim Tab-Aufbau und nach dem Speichern der Einstellungen über
        # MainWindow._reload_all_paths() aufgerufen. Der Button zeigt damit
        # immer den tatsächlich für DV-Remux verwendeten Zielcontainer.
        if not hasattr(self, "_ui") or not getattr(self._ui, "dv_remux_btn", None):
            return
        container = self._dv_remux_target_container()
        self._ui.dv_remux_btn.setText(f"📦 DV-Remux → {container.upper()}")
        if container == "mkv":
            mux_hint = "Finaler Mux: mkvmerge / MKVToolNix"
            subtitle_hint = "Untertitel: nach Regelwerk intern im MKV-Container"
        else:
            mux_hint = "Finaler Mux: MP4Box (streamingoptimiertes MP4)"
            subtitle_hint = "Untertitel: MP4-Policy (Sidecars an: extern; aus: Text intern als mov_text, Bitmap extern)"
        self._ui.dv_remux_btn.setToolTip(
            "Dolby-Vision-Dateien ohne Video-Re-Encoding remuxen:\n"
            "• Zielcontainer: folgt Einstellungen > Ausgabecontainer > Dolby Vision\n"
            "• Video: unverändert, Dolby Vision bleibt erhalten\n"
            "• Audio: nach den zentralen Audioregeln\n"
            f"• {subtitle_hint}\n"
            f"• {mux_hint}"
        )

    def save_paths(self) -> None:
        self.reload_paths()

    def _get_target_paths(self) -> dict[str, str]:
        return self._path_service.get_target_paths()

    @property
    def tv_path(self) -> str | None:
        return self._get_target_paths()["tv"] or None

    @property
    def anime_path(self) -> str | None:
        return self._get_target_paths()["anime"] or None

    @property
    def filme_path(self) -> str | None:
        return self._get_target_paths()["film"] or None

    # Runtime UI ---------------------------------------------------------------
    def _is_move_active(self) -> bool:
        return self._runtime_ui.is_move_active()

    def _is_queue_blocking_move_active(self) -> bool:
        return self._runtime_ui.is_queue_blocking_move_active()

    def _set_start_controls_enabled(self, enabled: bool) -> None:
        self._runtime_ui.set_start_controls_enabled(enabled)

    def set_queue_edit_enabled(self, enabled: bool) -> None:
        self._runtime_ui.set_queue_edit_enabled(enabled)

    def _guard_queue_edit_allowed(self, action: str) -> bool:
        return self._runtime_ui.guard_queue_edit_allowed(action)

    def _reset_progress_ui(self) -> None:
        self._runtime_ui.reset_progress()

    # Encoder profile/settings -------------------------------------------------
    def connect_encoder_settings_signals(self) -> None:
        self._enc_settings.connect_encoder_settings_signals()

    def save_encoder_settings(self) -> None:
        self._enc_settings.save_encoder_settings()

    def load_encoder_settings(self) -> None:
        self._enc_settings.load_encoder_settings()
        self.update_hdr_metadata_option_visibility()

    def _save_profile(self):
        self._enc_settings.save_profile()

    def _profile_assistant(self):
        self._enc_settings.apply_assistant_profile()

    def apply_profile(self, profile: dict) -> None:
        self._enc_settings.apply_profile_to_ui(profile)
        self.update_hdr_metadata_option_visibility()

    def reset_encoder_defaults(self) -> None:
        self._enc_settings.reset_to_defaults()
        self.update_hdr_metadata_option_visibility()

    def _load_profile(self):
        self._enc_settings.load_profile()

    def update_hdr_metadata_option_visibility(self) -> None:
        show = self.default_codec in {"h265", "av1"}
        for widget in (
            self.preserve_dv_cb,
            self.preserve_dv_info_btn,
            self.preserve_hdrplus_cb,
            self.preserve_hdrplus_info_btn,
        ):
            widget.setVisible(show)

    @staticmethod
    def _resolve_best_encoder() -> str:
        from ..core.gpu_detection import best_encoder

        return best_encoder()

    # Conversion/move delegates -----------------------------------------------
    def _start(self):
        self._controller.start_convert()

    def _start_dv_remux(self):
        self._controller.start_dv_remux()

    def _start_move_only(self):
        self._controller.start_move_only()

    def _move_finished_now(self):
        self._move_preflight.move_finished_now()

    def _toggle_pause(self):
        self._controller.toggle_pause()

    def _abort(self):
        self._controller.abort()

    def _active_worker(self):
        return self._controller.active_worker()

    def iter_shutdown_workers(self) -> tuple:
        """Öffentliche Lifecycle-Schnittstelle für den MainWindow-Shutdown."""
        return self._controller.workers_for_shutdown()

    def running_job_diagnostics(self) -> str:
        return self._controller.running_job_diagnostics()

    def _get_subtitle_rules(self) -> dict:
        return self._controller.get_subtitle_rules()

    def _build_preflight_report_rows(
        self,
        files: list[str],
        planned_targets: dict,
    ) -> list[dict]:
        return self._recovery_service.build_preflight_report_rows(files, planned_targets)

    def _maybe_preflight_new_files(self, added: list[str]) -> None:
        self._move_preflight.maybe_for_new_files(added)

    def _do_finalize_run(
        self,
        finished_thread,
        move_log=None,
        did_shutdown: bool = False,
        move_ok: int = 0,
        move_errors: int = 0,
    ) -> None:
        self._result_service.finalize_run(
            finished_thread,
            move_log=move_log,
            did_shutdown=did_shutdown,
            move_ok=move_ok,
            move_errors=move_errors,
        )

    # Host actions -------------------------------------------------------------
    def _confirm_shutdown(self) -> None:
        self._host_actions.confirm_shutdown()

    def log_message(self, msg, level: str = "info") -> None:
        self._host_actions.log(msg, level)

    def _log(self, msg, level: str = "info") -> None:
        self.log_message(msg, level)

    def _open_log_dir(self) -> None:
        self._host_actions.open_log_dir()

    def _open_current_log(self) -> None:
        self._host_actions.open_current_log()
