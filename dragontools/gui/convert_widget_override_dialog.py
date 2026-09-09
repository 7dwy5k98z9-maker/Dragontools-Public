# -*- coding: utf-8 -*-
"""File-override dialog orchestration facade used by ConvertWidget."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QMessageBox, QScrollArea, QVBoxLayout, QWidget,
)

from .convert_override_groups import ConvertOverrideGroupBuilderMixin
from .convert_override_lifecycle import _OverrideAnalyzeThread, _OverrideDialog
from .convert_override_state import _audio_meta_text, _lang_label, _load_override_state
from .convert_override_tracks import (
    _build_audio_rows, _build_subtitle_rows, _collect_audio_tracks,
    _collect_subtitle_tracks,
)
from .convert_widget_encoder_override import EncoderOverrideDialogHelper
from .ui_helpers import install_persistent_window_geometry


class ConvertWidgetOverrideDialogHelper(ConvertOverrideGroupBuilderMixin):
    def __init__(self, owner):
        self.owner = owner
        self._encoder_override = EncoderOverrideDialogHelper(
            owner,
            guard_queue_edit_allowed=owner._guard_queue_edit_allowed,
            log=owner._log,
        )

    def edit_encoder_override(self, paths) -> None:
        """Öffnet den schlanken Encoder-/Skalierungsdialog für eine Auswahl."""
        self._encoder_override.edit_paths(paths)

    def edit_override(self, path: str) -> None:
        """Öffnet den Override-Dialog und persistiert die Einstellungen."""
        ow = self.owner
        state = ow._state
        ov = dict(state.file_overrides.get(path) or {})

        dlg = _OverrideDialog(ow)
        dlg.setWindowTitle(f"Einstellungen: {Path(path).name}")
        dlg.setMinimumWidth(560)
        dlg.resize(760, 640)
        dlg.setMaximumHeight(760)
        install_persistent_window_geometry(dlg, "file_override_dialog")
        dlg._override_loader = None

        v = QVBoxLayout(dlg)
        scroll = QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(8, 8, 8, 8)
        cv.setSpacing(10)
        scroll.setWidget(content)
        v.addWidget(scroll)

        _ov_state = _load_override_state(ov)
        old_audio_action = _ov_state["old_audio_action"]
        audio_mode_value = _ov_state["audio_mode_value"]
        audio_track_map = _ov_state["audio_track_map"]
        old_burn_mode = _ov_state["old_burn_mode"]
        old_burn_stream_index = _ov_state["old_burn_stream_index"]
        subtitle_mode_value = _ov_state["subtitle_mode_value"]
        subtitle_track_map = _ov_state["subtitle_track_map"]
        processing_mode_value = _ov_state["processing_mode_value"]
        audio_drc_state = _ov_state["audio_drc"]
        audio_loudnorm_state = _ov_state["audio_loudnorm"]

        processing_combo = self._build_processing_group(cv, processing_mode_value)
        encoder_override_controls = self._encoder_override.build_group(cv, ov)
        ac, audio_status, audio_panel, apl, audio_rows = self._build_audio_group(
            cv, audio_mode_value
        )
        (
            drc_mode_combo,
            drc_scale_spin,
            loudnorm_mode_combo,
            loudnorm_i_spin,
        ) = self._build_audio_processing_group(cv, audio_drc_state, audio_loudnorm_state)
        bc, subtitle_status, subtitle_panel, spl, subtitle_rows, imax_cb = self._build_subtitle_group(
            cv, subtitle_mode_value, ov
        )
        dv_combo, hdp_combo = self._build_hdr_policy_group(cv, ov)
        cv.addStretch(1)

        def _refresh_panels():
            audio_panel.setVisible(ac.currentData() == "custom")
            subtitle_panel.setVisible(bc.currentData() == "custom")

        ac.currentTextChanged.connect(_refresh_panels)
        bc.currentTextChanged.connect(_refresh_panels)
        _refresh_panels()

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = bb.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn is not None:
            ok_btn.setEnabled(False)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)

        dialog_alive = {"value": True}

        def _finish_dialog_load(audio_streams, subtitle_streams, warning_text=None):
            if not dialog_alive["value"]:
                return
            _build_audio_rows(
                apl, audio_streams, audio_track_map, old_audio_action, audio_rows
            )
            _build_subtitle_rows(
                spl, subtitle_streams, subtitle_track_map,
                old_burn_mode, old_burn_stream_index, subtitle_rows,
            )
            audio_status.setText(
                warning_text or ("Keine Audiospuren erkannt." if not audio_streams else "")
            )
            subtitle_status.setText(
                warning_text or ("Keine Untertitel erkannt." if not subtitle_streams else "")
            )
            audio_status.setVisible(bool(audio_status.text()))
            subtitle_status.setVisible(bool(subtitle_status.text()))
            if ok_btn is not None:
                ok_btn.setEnabled(True)
            _refresh_panels()

        def _on_loaded(_mi, audio_streams, subtitle_streams):
            _finish_dialog_load(audio_streams, subtitle_streams)

        def _on_failed(error_text: str):
            if not dialog_alive["value"]:
                return
            ow.log_message(
                f"⚠️ Analyse für Override-Dialog fehlgeschlagen: {Path(path).name}",
                "warn",
            )
            ow.log_message(error_text, "error")
            _finish_dialog_load([], [], "Mediendaten konnten nicht geladen werden.")

        loader = _OverrideAnalyzeThread(path, ow.tools, dlg)
        dlg._override_loader = loader
        loader.loaded.connect(_on_loaded)
        loader.failed.connect(_on_failed)
        def _cleanup_loader():
            if getattr(dlg, "_override_loader", None) is loader:
                dlg._override_loader = None
            loader.deleteLater()

        loader.finished.connect(_cleanup_loader)
        dlg.finished.connect(lambda *_: dialog_alive.__setitem__("value", False))
        QTimer.singleShot(0, loader.start)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        controls = {
            "processing_combo": processing_combo,
            "encoder_override": encoder_override_controls,
            "audio_mode_combo": ac,
            "subtitle_mode_combo": bc,
            "audio_rows": audio_rows,
            "subtitle_rows": subtitle_rows,
            "drc_mode_combo": drc_mode_combo,
            "drc_scale_spin": drc_scale_spin,
            "loudnorm_mode_combo": loudnorm_mode_combo,
            "loudnorm_i_spin": loudnorm_i_spin,
            "imax_cb": imax_cb,
            "dv_combo": dv_combo,
            "hdrplus_combo": hdp_combo,
        }
        self._persist_override_result(path, state, ov, controls)

    def _persist_override_result(self, path: str, state, ov: dict, controls: dict) -> None:
        """Übernimmt validierte Dialogwerte in den Datei-Override-Zustand."""
        ow = self.owner
        processing_combo = controls["processing_combo"]
        ac = controls["audio_mode_combo"]
        bc = controls["subtitle_mode_combo"]
        audio_rows = controls["audio_rows"]
        subtitle_rows = controls["subtitle_rows"]
        drc_mode_combo = controls["drc_mode_combo"]
        drc_scale_spin = controls["drc_scale_spin"]
        loudnorm_mode_combo = controls["loudnorm_mode_combo"]
        loudnorm_i_spin = controls["loudnorm_i_spin"]
        imax_cb = controls["imax_cb"]
        dv_combo = controls["dv_combo"]
        hdp_combo = controls["hdrplus_combo"]

        processing_mode = processing_combo.currentData()
        if processing_mode == "strip_only":
            ov["processing_mode"] = "strip_only"
        else:
            ov.pop("processing_mode", None)
        ov.pop("strip_only", None)

        self._encoder_override.persist_group(ov, controls["encoder_override"])

        ov["audio_mode"] = ac.currentData()
        ov["subtitle_mode"] = bc.currentData()

        if ac.currentData() == "custom":
            ov["audio_tracks"] = _collect_audio_tracks(audio_rows)
        else:
            ov.pop("audio_tracks", None)
        ov.pop("audio_action", None)

        drc_mode = drc_mode_combo.currentData()
        if drc_mode == "inherit":
            ov.pop("audio_drc", None)
        else:
            ov["audio_drc"] = {
                "mode": str(drc_mode),
                "scale": round(float(drc_scale_spin.value()), 1),
            }

        loudnorm_mode = loudnorm_mode_combo.currentData()
        if loudnorm_mode == "inherit":
            ov.pop("audio_loudnorm", None)
        else:
            ov["audio_loudnorm"] = {
                "mode": str(loudnorm_mode),
                "i": round(float(loudnorm_i_spin.value()), 1),
            }

        if bc.currentData() == "custom":
            ov["subtitle_tracks"] = _collect_subtitle_tracks(subtitle_rows)
        else:
            ov.pop("subtitle_tracks", None)
        ov.pop("burn_mode", None)
        ov.pop("burn_stream_index", None)

        ov["imax"] = imax_cb.isChecked()

        dv_val = dv_combo.currentData()
        hdp_val = hdp_combo.currentData()
        if dv_val is None:
            ov.pop("preserve_dv", None)
        else:
            ov["preserve_dv"] = dv_val
        if hdp_val is None:
            ov.pop("preserve_hdrplus", None)
        else:
            ov["preserve_hdrplus"] = hdp_val

        thread = state.thread
        if thread and hasattr(thread, "update_override"):
            ok = thread.update_override(path, ov)
            if not ok:
                QMessageBox.warning(
                    ow,
                    "Override abgelehnt",
                    f"'{Path(path).name}' wird gerade verarbeitet\n"
                    "oder ist bereits abgeschlossen.\n\n"
                    "Override kann nur für noch nicht gestartete Dateien gesetzt werden.",
                )
                return

        state.file_overrides[path] = ov
        ow.update_queue_label(path)

__all__ = ["ConvertWidgetOverrideDialogHelper"]
