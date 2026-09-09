# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.type_utils import _safe_bool, _safe_float, _safe_int


class EncoderSettingsPersistenceMixin:
    def _sync_state_from_ui(self) -> None:
            widgets = self._ui.widgets
            self._state.encoder_key = self.enc_key()
            self._state.crf = widgets.crf_spin.value()
            self._state.preset = widgets.preset_combo.currentText()
            self._state.scale = widgets.scale_combo.currentText()
            self._state.strip_only = widgets.strip_cb.isChecked()
            self._state.overwrite_original = widgets.over_cb.isChecked()
            self._state.move = widgets.move_cb.isChecked()
            self._state.shutdown = widgets.shut_cb.isChecked()
            self._state.autocrop_enabled = widgets.autocrop_cb.isChecked()
            self._state.imax_auto_detect = widgets.imax_detect_cb.isChecked()
            self._state.imax_probe_interval_s = self._imax_probe_interval_s()
            self._state.preserve_dv = widgets.preserve_dv_cb.isChecked()
            self._state.preserve_hdrplus = widgets.preserve_hdrplus_cb.isChecked()
            self._state.encoder_options = self.collect_enc_opts()

    def save_encoder_settings(self) -> None:
            if self._state.loading:
                return
            self._sync_state_from_ui()
            widgets = self._ui.widgets
            c = self._default_codec
            s = self._settings
            s.setValue(f"encoder/{c}/encoder_idx", widgets.encoder_combo.currentIndex())
            s.setValue(f"encoder/{c}/crf", widgets.crf_spin.value())
            s.setValue(f"encoder/{c}/preset", widgets.preset_combo.currentText())
            s.setValue(f"encoder/{c}/scale", widgets.scale_combo.currentText())
            s.setValue(f"encoder/{c}/nv_preset", widgets.nv_preset.currentText())
            s.setValue(f"encoder/{c}/nv_cq", widgets.nv_cq.value())
            s.setValue(f"encoder/{c}/nv_bf", widgets.nv_bf.value())
            s.setValue(f"encoder/{c}/nv_bref", widgets.nv_bref.currentText())
            s.setValue(f"encoder/{c}/nv_la", widgets.nv_la.value())
            if getattr(widgets, "nv_lookahead_level", None) is not None:
                s.setValue(f"encoder/{c}/nv_lookahead_level", self._combo_value(widgets.nv_lookahead_level))
            if getattr(widgets, "nv_multipass", None) is not None:
                s.setValue(f"encoder/{c}/nv_multipass", self._combo_value(widgets.nv_multipass))
            s.setValue(f"encoder/{c}/nv_aq", widgets.nv_aq.value())
            s.setValue(f"encoder/{c}/nv_spatial", widgets.nv_spatial.isChecked())
            s.setValue(f"encoder/{c}/nv_temporal", widgets.nv_temporal.isChecked())
            s.setValue(f"encoder/{c}/qsv_preset", widgets.qsv_preset.currentText())
            s.setValue(f"encoder/{c}/qsv_q", widgets.qsv_q.value())
            s.setValue(f"encoder/{c}/qsv_la_depth", widgets.qsv_la_depth.value())
            s.remove(f"encoder/{c}/qsv_la")
            s.setValue(f"encoder/{c}/amf_qual", widgets.amf_qual.currentText())
            s.setValue(f"encoder/{c}/amf_qp", widgets.amf_qp.value())
            s.setValue(f"encoder/{c}/x265_tune", widgets.x265_tune.currentText())
            s.setValue(f"encoder/{c}/x265_aqm", widgets.x265_aqm.currentText())
            s.setValue(f"encoder/{c}/x265_aqs", widgets.x265_aqs.value())
            s.setValue(f"encoder/{c}/x265_psy", widgets.x265_psy.value())
            s.setValue(f"encoder/{c}/x265_psyrdoq", widgets.x265_psyrdoq.value())
            s.setValue(f"encoder/{c}/x265_bf", widgets.x265_bf.value())
            s.setValue(f"encoder/{c}/x265_la", widgets.x265_la.value())
            s.setValue(f"encoder/{c}/x265_crf", widgets.x265_crf.value())
            s.setValue(f"encoder/{c}/x265_preset", widgets.x265_preset.currentText())
            s.setValue(f"encoder/{c}/strip_only", widgets.strip_cb.isChecked())
            s.setValue(f"encoder/{c}/overwrite_original", widgets.over_cb.isChecked())
            s.setValue(f"encoder/{c}/move", widgets.move_cb.isChecked())
            s.setValue(f"encoder/{c}/autocrop", widgets.autocrop_cb.isChecked())
            s.setValue(f"encoder/{c}/imax_detect", widgets.imax_detect_cb.isChecked())
            if c in {"h265", "av1"}:
                s.setValue(f"encoder/{c}/preserve_dv", widgets.preserve_dv_cb.isChecked())
                s.setValue(f"encoder/{c}/preserve_hdrplus", widgets.preserve_hdrplus_cb.isChecked())
            # Herunterfahren bleibt bewusst nur Sitzungszustand:
            # nicht in Encoder-/Profil-Settings speichern und beim Laden nicht zuruecksetzen.
            s.sync()

    def load_encoder_settings(self) -> None:
            widgets = self._ui.widgets
            c = self._default_codec
            s = self._settings
            self._state.loading = True
            try:
                def iv(key: str, default=None):
                    return s.value(f"encoder/{c}/{key}", default)

                def to_bool(value, default=False) -> bool:
                    return _safe_bool(value, default)

                idx = _safe_int(iv("encoder_idx", None), None)
                if idx is not None and 0 <= idx < widgets.encoder_combo.count():
                    widgets.encoder_combo.setCurrentIndex(idx)
                crf = _safe_int(iv("crf", None), None)
                if crf is not None:
                    widgets.crf_spin.setValue(crf)
                    widgets.x265_crf.setValue(crf)
                preset = iv("preset", None)
                if preset and widgets.preset_combo.findText(str(preset)) >= 0:
                    widgets.preset_combo.setCurrentText(str(preset))
                if preset and widgets.x265_preset.findText(str(preset)) >= 0:
                    widgets.x265_preset.setCurrentText(str(preset))
                scale = iv("scale", None)
                if scale and widgets.scale_combo.findText(str(scale)) >= 0:
                    widgets.scale_combo.setCurrentText(str(scale))
                for key, combo in [
                    ("nv_preset", widgets.nv_preset),
                    ("nv_bref", widgets.nv_bref),
                    ("nv_lookahead_level", getattr(widgets, "nv_lookahead_level", None)),
                    ("nv_multipass", getattr(widgets, "nv_multipass", None)),
                    ("qsv_preset", widgets.qsv_preset),
                    ("amf_qual", widgets.amf_qual),
                    ("x265_tune", widgets.x265_tune),
                    ("x265_aqm", widgets.x265_aqm),
                    ("x265_preset", widgets.x265_preset),
                ]:
                    if combo is None:
                        continue
                    value = iv(key, None)
                    if value and combo.findText(str(value)) >= 0:
                        combo.setCurrentText(str(value))
                for key, widget in [
                    ("nv_cq", widgets.nv_cq),
                    ("nv_bf", widgets.nv_bf),
                    ("nv_la", widgets.nv_la),
                    ("nv_aq", widgets.nv_aq),
                    ("qsv_q", widgets.qsv_q),
                    ("qsv_la_depth", widgets.qsv_la_depth),
                    ("amf_qp", widgets.amf_qp),
                    ("x265_bf", widgets.x265_bf),
                    ("x265_la", widgets.x265_la),
                    ("x265_crf", widgets.x265_crf),
                ]:
                    value = _safe_int(iv(key, None), None)
                    if value is not None:
                        widget.setValue(value)
                for key, widget in [
                    ("x265_aqs", widgets.x265_aqs),
                    ("x265_psy", widgets.x265_psy),
                    ("x265_psyrdoq", widgets.x265_psyrdoq),
                ]:
                    value = iv(key, None)
                    if value is not None:
                        widget.setValue(_safe_float(value, widget.value()))
                widgets.nv_spatial.setChecked(to_bool(iv("nv_spatial", widgets.nv_spatial.isChecked())))
                widgets.nv_temporal.setChecked(to_bool(iv("nv_temporal", widgets.nv_temporal.isChecked())))
                widgets.strip_cb.setChecked(to_bool(iv("strip_only", widgets.strip_cb.isChecked())))
                widgets.over_cb.setChecked(to_bool(iv("overwrite_original", widgets.over_cb.isChecked())))
                widgets.move_cb.setChecked(to_bool(iv("move", widgets.move_cb.isChecked())))
                widgets.autocrop_cb.setChecked(to_bool(iv("autocrop", widgets.autocrop_cb.isChecked())))
                widgets.imax_detect_cb.setChecked(to_bool(iv("imax_detect", widgets.imax_detect_cb.isChecked())))
                if c in {"h265", "av1"}:
                    widgets.preserve_dv_cb.setChecked(to_bool(iv("preserve_dv", True), True))
                    widgets.preserve_hdrplus_cb.setChecked(to_bool(iv("preserve_hdrplus", True), True))
                else:
                    widgets.preserve_dv_cb.setChecked(False)
                    widgets.preserve_hdrplus_cb.setChecked(False)
            finally:
                self._state.loading = False
            self.refresh_enc_panel()
