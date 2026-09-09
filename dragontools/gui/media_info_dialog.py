# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSettings, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
)

from ..core.media_analyzer import analyze_media
from ..core.settings import (
    APP_NAME, APP_ORG,
    SET_KEY_PRESERVE_DV, SET_KEY_PRESERVE_HDRPLUS,
    SET_KEY_AV1_PRESERVE_DV, SET_KEY_AV1_PRESERVE_HDRPLUS,
    settings_bool,
)
from ..core.mediainfo_details import (
    MediaInfoDisplayDetails,
    build_mediainfo_display_details,
)
from .media_info_text_builder import build_media_info_text as _build_media_info_text
from .ui_helpers import install_persistent_window_geometry, save_window_geometry



class _MediaInfoLoadThread(QThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        file_path: str,
        *,
        file_override: dict[str, Any],
        planned_target: str | None,
        subtitle_rules: dict[str, Any],
        codec: str,
        global_preserve_dv: bool,
        global_preserve_hdrplus: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.file_path = file_path
        self.file_override = dict(file_override)
        self.planned_target = planned_target
        self.subtitle_rules = dict(subtitle_rules)
        self.codec = codec
        self.global_preserve_dv = bool(global_preserve_dv)
        self.global_preserve_hdrplus = bool(global_preserve_hdrplus)

    def run(self) -> None:
        try:
            mi = analyze_media(self.file_path)
            rules_text = _build_media_info_text(
                self.file_path,
                mi=mi,
                file_override=self.file_override,
                planned_target=self.planned_target,
                subtitle_rules=self.subtitle_rules,
                codec=self.codec,
                global_preserve_dv=self.global_preserve_dv,
                global_preserve_hdrplus=self.global_preserve_hdrplus,
            )
            details = build_mediainfo_display_details(self.file_path, media_info=mi)
        except Exception as exc:
            self.failed.emit(
                f"Medieninfo konnte nicht gelesen werden.\n\nFehler:\n{exc}"
            )
            return
        self.loaded.emit({"details": details, "rules_text": rules_text})


class MediaInfoDialog(QDialog):
    def __init__(
        self,
        file_path: str,
        parent=None,
        *,
        file_override: dict | None = None,
        planned_target: str | None = None,
        subtitle_rules: dict | None = None,
        codec: str = "h265",
    ):
        super().__init__(parent)
        self.file_path = file_path
        self.file_override = dict(file_override or {})
        self.planned_target = planned_target
        self.subtitle_rules = dict(subtitle_rules or {})
        self.codec = codec
        self._load_thread: _MediaInfoLoadThread | None = None
        self._closed = False

        self.setWindowTitle(f"Medieninfo \u2013 {Path(file_path).name}")
        self.resize(900, 700)

        layout = QVBoxLayout(self)

        title = QLabel(f"<b>{Path(file_path).name}</b>")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title)

        path_lbl = QLabel(file_path)
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_lbl.setWordWrap(True)
        layout.addWidget(path_lbl)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.overview_table = _make_pair_table()
        self.video_table = _make_pair_table()
        self.audio_table = _make_track_table(
            ["Spur", "Sprache", "Codec", "Kanäle", "Bitrate", "Sampling", "Dauer", "Titel", "Flags"]
        )
        self.subtitle_table = _make_track_table(["Spur", "Sprache", "Format", "Titel", "Flags"])

        self.rules_text = QTextEdit()
        self.rules_text.setReadOnly(True)
        self.rules_text.setPlainText("Medieninfo wird geladen …")

        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setPlainText("MediaInfo-Rohdaten werden geladen …")

        self.tabs.addTab(self.overview_table, "Überblick")
        self.tabs.addTab(self.video_table, "Video")
        self.tabs.addTab(self.audio_table, "Audio")
        self.tabs.addTab(self.subtitle_table, "Untertitel")
        self.tabs.addTab(self.rules_text, "DragonTools")
        self.tabs.addTab(self.raw_text, "Rohdaten")

        _fill_pair_table(self.overview_table, [("Status", "Medieninfo wird geladen …")])

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        close_btn = QPushButton("Schlie\u00dfen")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
        install_persistent_window_geometry(self, "media_info_dialog")

        self._load_info()

    def _load_info(self) -> None:
        app = QApplication.instance()
        settings = QSettings(APP_ORG, APP_NAME)
        codec_norm = str(self.codec or "").strip().lower()
        dv_key = SET_KEY_AV1_PRESERVE_DV if codec_norm == "av1" else SET_KEY_PRESERVE_DV
        hdr_key = SET_KEY_AV1_PRESERVE_HDRPLUS if codec_norm == "av1" else SET_KEY_PRESERVE_HDRPLUS
        self._load_thread = _MediaInfoLoadThread(
            self.file_path,
            file_override=self.file_override,
            planned_target=self.planned_target,
            subtitle_rules=self.subtitle_rules,
            codec=self.codec,
            global_preserve_dv=settings_bool(settings, dv_key, True),
            global_preserve_hdrplus=settings_bool(settings, hdr_key, True),
            parent=app,
        )
        self._load_thread.loaded.connect(self._on_info_loaded)
        self._load_thread.failed.connect(self._on_info_failed)
        self._load_thread.finished.connect(self._on_load_finished)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.start()

    def _on_info_loaded(self, payload: object) -> None:
        if self._closed:
            return
        data = payload if isinstance(payload, dict) else {}
        details = data.get("details")
        rules_text = data.get("rules_text", "")
        if isinstance(details, MediaInfoDisplayDetails):
            self._apply_details(details)
        self.rules_text.setPlainText(str(rules_text or "Keine DragonTools-Preview verfügbar."))

    def _on_info_failed(self, message: str) -> None:
        if self._closed:
            return
        _fill_pair_table(self.overview_table, [("Fehler", message)])
        self.video_table.setRowCount(0)
        self.audio_table.setRowCount(0)
        self.subtitle_table.setRowCount(0)
        self.rules_text.setPlainText(message)
        self.raw_text.setPlainText("")

    def _apply_details(self, details: MediaInfoDisplayDetails) -> None:
        overview_rows = list(details.overview_rows)
        if details.warning:
            overview_rows.append(("Hinweis", details.warning))
        _fill_pair_table(self.overview_table, overview_rows)
        _fill_pair_table(self.video_table, details.video_rows or [("Video", "Keine Videodaten gefunden")])
        _fill_track_table(self.audio_table, details.audio_rows)
        _fill_track_table(self.subtitle_table, details.subtitle_rows)
        self.raw_text.setPlainText(details.raw_text or "Keine MediaInfo-Rohdaten verfügbar.")

    def _on_load_finished(self) -> None:
        self._load_thread = None

    def closeEvent(self, event) -> None:
        self._closed = True
        save_window_geometry(self, "media_info_dialog")
        super().closeEvent(event)


