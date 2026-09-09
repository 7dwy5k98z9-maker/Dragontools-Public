# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.settings import (
    DEFAULT_AUTOCROP_MODE,
    DEFAULT_AUTOCROP_PROBE_DURATION_S,
    DEFAULT_AUTOCROP_PROBE_INTERVAL_S,
    DEFAULT_AUTOCROP_PROBE_START_S,
    DEFAULT_IMAX_MIN_HITS,
    DEFAULT_IMAX_MIN_VARIANCE_PERCENT,
    DEFAULT_IMAX_PROBE_DURATION_S,
    DEFAULT_IMAX_PROBE_INTERVAL_S,
    SET_KEY_AUTOCROP_MODE,
    SET_KEY_AUTOCROP_PROBE_DURATION,
    SET_KEY_AUTOCROP_PROBE_INTERVAL,
    SET_KEY_AUTOCROP_PROBE_START,
    SET_KEY_IMAX_MIN_HITS,
    SET_KEY_IMAX_MIN_VARIANCE_PERCENT,
    SET_KEY_IMAX_PROBE_DURATION,
    SET_KEY_IMAX_PROBE_INTERVAL,
    settings_int,
)


class EncoderSettingsOptionsMixin:
    def collect_enc_opts(self) -> dict:
            widgets = self._ui.widgets
            enc = self._active_encoder()
            opts = {"encoder": enc}
            if enc == "nvenc":
                opts.update({
                    "preset": widgets.nv_preset.currentText(),
                    "cq": widgets.nv_cq.value(),
                    "bf": widgets.nv_bf.value(),
                    "bref_mode": widgets.nv_bref.currentText(),
                    "rc_lookahead": widgets.nv_la.value(),
                    "lookahead_level": self._combo_value(getattr(widgets, "nv_lookahead_level", None)),
                    "multipass": self._combo_value(getattr(widgets, "nv_multipass", None)),
                    "aq_strength": widgets.nv_aq.value(),
                    "spatial_aq": widgets.nv_spatial.isChecked(),
                    "temporal_aq": widgets.nv_temporal.isChecked(),
                })
            elif enc == "qsv":
                opts.update({
                    "preset": widgets.qsv_preset.currentText(),
                    "q": widgets.qsv_q.value(),
                    "lookahead_depth": widgets.qsv_la_depth.value(),
                })
            elif enc == "amf":
                opts.update({
                    "quality": widgets.amf_qual.currentText(),
                    "qp": widgets.amf_qp.value(),
                })
            elif enc == "cpu":
                widgets.crf_spin.setValue(widgets.x265_crf.value())
                widgets.preset_combo.setCurrentText(widgets.x265_preset.currentText())
                if self._default_codec == "h265":
                    opts.update({
                        "tune": widgets.x265_tune.currentText(),
                        "aq_mode": widgets.x265_aqm.currentText(),
                        "aq_strength": str(widgets.x265_aqs.value()),
                        "psy_rd": str(widgets.x265_psy.value()),
                        "psy_rdoq": str(widgets.x265_psyrdoq.value()),
                        "bf": widgets.x265_bf.value(),
                        "rc_lookahead": widgets.x265_la.value(),
                    })
            hdr_meta_codec = self._default_codec in {"h265", "av1"}
            opts["preserve_dv"] = hdr_meta_codec and widgets.preserve_dv_cb.isChecked()
            opts["preserve_hdrplus"] = hdr_meta_codec and widgets.preserve_hdrplus_cb.isChecked()
            opts["autocrop_enabled"] = widgets.autocrop_cb.isChecked()
            opts["imax_auto_detect"] = widgets.imax_detect_cb.isChecked()
            opts["autocrop_mode"] = self._settings_text(
                SET_KEY_AUTOCROP_MODE,
                DEFAULT_AUTOCROP_MODE,
                allowed={"single", "multi"},
            )
            opts["autocrop_probe_start_s"] = self._settings_int(
                SET_KEY_AUTOCROP_PROBE_START,
                DEFAULT_AUTOCROP_PROBE_START_S,
                minimum=0,
                maximum=3600,
            )
            opts["autocrop_probe_duration_s"] = self._settings_int(
                SET_KEY_AUTOCROP_PROBE_DURATION,
                DEFAULT_AUTOCROP_PROBE_DURATION_S,
                minimum=2,
                maximum=120,
            )
            opts["autocrop_probe_interval_s"] = self._settings_int(
                SET_KEY_AUTOCROP_PROBE_INTERVAL,
                DEFAULT_AUTOCROP_PROBE_INTERVAL_S,
                minimum=60,
                maximum=1800,
            )
            opts["imax_probe_interval_s"] = self._settings_int(
                SET_KEY_IMAX_PROBE_INTERVAL,
                DEFAULT_IMAX_PROBE_INTERVAL_S,
                minimum=30,
                maximum=600,
            )
            opts["imax_probe_duration_s"] = self._settings_int(
                SET_KEY_IMAX_PROBE_DURATION,
                DEFAULT_IMAX_PROBE_DURATION_S,
                minimum=1,
                maximum=30,
            )
            opts["imax_min_variance_percent"] = self._settings_int(
                SET_KEY_IMAX_MIN_VARIANCE_PERCENT,
                DEFAULT_IMAX_MIN_VARIANCE_PERCENT,
                minimum=1,
                maximum=100,
            )
            opts["imax_min_hits"] = self._settings_int(
                SET_KEY_IMAX_MIN_HITS,
                DEFAULT_IMAX_MIN_HITS,
                minimum=2,
                maximum=50,
            )
            return opts

    @staticmethod
    def _combo_value(combo) -> str:
            if combo is None:
                return "auto"
            data = combo.currentData()
            return str(data if data is not None else combo.currentText()).strip()

    def _imax_probe_interval_s(self) -> int:
            return self._settings_int(
                SET_KEY_IMAX_PROBE_INTERVAL,
                DEFAULT_IMAX_PROBE_INTERVAL_S,
                minimum=30,
                maximum=600,
            )

    def _settings_int(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
            return settings_int(
                self._settings, key, default, minimum=minimum, maximum=maximum
            )

    def _settings_text(self, key: str, default: str, *, allowed: set[str]) -> str:
            try:
                value = str(self._settings.value(key, default, type=str) or default)
            except TypeError:
                value = str(self._settings.value(key, default) or default)
            value = value.strip().lower()
            return value if value in allowed else default
