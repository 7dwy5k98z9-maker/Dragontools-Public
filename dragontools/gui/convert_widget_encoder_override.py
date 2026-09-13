# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from ..core.encoder_profile_override import normalize_encoder_override
from .convert_widget_encoder_apply import apply_encoder_override
from .convert_widget_encoder_controls import EncoderOverrideControls
from .convert_widget_encoder_state import (
    common_encoder_override,
    encoder_override_summary,
    global_encoder_snapshot,
)


class EncoderOverrideDialogHelper:
    """Dialog facade for manual per-file encoder and scaling overrides."""

    def __init__(self, owner, *, guard_queue_edit_allowed, log) -> None:
        self.owner = owner
        self._guard_queue_edit_allowed = guard_queue_edit_allowed
        self._log = log
        self._controls = EncoderOverrideControls(owner.default_codec)

    def build_group(self, layout: QVBoxLayout, override: dict) -> dict:
        group = QGroupBox("Encoder / Skalierung (per Datei)")
        grid = QGridLayout(group)
        controls = self._controls.create(group)
        manual = normalize_encoder_override(
            override.get("encoder_override"),
            default_codec=self.owner.default_codec,
        )
        snapshot = manual or global_encoder_snapshot(self.owner)

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
        self._controls.load_snapshot(controls, snapshot)
        controls["encoder"].currentIndexChanged.connect(
            lambda _idx: self._controls.refresh_encoder(controls)
        )
        controls["mode"].currentIndexChanged.connect(
            lambda _idx: self._controls.refresh_enabled(controls)
        )
        self._controls.refresh_encoder(controls)
        self._controls.refresh_enabled(controls)
        return controls

    def persist_group(self, override: dict, controls: dict) -> None:
        if controls["mode"].currentData() != "custom":
            override.pop("encoder_override", None)
            return
        override["encoder_override"] = self._controls.collect(controls)

    def edit_paths(self, paths: Iterable[str]) -> None:
        unique_paths = list(dict.fromkeys(str(path) for path in paths if str(path or "")))
        if not unique_paths or not self._guard_queue_edit_allowed("Encoder-/Skalierungs-Override ändern"):
            return

        existing = common_encoder_override(self.owner, unique_paths)
        dialog = self._build_dialog(unique_paths)
        root = QVBoxLayout(dialog)
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
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        template = dict(existing)
        self.persist_group(template, controls)
        encoder_value = template.get("encoder_override")
        result = apply_encoder_override(self.owner, unique_paths, encoder_value)
        self._log_apply_result(result.applied, encoder_value)
        if result.rejected:
            QMessageBox.warning(
                self.owner,
                "Override teilweise abgelehnt",
                f"{len(result.rejected)} Datei(en) werden bereits verarbeitet oder sind abgeschlossen. "
                "Für diese Dateien wurde nichts geändert.",
            )

    def _build_dialog(self, paths: list[str]) -> QDialog:
        dialog = QDialog(self.owner)
        dialog.setWindowTitle(
            f"Encoder / Skalierung: {Path(paths[0]).name}"
            if len(paths) == 1
            else f"Encoder / Skalierung für {len(paths)} Dateien"
        )
        dialog.resize(720, 520)
        return dialog

    def _log_apply_result(self, applied: int, encoder_value: dict | None) -> None:
        if encoder_value is None:
            self._log(f"Encoder-/Skalierungs-Override entfernt: {applied} Datei(en)", "info")
            return
        summary = self.summary_text(encoder_value, self.owner.default_codec)
        self._log(
            f"Encoder-/Skalierungs-Override gesetzt: {applied} Datei(en) -> {summary}",
            "info",
        )

    @staticmethod
    def summary_text(raw: dict | None, default_codec: str) -> str:
        return encoder_override_summary(raw, default_codec)
