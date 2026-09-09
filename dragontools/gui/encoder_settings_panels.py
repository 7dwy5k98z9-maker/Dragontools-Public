# -*- coding: utf-8 -*-
from __future__ import annotations


class EncoderSettingsPanelMixin:
    def build_nvenc_panel(self):
            return self._ui.build_nvenc_panel()

    def build_qsv_panel(self):
            return self._ui.build_qsv_panel()

    def build_amf_panel(self):
            return self._ui.build_amf_panel()

    def build_x265_panel(self):
            return self._ui.build_x265_panel()

    def bind_main_widgets(self, **kwargs) -> None:
            self._ui.bind_main_widgets(**kwargs)

    def enc_key(self) -> str:
            idx = self._ui.widgets.encoder_combo.currentIndex()
            return ["cpu", "auto", "nvenc", "qsv", "amf"][idx]

    def refresh_enc_panel(self):
            enc = self.enc_key()
            if enc == "auto":
                enc = self._resolve_best_encoder()
                self._log(f"🤖 GPU-Auto: {enc.upper()} erkannt.")
            show_cpu_panel = enc == "cpu"
            widgets = self._ui.widgets
            widgets.enc_grp.setVisible(True)
            widgets.nvenc_p.setVisible(enc == "nvenc")
            widgets.qsv_p.setVisible(enc == "qsv")
            widgets.amf_p.setVisible(enc == "amf")
            widgets.x265_p.setVisible(show_cpu_panel)
            if show_cpu_panel and hasattr(widgets.enc_grp, "setCollapsed"):
                has_user_state = False
                if hasattr(widgets.enc_grp, "hasPersistedState"):
                    try:
                        has_user_state = bool(widgets.enc_grp.hasPersistedState())
                    except Exception:
                        has_user_state = False
                if not has_user_state:
                    widgets.enc_grp.setCollapsed(False)
            self.save_encoder_settings()

    def detect_encoders(self):
            return None

    def _active_encoder(self) -> str:
            raw = self.enc_key()
            return self._resolve_best_encoder() if raw == "auto" else raw

    def connect_encoder_settings_signals(self) -> None:
            widgets = self._ui.widgets
            for widget in [
                widgets.encoder_combo,
                widgets.scale_combo,
                widgets.preset_combo,
                widgets.nv_preset,
                widgets.nv_bref,
                getattr(widgets, "nv_lookahead_level", None),
                getattr(widgets, "nv_multipass", None),
                widgets.qsv_preset,
                widgets.amf_qual,
                widgets.x265_tune,
                widgets.x265_aqm,
            ]:
                if widget is None:
                    continue
                widget.currentIndexChanged.connect(self.save_encoder_settings)
            for widget in [
                widgets.crf_spin,
                widgets.nv_cq,
                widgets.nv_bf,
                widgets.nv_la,
                widgets.nv_aq,
                widgets.qsv_q,
                widgets.qsv_la_depth,
                widgets.amf_qp,
                widgets.x265_bf,
                widgets.x265_la,
            ]:
                widget.valueChanged.connect(self.save_encoder_settings)
            for widget in [widgets.x265_aqs, widgets.x265_psy, widgets.x265_psyrdoq]:
                widget.valueChanged.connect(self.save_encoder_settings)
            for widget in [
                widgets.strip_cb,
                widgets.over_cb,
                widgets.move_cb,
                widgets.shut_cb,
                widgets.autocrop_cb,
                widgets.imax_detect_cb,
                widgets.preserve_dv_cb,
                widgets.preserve_hdrplus_cb,
                widgets.nv_spatial,
                widgets.nv_temporal,
            ]:
                widget.toggled.connect(self.save_encoder_settings)
            widgets.x265_crf.valueChanged.connect(self.save_encoder_settings)
            widgets.x265_preset.currentIndexChanged.connect(self.save_encoder_settings)
