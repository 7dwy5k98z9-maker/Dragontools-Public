# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QWidget

from ..core.encoder_profile_override import MODE_TO_SCALE_LABEL, SCALE_LABELS_TO_MODE, scoped_encoder_options
from ..core.type_utils import _safe_bool, _safe_float, _safe_int
from .convert_widget_encoder_panels import create_encoder_controls, preset_items
from .convert_widget_encoder_state import default_encoder_preset


class EncoderOverrideControls:
    """Maps encoder-override widgets to and from the persisted override dict."""

    def __init__(self, default_codec: str) -> None:
        self.default_codec = str(default_codec or "h265")

    @staticmethod
    def create(parent: QWidget) -> dict:
        return create_encoder_controls(parent)

    def load_snapshot(self, controls: dict, snapshot: dict) -> None:
        encoder = str(snapshot.get("encoder") or "cpu")
        idx = controls["encoder"].findData(encoder)
        controls["encoder"].setCurrentIndex(max(0, idx))
        controls["scale"].setCurrentText(
            MODE_TO_SCALE_LABEL.get(snapshot.get("scale_mode") or "original", "original")
        )
        controls["quality"].setValue(_safe_int(snapshot.get("quality"), 22))
        options = dict(snapshot.get("encoder_options") or {})
        preferred = str(snapshot.get("preset") or default_encoder_preset(encoder, self.default_codec))
        self._set_preset_items(controls["preset"], encoder, preferred)

        # Overlapping option names must never leak between encoder backends.
        cpu_options = scoped_encoder_options(options, active_encoder=encoder, target_encoder="cpu")
        nvenc_options = scoped_encoder_options(options, active_encoder=encoder, target_encoder="nvenc")
        qsv_options = scoped_encoder_options(options, active_encoder=encoder, target_encoder="qsv")
        self._load_cpu(controls["cpu"], cpu_options)
        self._load_nvenc(controls["nvenc"], nvenc_options)
        controls["qsv"]["lookahead_depth"].setValue(_safe_int(qsv_options.get("lookahead_depth"), 40))

    def refresh_encoder(self, controls: dict) -> None:
        encoder = str(controls["encoder"].currentData() or "cpu")
        controls["stack"].setCurrentIndex({"cpu": 0, "nvenc": 1, "qsv": 2, "amf": 3}[encoder])
        self._set_preset_items(controls["preset"], encoder, controls["preset"].currentText())

    @staticmethod
    def refresh_enabled(controls: dict) -> None:
        enabled = controls["mode"].currentData() == "custom"
        for key in ("encoder", "scale", "quality", "preset", "stack"):
            controls[key].setEnabled(enabled)

    def collect(self, controls: dict) -> dict:
        encoder = str(controls["encoder"].currentData() or "cpu")
        quality = int(controls["quality"].value())
        preset = controls["preset"].currentText()
        options = self._collect_backend_options(controls, encoder, quality, preset)
        return {
            "codec": self.default_codec,
            "encoder": encoder,
            "quality": quality,
            "preset": preset,
            "scale_mode": SCALE_LABELS_TO_MODE.get(controls["scale"].currentText(), "original"),
            "encoder_options": options,
        }

    @staticmethod
    def _collect_backend_options(controls: dict, encoder: str, quality: int, preset: str) -> dict:
        options: dict = {"encoder": encoder}
        if encoder == "cpu":
            c = controls["cpu"]
            options.update({
                "tune": c["tune"].currentText(), "aq_mode": c["aq_mode"].currentText(),
                "aq_strength": str(c["aq_strength"].value()), "psy_rd": str(c["psy_rd"].value()),
                "psy_rdoq": str(c["psy_rdoq"].value()), "bf": c["bf"].value(),
                "rc_lookahead": c["rc_lookahead"].value(),
            })
        elif encoder == "nvenc":
            c = controls["nvenc"]
            options.update({
                "preset": preset, "cq": quality, "bf": c["bf"].value(),
                "bref_mode": c["bref_mode"].currentText(), "rc_lookahead": c["rc_lookahead"].value(),
                "lookahead_level": c["lookahead_level"].currentText(),
                "multipass": c["multipass"].currentText(), "aq_strength": c["aq_strength"].value(),
                "spatial_aq": c["spatial_aq"].isChecked(), "temporal_aq": c["temporal_aq"].isChecked(),
            })
        elif encoder == "qsv":
            c = controls["qsv"]
            options.update({"preset": preset, "q": quality, "lookahead_depth": c["lookahead_depth"].value()})
        else:
            options.update({"quality": preset, "qp": quality})
        return options

    def _set_preset_items(self, combo: QComboBox, encoder: str, preferred: str) -> None:
        items = preset_items(encoder, self.default_codec)
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(list(items))
        combo.setCurrentText(
            preferred if preferred in items else default_encoder_preset(encoder, self.default_codec)
        )
        combo.blockSignals(False)

    @staticmethod
    def _load_cpu(controls: dict, options: dict) -> None:
        controls["tune"].setCurrentText(str(options.get("tune", "none")))
        controls["aq_mode"].setCurrentText(str(options.get("aq_mode", "2")))
        controls["aq_strength"].setValue(_safe_float(options.get("aq_strength"), 1.0))
        controls["psy_rd"].setValue(_safe_float(options.get("psy_rd"), 2.0))
        controls["psy_rdoq"].setValue(_safe_float(options.get("psy_rdoq"), 1.0))
        controls["bf"].setValue(_safe_int(options.get("bf"), 8))
        controls["rc_lookahead"].setValue(_safe_int(options.get("rc_lookahead"), 40))

    @staticmethod
    def _load_nvenc(controls: dict, options: dict) -> None:
        controls["bf"].setValue(_safe_int(options.get("bf"), 4))
        controls["bref_mode"].setCurrentText(str(options.get("bref_mode", "middle")))
        controls["rc_lookahead"].setValue(_safe_int(options.get("rc_lookahead"), 32))
        controls["lookahead_level"].setCurrentText(str(options.get("lookahead_level", "auto")))
        controls["multipass"].setCurrentText(str(options.get("multipass", "auto")))
        controls["aq_strength"].setValue(_safe_int(options.get("aq_strength"), 8))
        controls["spatial_aq"].setChecked(_safe_bool(options.get("spatial_aq", True), True))
        controls["temporal_aq"].setChecked(_safe_bool(options.get("temporal_aq", True), True))
