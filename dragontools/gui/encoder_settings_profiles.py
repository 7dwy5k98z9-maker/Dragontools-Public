# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.type_utils import _safe_bool, _safe_float, _safe_int


class EncoderSettingsProfilesMixin:
    def save_profile(self):
            payload = {
                "codec": self._default_codec,
                "crf": self._ui.widgets.crf_spin.value(),
                "preset": self._ui.widgets.preset_combo.currentText(),
                "scale": self._ui.widgets.scale_combo.currentText(),
                "encoder_options": self.collect_enc_opts(),
            }
            self._profile_service.save_profile_dialog(payload)

    def apply_profile_to_ui(self, profile: dict) -> None:
            if not profile:
                return
            widgets = self._ui.widgets
            opts = profile.get("encoder_options") or {}
            enc = opts.get("encoder", "cpu")
            enc_map = {"cpu": 0, "auto": 1, "nvenc": 2, "qsv": 3, "amf": 4}
            if enc in enc_map:
                widgets.encoder_combo.setCurrentIndex(enc_map[enc])
            self.refresh_enc_panel()
            scale = profile.get("scale", "original")
            if widgets.scale_combo.findText(scale) >= 0:
                widgets.scale_combo.setCurrentText(scale)
            crf = profile.get("crf") or opts.get("crf")
            if crf is not None:
                crf_value = _safe_int(crf)
                if crf_value is not None:
                    widgets.crf_spin.setValue(crf_value)
                    widgets.x265_crf.setValue(crf_value)
            preset = profile.get("preset")
            self._apply_encoder_combo_value(widgets.preset_combo, preset)
            self._apply_encoder_combo_value(widgets.x265_preset, preset)
            if enc == "nvenc":
                self._apply_encoder_combo_value(widgets.nv_preset, opts.get("preset"))
                self._apply_int_value(widgets.nv_cq, opts.get("cq"))
                self._apply_int_value(widgets.nv_bf, opts.get("bf"))
                self._apply_encoder_combo_value(widgets.nv_bref, opts.get("bref_mode"))
                self._apply_int_value(widgets.nv_la, opts.get("rc_lookahead"))
                self._apply_encoder_combo_value(getattr(widgets, "nv_lookahead_level", None), opts.get("lookahead_level"))
                self._apply_encoder_combo_value(getattr(widgets, "nv_multipass", None), opts.get("multipass"))
                self._apply_int_value(widgets.nv_aq, opts.get("aq_strength"))
                if "spatial_aq" in opts:
                    widgets.nv_spatial.setChecked(_safe_bool(opts["spatial_aq"], True))
                if "temporal_aq" in opts:
                    widgets.nv_temporal.setChecked(_safe_bool(opts["temporal_aq"], True))
            elif enc == "qsv":
                self._apply_encoder_combo_value(widgets.qsv_preset, opts.get("preset"))
                self._apply_int_value(widgets.qsv_q, opts.get("q"))
                self._apply_int_value(widgets.qsv_la_depth, opts.get("lookahead_depth"))
            elif enc == "amf":
                self._apply_encoder_combo_value(widgets.amf_qual, opts.get("quality"))
                self._apply_int_value(widgets.amf_qp, opts.get("qp"))
            elif enc == "cpu":
                self._apply_encoder_combo_value(widgets.x265_tune, opts.get("tune"))
                self._apply_encoder_combo_value(widgets.x265_aqm, opts.get("aq_mode"))
                self._apply_float_value(widgets.x265_aqs, opts.get("aq_strength"))
                self._apply_float_value(widgets.x265_psy, opts.get("psy_rd"))
                self._apply_float_value(widgets.x265_psyrdoq, opts.get("psy_rdoq"))
                self._apply_int_value(widgets.x265_bf, opts.get("bf"))
                self._apply_int_value(widgets.x265_la, opts.get("rc_lookahead"))

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
