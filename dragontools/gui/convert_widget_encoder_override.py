# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.encoder_profile_override import (
    MODE_TO_SCALE_LABEL,
    normalize_encoder_override,
    scoped_encoder_options,
)
from ..core.type_utils import _safe_bool, _safe_float, _safe_int


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


class EncoderOverrideDialogHelper:
    """Baut und persistiert manuelle per-Datei-Encoder-/Skalierungswerte.

    Der Zielcodec bleibt an den geöffneten Converter-Tab gebunden. Dadurch kann
    eine Queue z.B. einzelne Dateien per NVENC und andere per CPU verarbeiten,
    ohne die Pipeline-/Codec-Semantik des Tabs aufzuweichen.
    """

    def __init__(self, owner, *, guard_queue_edit_allowed, log) -> None:
        self.owner = owner
        self._guard_queue_edit_allowed = guard_queue_edit_allowed
        self._log = log

    def build_group(self, layout: QVBoxLayout, override: dict) -> dict:
        group = QGroupBox("Encoder / Skalierung (per Datei)")
        grid = QGridLayout(group)
        controls = self._create_controls(group)
        manual = normalize_encoder_override(
            override.get("encoder_override"),
            default_codec=self.owner.default_codec,
        )
        snapshot = manual or self._global_snapshot()

        grid.addWidget(QLabel("Modus:"), 0, 0)
        grid.addWidget(controls["mode"], 0, 1)
        grid.addWidget(QLabel("Encoder:"), 1, 0)
        grid.addWidget(controls["encoder"], 1, 1)
        grid.addWidget(QLabel("Skalierung:"), 1, 2)
        grid.addWidget(controls["scale"], 1, 3)
        grid.addWidget(QLabel("Qualität:"), 2, 0)
        grid.addWidget(controls["quality"], 2, 1)
        grid.addWidget(QLabel("Preset/Qualität:"), 2, 2)
        grid.addWidget(controls["preset"], 2, 3)
        grid.addWidget(controls["stack"], 3, 0, 1, 4)
        layout.addWidget(group)

        controls["mode"].setCurrentIndex(1 if manual else 0)
        self._load_snapshot(controls, snapshot)
        controls["encoder"].currentIndexChanged.connect(
            lambda _idx: self._refresh_encoder_controls(controls)
        )
        controls["mode"].currentIndexChanged.connect(
            lambda _idx: self._refresh_enabled(controls)
        )
        self._refresh_encoder_controls(controls)
        self._refresh_enabled(controls)
        return controls

    def persist_group(self, override: dict, controls: dict) -> None:
        if controls["mode"].currentData() != "custom":
            override.pop("encoder_override", None)
            return
        override["encoder_override"] = self._collect_controls(controls)
        # Ein freier manueller Override gewinnt gegenüber einem gespeicherten
        # Encoder-Profil. Das Profil bleibt erhalten und wird wieder wirksam,
        # sobald der manuelle Modus auf "Global / Profil" zurückgestellt wird.

    def edit_paths(self, paths: Iterable[str]) -> None:
        unique_paths = list(dict.fromkeys(str(path) for path in paths if str(path or "")))
        if not unique_paths:
            return
        owner = self.owner
        if not self._guard_queue_edit_allowed("Encoder-/Skalierungs-Override ändern"):
            return

        existing = self._common_override(unique_paths)
        dlg = QDialog(owner)
        dlg.setWindowTitle(
            f"Encoder / Skalierung: {Path(unique_paths[0]).name}"
            if len(unique_paths) == 1
            else f"Encoder / Skalierung für {len(unique_paths)} Dateien"
        )
        dlg.resize(720, 520)
        root = QVBoxLayout(dlg)
        if len(unique_paths) > 1:
            note = QLabel(
                f"Die gewählten Werte werden auf {len(unique_paths)} markierte Dateien angewendet. "
                "Audio-, Untertitel-, DV/HDR- und Remux-Overrides bleiben unverändert."
            )
            note.setWordWrap(True)
            root.addWidget(note)
        controls = self.build_group(root, existing)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        root.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        template = dict(existing)
        self.persist_group(template, controls)
        encoder_value = template.get("encoder_override")
        rejected: list[str] = []
        applied = 0
        for path in unique_paths:
            ov = dict(owner._state.file_overrides.get(path) or {})
            if encoder_value is None:
                ov.pop("encoder_override", None)
            else:
                ov["encoder_override"] = dict(encoder_value)
            thread = owner._state.thread
            if thread and hasattr(thread, "update_override") and not thread.update_override(path, ov):
                rejected.append(path)
                continue
            owner._state.file_overrides[path] = ov
            getattr(owner._state, "preflight_rows_by_path", {}).pop(path, None)
            owner.update_queue_label(path)
            applied += 1

        if encoder_value is None:
            self._log(f"Encoder-/Skalierungs-Override entfernt: {applied} Datei(en)", "info")
        else:
            summary = self.summary_text(encoder_value, owner.default_codec)
            self._log(
                f"Encoder-/Skalierungs-Override gesetzt: {applied} Datei(en) -> {summary}",
                "info",
            )
        if rejected:
            QMessageBox.warning(
                owner,
                "Override teilweise abgelehnt",
                f"{len(rejected)} Datei(en) werden bereits verarbeitet oder sind abgeschlossen. "
                "Für diese Dateien wurde nichts geändert.",
            )

    @staticmethod
    def summary_text(raw: dict | None, default_codec: str) -> str:
        value = normalize_encoder_override(raw, default_codec=default_codec)
        if not value:
            return "Global / Profil"
        encoder = value["encoder"].upper()
        quality_label = {"cpu": "CRF", "nvenc": "CQ", "qsv": "Q", "amf": "QP"}[value["encoder"]]
        quality = value.get("quality")
        scale = MODE_TO_SCALE_LABEL.get(value.get("scale_mode") or "original", value.get("scale_mode") or "original")
        preset = value.get("preset") or "-"
        return f"{encoder} {quality_label} {quality if quality is not None else '-'} | {preset} | {scale}"

    def _global_snapshot(self) -> dict:
        owner = self.owner
        options = dict(owner._enc_settings.collect_enc_opts() or {})
        encoder = str(options.get("encoder") or "cpu").lower()
        if encoder not in {"cpu", "nvenc", "qsv", "amf"}:
            encoder = "cpu"
        quality = {
            "cpu": getattr(owner, "crf_spin").value(),
            "nvenc": options.get("cq", getattr(owner, "crf_spin").value()),
            "qsv": options.get("q", getattr(owner, "crf_spin").value()),
            "amf": options.get("qp", getattr(owner, "crf_spin").value()),
        }[encoder]
        preset = {
            "cpu": getattr(owner, "preset_combo").currentText(),
            "nvenc": options.get("preset", "p6"),
            "qsv": options.get("preset", "medium"),
            "amf": options.get("quality", "balanced"),
        }[encoder]
        allowed_keys = {
            "cpu": {"tune", "aq_mode", "aq_strength", "psy_rd", "psy_rdoq", "bf", "rc_lookahead"},
            "nvenc": {"preset", "cq", "bf", "bref_mode", "rc_lookahead", "lookahead_level", "multipass", "aq_strength", "spatial_aq", "temporal_aq"},
            "qsv": {"preset", "q", "lookahead_depth"},
            "amf": {"quality", "qp"},
        }[encoder]
        filtered = {key: options[key] for key in allowed_keys if key in options}
        filtered["encoder"] = encoder
        return {
            "codec": owner.default_codec,
            "encoder": encoder,
            "quality": int(quality),
            "preset": str(preset),
            "scale_mode": self._scale_mode_from_owner(),
            "encoder_options": filtered,
        }

    def _scale_mode_from_owner(self) -> str:
        from ..core.encoder_profile_override import SCALE_LABELS_TO_MODE

        text = str(self.owner.scale_combo.currentText() or "original")
        return SCALE_LABELS_TO_MODE.get(text, "original")

    def _common_override(self, paths: list[str]) -> dict:
        values = [
            dict(self.owner._state.file_overrides.get(path) or {}).get("encoder_override")
            for path in paths
        ]
        first = values[0] if values else None
        if first is not None and all(value == first for value in values[1:]):
            return {"encoder_override": dict(first)}
        return {}

    def _create_controls(self, parent: QWidget) -> dict:
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
        cpu = self._cpu_panel(parent)
        nvenc = self._nvenc_panel(parent)
        qsv = self._qsv_panel(parent)
        amf = self._amf_panel(parent)
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

    def _cpu_panel(self, parent: QWidget) -> dict:
        widget = QWidget(parent)
        grid = QGridLayout(widget)
        tune = QComboBox(widget); tune.addItems(["none", "grain", "animation", "ssim", "psnr"])
        aq_mode = QComboBox(widget); aq_mode.addItems(["0", "1", "2", "3"])
        aq_strength = QDoubleSpinBox(widget); aq_strength.setRange(0, 3); aq_strength.setSingleStep(0.1)
        psy_rd = QDoubleSpinBox(widget); psy_rd.setRange(0, 5); psy_rd.setSingleStep(0.1)
        psy_rdoq = QDoubleSpinBox(widget); psy_rdoq.setRange(0, 50); psy_rdoq.setSingleStep(0.5)
        bf = QSpinBox(widget); bf.setRange(0, 16)
        lookahead = QSpinBox(widget); lookahead.setRange(0, 250)
        labels = (("Tune", tune), ("AQ-Mode", aq_mode), ("AQ-Stärke", aq_strength), ("psy-rd", psy_rd), ("psy-rdoq", psy_rdoq), ("B-Frames", bf), ("Lookahead", lookahead))
        for idx, (label, control) in enumerate(labels):
            row, col = divmod(idx, 2)
            grid.addWidget(QLabel(label + ":"), row, col * 2)
            grid.addWidget(control, row, col * 2 + 1)
        return {"widget": widget, "tune": tune, "aq_mode": aq_mode, "aq_strength": aq_strength, "psy_rd": psy_rd, "psy_rdoq": psy_rdoq, "bf": bf, "rc_lookahead": lookahead}

    def _nvenc_panel(self, parent: QWidget) -> dict:
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
        fields = (("B-Frames", bf), ("B-Ref-Mode", bref), ("Lookahead", lookahead), ("Lookahead-Level", la_level), ("Multipass", multipass), ("AQ-Stärke", aq_strength))
        for idx, (label, control) in enumerate(fields):
            row, col = divmod(idx, 2)
            grid.addWidget(QLabel(label + ":"), row, col * 2)
            grid.addWidget(control, row, col * 2 + 1)
        grid.addWidget(spatial, 3, 0, 1, 2); grid.addWidget(temporal, 3, 2, 1, 2)
        return {"widget": widget, "bf": bf, "bref_mode": bref, "rc_lookahead": lookahead, "lookahead_level": la_level, "multipass": multipass, "aq_strength": aq_strength, "spatial_aq": spatial, "temporal_aq": temporal}

    def _qsv_panel(self, parent: QWidget) -> dict:
        widget = QWidget(parent)
        grid = QGridLayout(widget)
        lookahead = QSpinBox(widget); lookahead.setRange(1, 100)
        grid.addWidget(QLabel("Lookahead-Tiefe:"), 0, 0); grid.addWidget(lookahead, 0, 1)
        return {"widget": widget, "lookahead_depth": lookahead}

    def _amf_panel(self, parent: QWidget) -> dict:
        widget = QWidget(parent)
        grid = QGridLayout(widget)
        grid.addWidget(QLabel("Für AMF werden QP und Qualitätsmodus oben gesetzt."), 0, 0)
        return {"widget": widget}

    def _load_snapshot(self, controls: dict, snapshot: dict) -> None:
        encoder = str(snapshot.get("encoder") or "cpu")
        idx = controls["encoder"].findData(encoder)
        controls["encoder"].setCurrentIndex(max(0, idx))
        scale_label = MODE_TO_SCALE_LABEL.get(snapshot.get("scale_mode") or "original", "original")
        controls["scale"].setCurrentText(scale_label)
        controls["quality"].setValue(_safe_int(snapshot.get("quality"), 22))
        options = dict(snapshot.get("encoder_options") or {})
        preset = str(snapshot.get("preset") or self._default_preset(encoder))
        self._set_preset_items(controls["preset"], encoder, preset)

        # Backend-Optionen niemals zwischen CPU/NVENC/QSV vermischen. Mehrere
        # Schluessel existieren in verschiedenen Backends mit unterschiedlichen
        # Typen/Skalen (z.B. x265 aq_strength="1.0" vs. NVENC aq_strength=8).
        cpu_options = scoped_encoder_options(
            options, active_encoder=encoder, target_encoder="cpu"
        )
        nvenc_options = scoped_encoder_options(
            options, active_encoder=encoder, target_encoder="nvenc"
        )
        qsv_options = scoped_encoder_options(
            options, active_encoder=encoder, target_encoder="qsv"
        )
        self._load_cpu(controls["cpu"], cpu_options)
        self._load_nvenc(controls["nvenc"], nvenc_options)
        controls["qsv"]["lookahead_depth"].setValue(
            _safe_int(qsv_options.get("lookahead_depth"), 40)
        )

    def _load_cpu(self, controls: dict, options: dict) -> None:
        controls["tune"].setCurrentText(str(options.get("tune", "none")))
        controls["aq_mode"].setCurrentText(str(options.get("aq_mode", "2")))
        controls["aq_strength"].setValue(_safe_float(options.get("aq_strength"), 1.0))
        controls["psy_rd"].setValue(_safe_float(options.get("psy_rd"), 2.0))
        controls["psy_rdoq"].setValue(_safe_float(options.get("psy_rdoq"), 1.0))
        controls["bf"].setValue(_safe_int(options.get("bf"), 8))
        controls["rc_lookahead"].setValue(_safe_int(options.get("rc_lookahead"), 40))

    def _load_nvenc(self, controls: dict, options: dict) -> None:
        controls["bf"].setValue(_safe_int(options.get("bf"), 4))
        controls["bref_mode"].setCurrentText(str(options.get("bref_mode", "middle")))
        controls["rc_lookahead"].setValue(_safe_int(options.get("rc_lookahead"), 32))
        controls["lookahead_level"].setCurrentText(str(options.get("lookahead_level", "auto")))
        controls["multipass"].setCurrentText(str(options.get("multipass", "auto")))
        controls["aq_strength"].setValue(_safe_int(options.get("aq_strength"), 8))
        controls["spatial_aq"].setChecked(_safe_bool(options.get("spatial_aq", True), True))
        controls["temporal_aq"].setChecked(_safe_bool(options.get("temporal_aq", True), True))

    def _refresh_encoder_controls(self, controls: dict) -> None:
        encoder = str(controls["encoder"].currentData() or "cpu")
        index = {"cpu": 0, "nvenc": 1, "qsv": 2, "amf": 3}[encoder]
        controls["stack"].setCurrentIndex(index)
        current = controls["preset"].currentText()
        self._set_preset_items(controls["preset"], encoder, current)

    def _refresh_enabled(self, controls: dict) -> None:
        enabled = controls["mode"].currentData() == "custom"
        for key in ("encoder", "scale", "quality", "preset", "stack"):
            controls[key].setEnabled(enabled)

    def _set_preset_items(self, combo: QComboBox, encoder: str, preferred: str) -> None:
        items = {
            "cpu": _AV1_CPU_PRESETS if self.owner.default_codec == "av1" else _CPU_PRESETS,
            "nvenc": _NVENC_PRESETS,
            "qsv": _QSV_PRESETS,
            "amf": _AMF_PRESETS,
        }[encoder]
        combo.blockSignals(True)
        combo.clear(); combo.addItems(list(items))
        combo.setCurrentText(preferred if preferred in items else self._default_preset(encoder))
        combo.blockSignals(False)

    def _default_preset(self, encoder: str) -> str:
        return {"cpu": "6" if self.owner.default_codec == "av1" else "medium", "nvenc": "p6", "qsv": "medium", "amf": "balanced"}[encoder]

    def _collect_controls(self, controls: dict) -> dict:
        encoder = str(controls["encoder"].currentData() or "cpu")
        quality = int(controls["quality"].value())
        preset = controls["preset"].currentText()
        options: dict = {"encoder": encoder}
        if encoder == "cpu":
            c = controls["cpu"]
            options.update({"tune": c["tune"].currentText(), "aq_mode": c["aq_mode"].currentText(), "aq_strength": str(c["aq_strength"].value()), "psy_rd": str(c["psy_rd"].value()), "psy_rdoq": str(c["psy_rdoq"].value()), "bf": c["bf"].value(), "rc_lookahead": c["rc_lookahead"].value()})
        elif encoder == "nvenc":
            c = controls["nvenc"]
            options.update({"preset": preset, "cq": quality, "bf": c["bf"].value(), "bref_mode": c["bref_mode"].currentText(), "rc_lookahead": c["rc_lookahead"].value(), "lookahead_level": c["lookahead_level"].currentText(), "multipass": c["multipass"].currentText(), "aq_strength": c["aq_strength"].value(), "spatial_aq": c["spatial_aq"].isChecked(), "temporal_aq": c["temporal_aq"].isChecked()})
        elif encoder == "qsv":
            c = controls["qsv"]
            options.update({"preset": preset, "q": quality, "lookahead_depth": c["lookahead_depth"].value()})
        else:
            options.update({"quality": preset, "qp": quality})
        from ..core.encoder_profile_override import SCALE_LABELS_TO_MODE
        return {"codec": self.owner.default_codec, "encoder": encoder, "quality": quality, "preset": preset, "scale_mode": SCALE_LABELS_TO_MODE.get(controls["scale"].currentText(), "original"), "encoder_options": options}
