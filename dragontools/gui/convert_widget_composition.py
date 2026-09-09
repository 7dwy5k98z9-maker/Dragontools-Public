# -*- coding: utf-8 -*-
"""Composition root and signal wiring for :class:`ConvertWidget`."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QTimer

from ..core.profile_manager import ProfileManager
from .conversion_controller import ConversionController
from .conversion_result_service import ConversionResultService
from .convert_widget_file_queue import ConvertWidgetFileQueueHelper
from .convert_widget_layout import ConvertWidgetLayoutBuilder, ConvertWidgetUI
from .convert_widget_override_dialog import ConvertWidgetOverrideDialogHelper
from .convert_widget_recovery import ConvertWidgetRecoveryService
from .convert_widget_runtime_ui import ConvertWidgetRuntimeUI
from .encoder_profile_service import EncoderProfileService
from .encoder_settings_controller import EncoderSettingsController
from .encoder_settings_state import EncoderSettingsState
from .encoder_settings_ui import EncoderSettingsUI
from .move_preflight_controller import MovePreflightController


class ConvertWidgetComposition:
    """Build the converter widget graph; contains no conversion business logic."""

    def __init__(self, owner) -> None:
        self.owner = owner

    def initialize(self) -> None:
        owner = self.owner
        self._build_encoder_support()
        self._build_ui()
        self._build_runtime_services()
        self._build_conversion_services()
        owner._queue_window = None
        self.connect_signals()
        owner.connect_encoder_settings_signals()
        owner.reload_paths()
        owner.load_encoder_settings()
        owner.update_hdr_metadata_option_visibility()
        owner.set_queue_edit_enabled(True)
        owner.installEventFilter(owner)
        owner.file_list.installEventFilter(owner)
        owner.file_list.viewport().installEventFilter(owner)
        QTimer.singleShot(800, owner._detect_encoders)

    def _build_encoder_support(self) -> None:
        owner = self.owner
        profile_path = (
            Path.home()
            / "Documents"
            / "DragonTools"
            / f"{owner.default_codec}_profiles.json"
        )
        owner.profile_manager = ProfileManager(profile_path, reporter=owner._log)
        owner._enc_settings_state = EncoderSettingsState()
        owner._enc_settings_ui = EncoderSettingsUI(default_codec=owner.default_codec)
        owner._enc_profile_service = EncoderProfileService(
            profile_manager=owner.profile_manager,
            parent_widget=owner,
            log=owner._log,
        )
        owner._enc_settings = EncoderSettingsController(
            default_codec=owner.default_codec,
            settings=owner.settings,
            state=owner._enc_settings_state,
            ui=owner._enc_settings_ui,
            profile_service=owner._enc_profile_service,
            log=owner._log,
            resolve_best_encoder=owner._resolve_best_encoder,
        )
        owner._override_dialog = ConvertWidgetOverrideDialogHelper(owner)

    def _build_ui(self) -> None:
        owner = self.owner
        builder = ConvertWidgetLayoutBuilder(
            owner,
            owner.default_codec,
            owner.settings,
            owner._enc_settings,
        )
        owner._ui: ConvertWidgetUI = builder.build()
        owner._file_queue = ConvertWidgetFileQueueHelper(
            parent_widget=owner,
            file_list=owner.file_list,
            state=owner._state,
            log=owner._log,
            guard_queue_edit_allowed=owner._guard_queue_edit_allowed,
            maybe_preflight_new_files=owner._maybe_preflight_new_files,
            reset_progress_ui=owner._reset_progress_ui,
            update_label=owner.update_queue_label,
        )
        owner._enc_settings.bind_main_widgets(
            encoder_combo=owner.encoder_combo,
            scale_combo=owner.scale_combo,
            preset_combo=owner.preset_combo,
            crf_spin=owner.crf_spin,
            strip_cb=owner.strip_cb,
            over_cb=owner.over_cb,
            move_cb=owner.move_cb,
            shut_cb=owner.shut_cb,
            autocrop_cb=owner.autocrop_cb,
            imax_detect_cb=owner.imax_detect_cb,
            preserve_dv_cb=owner.preserve_dv_cb,
            preserve_hdrplus_cb=owner.preserve_hdrplus_cb,
            enc_grp=owner.enc_grp,
            nvenc_p=owner.nvenc_p,
            qsv_p=owner.qsv_p,
            amf_p=owner.amf_p,
            x265_p=owner.x265_p,
        )

    def _build_runtime_services(self) -> None:
        owner = self.owner
        owner._runtime_ui = ConvertWidgetRuntimeUI(
            parent_widget=owner,
            state=owner._state,
            ui=owner._ui,
            log=owner._log,
            refresh_queue=owner._refresh_queue_window,
        )

    def _build_conversion_services(self) -> None:
        owner = self.owner
        owner._recovery_service = ConvertWidgetRecoveryService(
            state=owner._state,
            file_list=owner.file_list,
            log=owner._log,
            active_worker=owner._active_worker,
            refresh_queue=owner._refresh_queue_window,
            update_label=owner.update_queue_label,
            default_codec=owner.default_codec,
            get_subtitle_rules=owner._get_subtitle_rules,
            overwrite_original=lambda: owner.over_cb.isChecked(),
            get_tools=lambda: owner.tools,
        )
        owner._move_preflight = MovePreflightController(
            state=owner._state,
            ui=owner._ui,
            log=owner._log,
            parent_widget=owner,
            get_target_paths=owner._get_target_paths,
            finalize_run=owner._do_finalize_run,
            set_start_enabled=owner._set_start_controls_enabled,
            set_queue_edit=owner.set_queue_edit_enabled,
            refresh_queue=owner._refresh_queue_window,
            remove_queued_files=owner._file_queue.remove_paths,
            preflight_rows_builder=owner._build_preflight_report_rows,
        )
        owner._result_service = ConversionResultService(
            state=owner._state,
            ui=owner._ui,
            log=owner._log,
            start_move=owner._move_preflight.start_move,
            set_start_enabled=owner._set_start_controls_enabled,
            set_queue_edit=owner.set_queue_edit_enabled,
            refresh_queue=owner._refresh_queue_window,
            clear=owner._clear,
            confirm_shutdown=owner._confirm_shutdown,
            parent_widget=owner,
            requeue_files=owner._requeue_paths,
        )
        owner._controller = ConversionController(
            state=owner._state,
            ui=owner._ui,
            default_codec=owner.default_codec,
            log=owner._log,
            collect_encoder_options=owner._enc_settings.collect_enc_opts,
            get_target_paths=owner._get_target_paths,
            refresh_queue=owner._refresh_queue_window,
            set_start_enabled=owner._set_start_controls_enabled,
            set_queue_edit=owner.set_queue_edit_enabled,
            remove_queued_files=owner._file_queue.remove_paths,
            preflight=owner._move_preflight,
            result_service=owner._result_service,
            qt_parent=owner,
        )
        owner._result_service.set_file_progress_handler(owner._controller.on_file_progress)

    def connect_signals(self) -> None:
        owner = self.owner
        owner._ui.start_btn.clicked.connect(owner._start)
        owner._ui.dv_remux_btn.clicked.connect(owner._start_dv_remux)
        owner._ui.move_only_btn.clicked.connect(owner._start_move_only)
        owner._ui.move_finished_btn.clicked.connect(owner._move_finished_now)
        owner._ui.pause_btn.clicked.connect(owner._toggle_pause)
        owner._ui.abort_btn.clicked.connect(owner._abort)

        owner.file_list.customContextMenuRequested.connect(owner._ctx_menu)
        owner.file_list.remove_requested.connect(owner._remove_paths)
        owner.file_list.order_changed.connect(owner._sync_queue_order)
        owner.file_list.files_dropped.connect(owner.add_dropped_files)

        owner.add_files_btn.clicked.connect(owner._add_files)
        owner.add_folder_btn.clicked.connect(owner._add_folder)
        owner.remove_btn.clicked.connect(owner.remove_selected_files)
        owner.clear_btn.clicked.connect(owner._clear)

        owner.assist_prof.clicked.connect(owner._profile_assistant)
        owner.save_prof.clicked.connect(owner._save_profile)
        owner.load_prof.clicked.connect(owner._load_profile)

        owner.logfile_btn.clicked.connect(owner._open_log_dir)
        owner.curlog_btn.clicked.connect(owner._open_current_log)
        owner.encoder_combo.currentIndexChanged.connect(owner._refresh_enc_panel)
