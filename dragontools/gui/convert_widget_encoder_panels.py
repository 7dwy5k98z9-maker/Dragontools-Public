# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QSpinBox,
    QStackedWidget,
    QWidget,
)

_ENCODER_LABELS = (
    ("CPU (Software)", "cpu"),
    ("NVIDIA NVENC", "nvenc"),
    ("Intel QSV", "qsv"),
    ("AMD AMF", "amf"),
)
_SCALE_ITEMS = ("original", "4K (2160p)", "1080p", "720p", "480p")
_CPU_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
_AV1_CPU_PRESETS = ("4", "5", "6", "7", "8", "9", "10", "11", "12")
_NVENC_PRESETS = ("p1", "p2", "p3", "p4", "p5", "p6", "p7")
_QSV_PRESETS = ("veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
_AMF_PRESETS = ("speed", "balanced", "quality")


def preset_items(encoder: str, default_codec: str) -> tuple[str, ...]:
    return {
        "cpu": _AV1_CPU_PRESETS if default_codec == "av1" else _CPU_PRESETS,
        "nvenc": _NVENC_PRESETS,
        "qsv": _QSV_PRESETS,
        "amf": _AMF_PRESETS,
    }[encoder]


def create_encoder_controls(parent: QWidget) -> dict:
    mode = QComboBox(parent)
    mode.addItem("Global / Encoder-Profil verwenden", "inherit")
    mode.addItem("Benutzerdefiniert", "custom")
    encoder = QComboBox(parent)
    for label, key in _ENCODER_LABELS:
        encoder.addItem(label, key)
    scale = QComboBox(parent)
    scale.addItems(list(_SCALE_ITEMS))
    quality = QSpinBox(parent)
    quality.setRange(0, 63)
    preset = QComboBox(parent)
    stack = QStackedWidget(parent)
    cpu = _cpu_panel(parent)
    nvenc = _nvenc_panel(parent)
    qsv = _qsv_panel(parent)
    amf = _amf_panel(parent)
    for panel in (cpu["widget"], nvenc["widget"], qsv["widget"], amf["widget"]):
        stack.addWidget(panel)
    return {
        "mode": mode,
        "encoder": encoder,
        "scale": scale,
        "quality": quality,
        "preset": preset,
        "stack": stack,
        "cpu": cpu,
        "nvenc": nvenc,
        "qsv": qsv,
        "amf": amf,
    }


def _cpu_panel(parent: QWidget) -> dict:
    widget = QWidget(parent)
    grid = QGridLayout(widget)
    tune = QComboBox(widget); tune.addItems(["none", "grain", "animation", "ssim", "psnr"])
    aq_mode = QComboBox(widget); aq_mode.addItems(["0", "1", "2", "3"])
    aq_strength = QDoubleSpinBox(widget); aq_strength.setRange(0, 3); aq_strength.setSingleStep(0.1)
    psy_rd = QDoubleSpinBox(widget); psy_rd.setRange(0, 5); psy_rd.setSingleStep(0.1)
    psy_rdoq = QDoubleSpinBox(widget); psy_rdoq.setRange(0, 50); psy_rdoq.setSingleStep(0.5)
    bf = QSpinBox(widget); bf.setRange(0, 16)
    lookahead = QSpinBox(widget); lookahead.setRange(0, 250)
    fields = (
        ("Tune", tune), ("AQ-Mode", aq_mode), ("AQ-Stärke", aq_strength),
        ("psy-rd", psy_rd), ("psy-rdoq", psy_rdoq), ("B-Frames", bf),
        ("Lookahead", lookahead),
    )
    for idx, (label, control) in enumerate(fields):
        row, col = divmod(idx, 2)
        grid.addWidget(QLabel(label + ":"), row, col * 2)
        grid.addWidget(control, row, col * 2 + 1)
    return {
        "widget": widget, "tune": tune, "aq_mode": aq_mode,
        "aq_strength": aq_strength, "psy_rd": psy_rd, "psy_rdoq": psy_rdoq,
        "bf": bf, "rc_lookahead": lookahead,
    }


def _nvenc_panel(parent: QWidget) -> dict:
    widget = QWidget(parent)
    grid = QGridLayout(widget)
    bf = QSpinBox(widget); bf.setRange(0, 8)
    bref = QComboBox(widget); bref.addItems(["disabled", "each", "middle"])
    lookahead = QSpinBox(widget); lookahead.setRange(0, 64)
    la_level = QComboBox(widget); la_level.addItems(["auto", "0", "1", "2", "3"])
    multipass = QComboBox(widget); multipass.addItems(["auto", "disabled", "qres", "fullres"])
    aq_strength = QSpinBox(widget); aq_strength.setRange(1, 15)
    spatial = QCheckBox("Spatial AQ", widget)
    temporal = QCheckBox("Temporal AQ", widget)
    fields = (
        ("B-Frames", bf), ("B-Ref-Mode", bref), ("Lookahead", lookahead),
        ("Lookahead-Level", la_level), ("Multipass", multipass), ("AQ-Stärke", aq_strength),
    )
    for idx, (label, control) in enumerate(fields):
        row, col = divmod(idx, 2)
        grid.addWidget(QLabel(label + ":"), row, col * 2)
        grid.addWidget(control, row, col * 2 + 1)
    grid.addWidget(spatial, 3, 0, 1, 2)
    grid.addWidget(temporal, 3, 2, 1, 2)
    return {
        "widget": widget, "bf": bf, "bref_mode": bref, "rc_lookahead": lookahead,
        "lookahead_level": la_level, "multipass": multipass, "aq_strength": aq_strength,
        "spatial_aq": spatial, "temporal_aq": temporal,
    }


def _qsv_panel(parent: QWidget) -> dict:
    widget = QWidget(parent)
    grid = QGridLayout(widget)
    lookahead = QSpinBox(widget); lookahead.setRange(1, 100)
    grid.addWidget(QLabel("Lookahead-Tiefe:"), 0, 0)
    grid.addWidget(lookahead, 0, 1)
    return {"widget": widget, "lookahead_depth": lookahead}


def _amf_panel(parent: QWidget) -> dict:
    widget = QWidget(parent)
    grid = QGridLayout(widget)
    grid.addWidget(QLabel("Für AMF werden QP und Qualitätsmodus oben gesetzt."), 0, 0)
    return {"widget": widget}
