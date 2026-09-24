# -*- coding: utf-8 -*-
"""Review dialog for Patch-J bitmap subtitle OCR drafts."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.bitmap_subtitle_ocr import finalize_ocr_report, load_ocr_report


class BitmapSubtitleOcrReviewDialog(QDialog):
    def __init__(self, report_path: str, parent=None, *, expected_media=None) -> None:
        super().__init__(parent)
        self.report_path = str(report_path)
        self.report = load_ocr_report(report_path)
        self.expected_media = expected_media
        self.final_path = ""
        self.setWindowTitle("OCR-Untertitel prüfen")
        self.resize(1050, 650)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        cues = list(self.report.get("cues") or [])
        uncertain = sum(1 for cue in cues if bool(cue.get("uncertain")))
        average = float(self.report.get("average_confidence") or 0.0) * 100.0
        language = str(self.report.get("detected_language") or "und")
        info = QLabel(
            f"{len(cues)} OCR-Cues · {uncertain} unsicher · Ø {average:.1f}% · Sprache: {language}. "
            "Bitte besonders die als unsicher markierten Zeilen prüfen. Die originale Bilduntertitelspur bleibt erhalten."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(len(cues), 5)
        self.table.setHorizontalHeaderLabels(["#", "Start", "Ende", "Konfidenz", "OCR-Text"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.table.horizontalHeader()
        for column in range(4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for row, cue in enumerate(cues):
            self._readonly_item(row, 0, str(row + 1))
            self._readonly_item(row, 1, _clock(float(cue.get("start_s") or 0.0)))
            self._readonly_item(row, 2, _clock(float(cue.get("end_s") or 0.0)))
            confidence = float(cue.get("confidence") or 0.0)
            marker = " ⚠" if bool(cue.get("uncertain")) else ""
            self._readonly_item(row, 3, f"{confidence * 100:.1f}%{marker}")
            text_item = QTableWidgetItem(str(cue.get("text") or ""))
            text_item.setToolTip("Bearbeitbar. Leer lassen, um diesen Cue beim finalen SRT zu entfernen.")
            self.table.setItem(row, 4, text_item)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if save is not None:
            save.setText("Bestätigen && SRT speichern")
        if cancel is not None:
            cancel.setText("Später prüfen")
        buttons.accepted.connect(self._finalize)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _readonly_item(self, row: int, column: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, column, item)

    def _finalize(self) -> None:
        edited = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 4)
            edited.append(item.text() if item is not None else "")
        try:
            final = finalize_ocr_report(
                self.report_path, edited, expected_media=self.expected_media,
                expected_report=self.report,
            )
        except Exception as exc:
            QMessageBox.critical(self, "OCR-Untertitel", f"SRT konnte nicht gespeichert werden:\n{exc}")
            return
        self.final_path = str(final)
        self.accept()


def _clock(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000.0)))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


__all__ = ["BitmapSubtitleOcrReviewDialog"]
