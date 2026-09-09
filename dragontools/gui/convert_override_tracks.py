# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QComboBox, QLabel, QSpinBox

from .convert_override_state import _audio_meta_text, _lang_label

def _clear_layout_widgets(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout_widgets(child_layout)


def _build_audio_rows(
    layout, audio_streams: list, audio_track_map: dict,
    old_audio_action: str, audio_rows: list,
) -> None:
    _clear_layout_widgets(layout)
    audio_rows.clear()
    layout.addWidget(QLabel("Spur"), 0, 0)
    layout.addWidget(QLabel("Aktion"), 0, 1)
    layout.addWidget(QLabel("Codec"), 0, 2)
    layout.addWidget(QLabel("Bitrate"), 0, 3)

    for row_idx, stream in enumerate(audio_streams, start=1):
        stream_index = int(getattr(stream, "index", row_idx - 1))
        existing = audio_track_map.get(stream_index, {})
        if not existing and old_audio_action != "auto":
            existing = {
                "index": stream_index,
                "mode": "custom",
                "codec": old_audio_action,
                "bitrate": getattr(stream, "bitrate", None),
            }
        label = QLabel(f"#{stream_index}  {_audio_meta_text(stream)}")
        mode = QComboBox()
        mode.addItem("auto", "auto")
        mode.addItem("benutzerdefiniert", "custom")
        mode.addItem("weglassen", "drop")
        current_mode = existing.get("mode", "auto")
        if current_mode == "drop":
            mode.setCurrentIndex(2)
        elif current_mode == "custom":
            mode.setCurrentIndex(1)
        else:
            mode.setCurrentIndex(0)
        codec = QComboBox()
        codec.addItems(["copy", "aac", "ac3", "eac3"])
        codec.setCurrentText(str(existing.get("codec", "eac3")))
        bitrate = QSpinBox()
        bitrate.setRange(0, 5000)
        bitrate.setSuffix(" kbps")
        bitrate_value = existing.get("bitrate")
        try:
            bitrate.setValue(
                max(0, int((int(bitrate_value) if bitrate_value else 0) / 1000))
            )
        except Exception:
            bitrate.setValue(0)
        layout.addWidget(label, row_idx, 0)
        layout.addWidget(mode, row_idx, 1)
        layout.addWidget(codec, row_idx, 2)
        layout.addWidget(bitrate, row_idx, 3)

        def _refresh_audio_row(_=None, m=mode, c=codec, b=bitrate):
            active = m.currentData() == "custom"
            c.setEnabled(active)
            b.setEnabled(active)

        mode.currentTextChanged.connect(_refresh_audio_row)
        _refresh_audio_row()
        audio_rows.append({
            "index": stream_index,
            "mode": mode,
            "codec": codec,
            "bitrate": bitrate,
        })


def _build_subtitle_rows(
    layout, subtitle_streams: list, subtitle_track_map: dict,
    old_burn_mode: str, old_burn_stream_index, subtitle_rows: list,
) -> None:
    _clear_layout_widgets(layout)
    subtitle_rows.clear()
    layout.addWidget(QLabel("Spur"), 0, 0)
    layout.addWidget(QLabel("Behalten"), 0, 1)
    layout.addWidget(QLabel("Burn-In"), 0, 2)

    def _ensure_single_burn(changed=None):
        if changed is None or not changed.isChecked():
            return
        for row in subtitle_rows:
            if row["burn"] is changed:
                row["keep"].blockSignals(True)
                row["keep"].setChecked(False)
                row["keep"].blockSignals(False)
            elif row["burn"].isChecked():
                row["burn"].blockSignals(True)
                row["burn"].setChecked(False)
                row["burn"].blockSignals(False)

    def _ensure_keep_not_burn(keep_cb=None):
        if keep_cb is None or not keep_cb.isChecked():
            return
        for row in subtitle_rows:
            if row["keep"] is keep_cb and row["burn"].isChecked():
                row["keep"].blockSignals(True)
                row["keep"].setChecked(False)
                row["keep"].blockSignals(False)
                return

    for row_idx, stream in enumerate(subtitle_streams, start=1):
        idx = int(getattr(stream, "index", row_idx - 1))
        existing = subtitle_track_map.get(idx, {})
        if not existing and old_burn_mode == "selected" and old_burn_stream_index == idx:
            existing = {"index": idx, "keep": False, "burn_in": True}
        label = QLabel(
            f"#{idx}  {_lang_label(getattr(stream, 'language', None))} | "
            f"{getattr(stream, 'codec', '—')} | "
            f"Forced: {'Ja' if getattr(stream, 'forced', False) else 'Nein'}"
        )
        keep_cb = QCheckBox()
        keep_cb.setChecked(bool(existing.get("keep", False)))
        burn_cb = QCheckBox()
        burn_cb.setChecked(bool(existing.get("burn_in", False)))
        layout.addWidget(label, row_idx, 0)
        layout.addWidget(keep_cb, row_idx, 1)
        layout.addWidget(burn_cb, row_idx, 2)
        subtitle_rows.append({"index": idx, "keep": keep_cb, "burn": burn_cb})

    for row in subtitle_rows:
        row["burn"].toggled.connect(
            lambda checked, cb=row["burn"]: _ensure_single_burn(cb) if checked else None
        )
        row["keep"].toggled.connect(
            lambda checked, cb=row["keep"]: _ensure_keep_not_burn(cb) if checked else None
        )


def _collect_audio_tracks(audio_rows: list) -> list:
    audio_tracks = []
    for row in audio_rows:
        current_mode = row["mode"].currentData()
        entry = {
            "index": row["index"],
            "mode": current_mode,
        }
        if current_mode == "custom":
            entry["codec"] = row["codec"].currentText()
            entry["bitrate"] = (
                int(row["bitrate"].value()) * 1000
                if row["bitrate"].value() > 0
                else None
            )
        audio_tracks.append(entry)
    return audio_tracks


def _collect_subtitle_tracks(subtitle_rows: list) -> list:
    return [
        {
            "index": row["index"],
            "keep": row["keep"].isChecked(),
            "burn_in": row["burn"].isChecked(),
        }
        for row in subtitle_rows
    ]