def _make_pair_table() -> QTableWidget:
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(["Eigenschaft", "Wert"])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    return table


def _make_track_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    for column in range(len(headers)):
        mode = QHeaderView.ResizeMode.Stretch if column in {len(headers) - 2, len(headers) - 1} else QHeaderView.ResizeMode.ResizeToContents
        header.setSectionResizeMode(column, mode)
    return table


def _fill_pair_table(table: QTableWidget, rows: list[tuple[str, str]]) -> None:
    table.setRowCount(len(rows))
    for row, (label, value) in enumerate(rows):
        table.setItem(row, 0, _item(label))
        table.setItem(row, 1, _item(value))
    table.resizeRowsToContents()


def _fill_track_table(table: QTableWidget, rows: list[dict[str, str]]) -> None:
    headers = [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())]
    if not rows:
        table.setRowCount(1)
        for column, header in enumerate(headers):
            table.setItem(0, column, _item("Keine Spuren gefunden" if column == 0 else ""))
        table.resizeRowsToContents()
        return

    table.setRowCount(len(rows))
    for row, data in enumerate(rows):
        for column, header in enumerate(headers):
            table.setItem(row, column, _item(data.get(header, "")))
    table.resizeRowsToContents()


def _item(value: str) -> QTableWidgetItem:
    item = QTableWidgetItem(str(value))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item
