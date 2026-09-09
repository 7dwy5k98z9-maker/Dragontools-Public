# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.codec_utils import normalize_target_codec, value_or_default
from ..core.encoder_profile_override import scoped_encoder_options
from ..core.type_utils import _safe_bool, _safe_float, _safe_int
from .ui_helpers import install_persistent_window_geometry

class _QualityRunDialog(QDialog):
    """Assistent für einen Qualitätstestlauf mit den wichtigsten Encoder-Optionen."""

    CODECS = [
        ("H.265 / HEVC", "h265"),
        ("H.264 / AVC", "h264"),
        ("AV1", "av1"),
    ]
    ENCODERS = [
        ("CPU (Software)", "cpu"),
        ("NVIDIA NVENC", "nvenc"),
        ("Intel QSV", "qsv"),
        ("AMD AMF", "amf"),
    ]
    SCALE_MODES = [("Original", "original"), ("1080p", "1080p"), ("720p", "720p"), ("480p", "480p")]

    def __init__(self, initial: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Testlauf einrichten")
        self.setMinimumWidth(620)
        self._advanced_widgets: dict[str, list[QWidget]] = {}
        self._init_ui(initial or {})
        self._load_initial(initial or {})
        self._refresh_for_codec_encoder()
        if initial:
            self.preset_combo.setCurrentText(str(initial.get("preset") or self.preset_combo.currentText()))
            self.pix_fmt_combo.setCurrentText(str(initial.get("pix_fmt") or self.pix_fmt_combo.currentText()))
        install_persistent_window_geometry(self, "quality_run_dialog")

    def _init_ui(self, initial: dict) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        base = QGroupBox("Basis")
        grid = QGridLayout(base)
        grid.addWidget(QLabel("Name:"), 0, 0)
        self.name_edit = QLineEdit(str(initial.get("name") or "Neuer Testlauf"))
        grid.addWidget(self.name_edit, 0, 1, 1, 3)

        grid.addWidget(QLabel("Codec:"), 1, 0)
        self.codec_combo = QComboBox()
        for label, value in self.CODECS:
            self.codec_combo.addItem(label, value)
        grid.addWidget(self.codec_combo, 1, 1)

        grid.addWidget(QLabel("Encoder:"), 1, 2)
        self.encoder_combo = QComboBox()
        for label, value in self.ENCODERS:
            self.encoder_combo.addItem(label, value)
        grid.addWidget(self.encoder_combo, 1, 3)

        grid.addWidget(QLabel("Qualität:"), 2, 0)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(0, 63)
        self.quality_spin.setValue(23)
        grid.addWidget(self.quality_spin, 2, 1)

        grid.addWidget(QLabel("Preset:"), 2, 2)
        self.preset_combo = QComboBox()
        self.preset_combo.setEditable(True)
        grid.addWidget(self.preset_combo, 2, 3)

        grid.addWidget(QLabel("Bit:"), 3, 0)
        self.pix_fmt_combo = QComboBox()
        grid.addWidget(self.pix_fmt_combo, 3, 1)

        grid.addWidget(QLabel("Skalierung:"), 3, 2)
        self.scale_combo = QComboBox()
        for label, value in self.SCALE_MODES:
            self.scale_combo.addItem(label, value)
        grid.addWidget(self.scale_combo, 3, 3)

        grid.addWidget(QLabel("Extra-Args:"), 4, 0)
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("optional, z. B. -film-grain 8")
        grid.addWidget(self.extra_edit, 4, 1, 1, 3)
        root.addWidget(base)

        adv = QGroupBox("Encoder-Optionen")
        adv_grid = QGridLayout(adv)
        row = 0

        self.cpu_tune = QComboBox()
        self.cpu_tune.addItems(["none", "animation", "grain", "fastdecode", "zerolatency"])
        self.cpu_aq_mode = QComboBox()
        self.cpu_aq_mode.addItems(["1", "2", "3", "4"])
        self.cpu_aq_strength = self._double_spin(0.0, 4.0, 1.0, 0.1, 2)
        self.cpu_psy_rd = self._double_spin(0.0, 5.0, 2.0, 0.1, 2)
        self.cpu_psy_rdoq = self._double_spin(0.0, 5.0, 1.0, 0.1, 2)
        self.cpu_bframes = self._spin(0, 16, 8)
        self.cpu_lookahead = self._spin(0, 250, 40)
        row = self._add_adv_row(adv_grid, row, "cpu", "Tune:", self.cpu_tune, "AQ-Mode:", self.cpu_aq_mode)
        row = self._add_adv_row(adv_grid, row, "cpu", "AQ-Stärke:", self.cpu_aq_strength, "psy-rd:", self.cpu_psy_rd)
        row = self._add_adv_row(adv_grid, row, "cpu", "psy-rdoq:", self.cpu_psy_rdoq, "B-Frames:", self.cpu_bframes)
        row = self._add_adv_row(adv_grid, row, "cpu", "Lookahead:", self.cpu_lookahead, "", None)

        self.nv_bframes = self._spin(0, 16, 4)
        self.nv_lookahead = self._spin(0, 64, 32)
        self.nv_aq_strength = self._spin(0, 15, 8)
        self.nv_bref = QComboBox()
        self.nv_bref.addItems(["disabled", "middle", "each"])
        self.nv_lookahead_level = QComboBox()
        self.nv_lookahead_level.addItem("Auto", "auto")
        for value in range(0, 4):
            self.nv_lookahead_level.addItem(str(value), str(value))
        self.nv_multipass = QComboBox()
        self.nv_multipass.addItem("Auto/Default", "auto")
        self.nv_multipass.addItem("disabled", "disabled")
        self.nv_multipass.addItem("qres", "qres")
        self.nv_multipass.addItem("fullres", "fullres")
        self.nv_spatial_aq = QCheckBox("Spatial AQ")
        self.nv_spatial_aq.setChecked(True)
        self.nv_temporal_aq = QCheckBox("Temporal AQ")
        self.nv_temporal_aq.setChecked(True)
        row = self._add_adv_row(adv_grid, row, "nvenc", "B-Frames:", self.nv_bframes, "Lookahead:", self.nv_lookahead)
        row = self._add_adv_row(adv_grid, row, "nvenc", "AQ-Stärke:", self.nv_aq_strength, "B-Ref-Mode:", self.nv_bref)
        row = self._add_adv_row(adv_grid, row, "nvenc", "Lookahead-Level:", self.nv_lookahead_level, "Multipass:", self.nv_multipass)
        row = self._add_adv_row(adv_grid, row, "nvenc", "", self.nv_spatial_aq, "", self.nv_temporal_aq)

        self.qsv_lookahead = self._spin(1, 100, 40)
        row = self._add_adv_row(adv_grid, row, "qsv", "Lookahead-Tiefe:", self.qsv_lookahead, "", None)

        info = QLabel("AMD AMF nutzt im Testlauf Qualität/Preset aus den Basisfeldern.")
        info.setWordWrap(True)
        adv_grid.addWidget(info, row, 0, 1, 4)
        self._advanced_widgets.setdefault("amf", []).append(info)
        root.addWidget(adv)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.codec_combo.currentIndexChanged.connect(lambda _idx: self._refresh_for_codec_encoder())
        self.encoder_combo.currentIndexChanged.connect(lambda _idx: self._refresh_for_codec_encoder())

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    @staticmethod
    def _double_spin(minimum: float, maximum: float, value: float, step: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        return spin

    def _add_adv_row(
        self,
        layout: QGridLayout,
        row: int,
        key: str,
        left_label: str,
        left_widget: QWidget | None,
        right_label: str,
        right_widget: QWidget | None,
    ) -> int:
        widgets: list[QWidget] = []
        if left_label:
            label = QLabel(left_label)
            layout.addWidget(label, row, 0)
            widgets.append(label)
        if left_widget is not None:
            layout.addWidget(left_widget, row, 1)
            widgets.append(left_widget)
        if right_label:
            label = QLabel(right_label)
            layout.addWidget(label, row, 2)
            widgets.append(label)
        if right_widget is not None:
            layout.addWidget(right_widget, row, 3)
            widgets.append(right_widget)
        self._advanced_widgets.setdefault(key, []).extend(widgets)
        return row + 1

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx < 0:
            idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_initial(self, initial: dict) -> None:
        self._set_combo_data(self.codec_combo, normalize_target_codec(initial.get("codec") or "h265"))
        self._set_combo_data(self.encoder_combo, str(initial.get("encoder") or "cpu").lower())
        quality = _safe_int(initial.get("quality"), 23)
        self.quality_spin.setValue(max(0, min(63, 23 if quality is None else quality)))
        self.extra_edit.setText(str(initial.get("extra_args") or ""))
        self._set_combo_data(self.scale_combo, str(initial.get("scale") or "original").lower())

        opts = dict(initial.get("encoder_options") or {})
        active_encoder = str(initial.get("encoder") or opts.get("encoder") or "cpu").lower()
        cpu_opts = scoped_encoder_options(
            opts, active_encoder=active_encoder, target_encoder="cpu"
        )
        nvenc_opts = scoped_encoder_options(
            opts, active_encoder=active_encoder, target_encoder="nvenc"
        )
        qsv_opts = scoped_encoder_options(
            opts, active_encoder=active_encoder, target_encoder="qsv"
        )

        self.cpu_tune.setCurrentText(str(cpu_opts.get("tune", "none") or "none"))
        self.cpu_aq_mode.setCurrentText(str(cpu_opts.get("aq_mode", "2") or "2"))
        self.cpu_aq_strength.setValue(_safe_float(value_or_default(cpu_opts.get("aq_strength"), 1.0), 1.0))
        self.cpu_psy_rd.setValue(_safe_float(value_or_default(cpu_opts.get("psy_rd"), 2.0), 2.0))
        self.cpu_psy_rdoq.setValue(_safe_float(value_or_default(cpu_opts.get("psy_rdoq"), 1.0), 1.0))
        self.cpu_bframes.setValue(_safe_int(value_or_default(cpu_opts.get("bf"), 8), 8))
        self.cpu_lookahead.setValue(_safe_int(value_or_default(cpu_opts.get("rc_lookahead"), 40), 40))

        self.nv_bframes.setValue(_safe_int(value_or_default(nvenc_opts.get("bf"), 4), 4))
        self.nv_lookahead.setValue(_safe_int(value_or_default(nvenc_opts.get("rc_lookahead"), 32), 32))
        self.nv_aq_strength.setValue(_safe_int(value_or_default(nvenc_opts.get("aq_strength"), 8), 8))
        self.nv_bref.setCurrentText(str(nvenc_opts.get("bref_mode", "middle") or "middle"))
        self._set_combo_data(self.nv_lookahead_level, str(nvenc_opts.get("lookahead_level", "auto") or "auto"))
        self._set_combo_data(self.nv_multipass, str(nvenc_opts.get("multipass", "auto") or "auto"))
        self.nv_spatial_aq.setChecked(_safe_bool(nvenc_opts.get("spatial_aq", True), True))
        self.nv_temporal_aq.setChecked(_safe_bool(nvenc_opts.get("temporal_aq", True), True))
        self.qsv_lookahead.setValue(_safe_int(value_or_default(qsv_opts.get("lookahead_depth"), 40), 40))

    def _refresh_for_codec_encoder(self) -> None:
        codec = str(self.codec_combo.currentData() or "h265")
        encoder = str(self.encoder_combo.currentData() or "cpu")

        old_preset = self.preset_combo.currentText().strip()
        self.preset_combo.clear()
        if encoder == "nvenc":
            presets = ["p6", "p5", "p7", "p4", "p3", "p2", "p1"]
        elif encoder == "amf":
            presets = ["balanced", "quality", "speed"]
        elif encoder == "cpu" and codec == "av1":
            presets = ["6", "4", "8", "10"]
        else:
            presets = ["medium", "slow", "fast", "slower", "faster", "veryslow", "veryfast"]
        self.preset_combo.addItems(presets)
        if old_preset:
            self.preset_combo.setCurrentText(old_preset)

        old_pix = self.pix_fmt_combo.currentText().strip()
        self.pix_fmt_combo.clear()
        if codec == "h264":
            self.pix_fmt_combo.addItem("8-bit", "8-bit")
        elif codec == "h265":
            self.pix_fmt_combo.addItem("10-bit", "10-bit")
        else:
            self.pix_fmt_combo.addItem("auto", "auto")
        if old_pix:
            self.pix_fmt_combo.setCurrentText(old_pix)

        for key, widgets in self._advanced_widgets.items():
            enabled = key == encoder and not (encoder == "cpu" and codec != "h265")
            for widget in widgets:
                widget.setEnabled(enabled)

    def values(self) -> dict:
        codec = str(self.codec_combo.currentData() or "h265")
        encoder = str(self.encoder_combo.currentData() or "cpu")
        quality = int(self.quality_spin.value())
        preset = self.preset_combo.currentText().strip() or ("p6" if encoder == "nvenc" else "medium")
        opts: dict[str, object] = {"encoder": encoder, "preset": preset}
        if encoder == "cpu" and codec == "h265":
            opts.update({
                "tune": self.cpu_tune.currentText(),
                "aq_mode": self.cpu_aq_mode.currentText(),
                "aq_strength": self.cpu_aq_strength.value(),
                "psy_rd": self.cpu_psy_rd.value(),
                "psy_rdoq": self.cpu_psy_rdoq.value(),
                "bf": self.cpu_bframes.value(),
                "rc_lookahead": self.cpu_lookahead.value(),
            })
        elif encoder == "nvenc":
            opts.update({
                "cq": quality,
                "bf": self.nv_bframes.value(),
                "rc_lookahead": self.nv_lookahead.value(),
                "aq_strength": self.nv_aq_strength.value(),
                "bref_mode": self.nv_bref.currentText(),
                "lookahead_level": str(self.nv_lookahead_level.currentData() or "auto"),
                "multipass": str(self.nv_multipass.currentData() or "auto"),
                "spatial_aq": self.nv_spatial_aq.isChecked(),
                "temporal_aq": self.nv_temporal_aq.isChecked(),
            })
        elif encoder == "qsv":
            opts.update({"q": quality, "lookahead_depth": self.qsv_lookahead.value()})
        elif encoder == "amf":
            opts.update({"qp": quality, "quality": preset})
        return {
            "name": self.name_edit.text().strip() or "Testlauf",
            "codec": codec,
            "encoder": encoder,
            "quality": quality,
            "preset": preset,
            "pix_fmt": str(self.pix_fmt_combo.currentData() or self.pix_fmt_combo.currentText() or "10-bit"),
            "scale": str(self.scale_combo.currentData() or "original"),
            "extra_args": self.extra_edit.text().strip(),
            "encoder_options": opts,
        }
