# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.type_utils import _safe_bool, _safe_float, _safe_int


class EncoderSettingsProfilesMixin:
    def save_profile(self):
            options = self.collect_enc_opts()
            payload = {
                "codec": self._default_codec,
                "crf": self._ui.widgets.crf_spin.value(),
                "preset": self._ui.widgets.preset_combo.currentText(),
                "scale": self._ui.widgets.scale_combo.currentText(),
                "encoder_options": options,
            }
            self._profile_service.save_profile_dialog(payload)

    def apply_profile_to_ui(self, profile: dict) -> None:
            if not isinstance(profile, dict) or not profile:
                return
            if str(profile.get("codec") or self._default_codec).lower() != self._default_codec:
                self._log("Profil passt nicht zum Codec dieses Tabs; bitte den passenden Tab verwenden.", "warn")
                return
            from .encoder_profile_application import apply_profile_values
            was_loading = self._state.loading
            self._state.loading = True
            self._state.profile_options = {}
            try:
                apply_profile_values(self, profile)
            finally:
                self._state.loading = was_loading
            self.save_encoder_settings()

    def apply_assistant_profile(self) -> None:
            profile = self._profile_service.assistant_profile_dialog(self._default_codec)
            if profile:
                self.apply_profile_to_ui(profile)
                self.save_encoder_settings()

    def load_profile(self):
            profile = self._profile_service.load_profile_dialog()
            if profile:
                self.apply_profile_to_ui(profile)

    def reset_to_defaults(self) -> None:
            """Setzt alle Encoder-Unterbereiche auf Werkseinstellungen zurück."""
            widgets = self._ui.widgets
            c = self._default_codec
            crf_default = {"h264": 22, "h265": 22, "av1": 28}.get(c, 22)
            preset_default = "6" if c == "av1" else "medium"

            self._state.loading = True
            self._state.profile_options = {}
            try:
                widgets.encoder_combo.setCurrentIndex(0)
                widgets.scale_combo.setCurrentText("original")
                widgets.crf_spin.setValue(crf_default)
                widgets.preset_combo.setCurrentText(preset_default)
                widgets.strip_cb.setChecked(False)
                widgets.over_cb.setChecked(False)
                widgets.move_cb.setChecked(False)
                widgets.shut_cb.setChecked(False)
                widgets.autocrop_cb.setChecked(True)
                widgets.imax_detect_cb.setChecked(False)
                widgets.preserve_dv_cb.setChecked(True)
                widgets.preserve_hdrplus_cb.setChecked(True)

                widgets.nv_preset.setCurrentText("p6")
                widgets.nv_cq.setValue(23)
                widgets.nv_bf.setValue(4)
                widgets.nv_bref.setCurrentText("middle")
                widgets.nv_la.setValue(32)
                self._apply_encoder_combo_value(getattr(widgets, "nv_lookahead_level", None), "auto")
                self._apply_encoder_combo_value(getattr(widgets, "nv_multipass", None), "auto")
                widgets.nv_aq.setValue(8)
                widgets.nv_spatial.setChecked(True)
                widgets.nv_temporal.setChecked(True)

                widgets.qsv_preset.setCurrentText("medium")
                widgets.qsv_q.setValue(23)
                widgets.qsv_la_depth.setValue(40)

                widgets.amf_qp.setValue(23)
                widgets.amf_qual.setCurrentText("balanced")

                widgets.x265_crf.setValue(crf_default)
                widgets.x265_preset.setCurrentText(preset_default)
                widgets.x265_tune.setCurrentText("none")
                widgets.x265_aqm.setCurrentText("2")
                widgets.x265_aqs.setValue(1.0)
                widgets.x265_psy.setValue(2.0)
                widgets.x265_psyrdoq.setValue(1.0)
                widgets.x265_bf.setValue(8)
                widgets.x265_la.setValue(40)
            finally:
                self._state.loading = False
            self.refresh_enc_panel()
            # Nicht auf valueChanged/currentIndexChanged verlassen: ein Reset kann
            # Werte auf denselben Zustand setzen und dann kein Signal auslösen.
            # Deshalb den finalen Werkzustand immer explizit persistieren.
            self.save_encoder_settings()

    @staticmethod
    def _apply_encoder_combo_value(combo, value) -> None:
            if combo is None or value is None:
                return
            text = str(value)
            idx = -1
            if hasattr(combo, "findData"):
                idx = combo.findData(text)
            if idx >= 0 and hasattr(combo, "setCurrentIndex"):
                combo.setCurrentIndex(idx)
            elif text and hasattr(combo, "findText") and combo.findText(text) >= 0:
                combo.setCurrentText(str(value))

    @staticmethod
    def _apply_int_value(widget, value) -> None:
            number = _safe_int(value)
            if number is not None:
                widget.setValue(number)

    @staticmethod
    def _apply_float_value(widget, value) -> None:
            if value is not None:
                widget.setValue(_safe_float(value))
