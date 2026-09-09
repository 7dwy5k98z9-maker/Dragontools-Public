# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QWidget
from .convert_widget_layout_components import CollapsibleGroupBox, FileListBannerOverlay, ConvertWidgetUI
from .convert_widget_layout_options import ConvertWidgetLayoutOptionsMixin
from .convert_widget_layout_runtime import ConvertWidgetLayoutRuntimeMixin

class ConvertWidgetLayoutBuilder(ConvertWidgetLayoutOptionsMixin, ConvertWidgetLayoutRuntimeMixin):
    def __init__(
        self,
        widget: QWidget,
        default_codec: str,
        settings: QSettings,
        enc_settings,
    ) -> None:
        self.w = widget
        self.default_codec = default_codec
        self.settings = settings
        self.enc_settings = enc_settings

    def build(self) -> ConvertWidgetUI:
        """
        Baut die gesamte UI auf und gibt das fertige UI-Bundle zurück.
        Setzt alle Widgets als Attribute auf self.w.
        """
        root = self._build_scroll_root()
        self._build_encoder_scaling_section(root)
        self._build_encoder_options_section(root)
        self._build_options_section(root)
        self._build_profile_section(root)
        self._build_file_list_section(root)
        self._build_controls_section(root)
        self._build_progress_section(root)
        self._build_log_section(root)
        self._style_progress_labels()
        return self._make_ui_bundle()

    def _make_ui_bundle(self) -> ConvertWidgetUI:
        """Erstellt das ConvertWidgetUI-Bundle aus den soeben gesetzten Attributen."""
        w = self.w
        return ConvertWidgetUI(
            file_lbl=w.file_lbl,
            file_focus_combo=w.file_focus_combo,
            file_bar=w.file_bar,
            eta_lbl=w.eta_lbl,
            total_lbl=w.total_lbl,
            progress_bar=w.progress_bar,
            start_btn=w.start_btn,
            dv_remux_btn=w.dv_remux_btn,
            move_only_btn=w.move_only_btn,
            move_finished_btn=w.move_finished_btn,
            pause_btn=w.pause_btn,
            abort_btn=w.abort_btn,
            abort_combo=w.abort_combo,
            curlog_btn=w.curlog_btn,
            file_list=self._file_list,
            over_cb=w.over_cb,
            strip_cb=w.strip_cb,
            move_cb=w.move_cb,
            shut_cb=w.shut_cb,
            crf_spin=w.crf_spin,
            preset_combo=w.preset_combo,
            scale_combo=w.scale_combo,
        )
