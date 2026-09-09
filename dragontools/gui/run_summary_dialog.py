# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from .ui_helpers import install_persistent_window_geometry


class RunSummaryDialog(QDialog):
    ACTION_CLOSE = "close"
    ACTION_REQUEUE_FAILED = "requeue_failed"

    _COLUMNS = ["Status", "Eingabe", "Ausgabe", "Zusatzdaten", "Hinweis", "Bericht"]

    def __init__(self, summary: dict, parent=None) -> None:
        super().__init__(parent)
        self._summary = dict(summary or {})
        self._rows = list(self._summary.get("rows") or [])
        self._action = self.ACTION_CLOSE

        self.setWindowTitle("Batch-Abschluss")
        self.resize(960, 560)

        layout = QVBoxLayout(self)
        self._summary_label = QLabel(self._summary_text(), self)
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

        self._table = QTableWidget(self)
        self._table.setColumnCount(len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setAlternatingRowColors(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self._open_report_btn = QPushButton("Fehlerbericht öffnen", self)
        self._retry_btn = QPushButton("Fehler erneut einreihen", self)
        self._close_btn = QPushButton("Schliessen", self)
        button_row.addWidget(self._open_report_btn)
        button_row.addWidget(self._retry_btn)
        button_row.addWidget(self._close_btn)
        layout.addLayout(button_row)

        self._open_report_btn.setEnabled(False)
        self._open_report_btn.clicked.connect(self._open_selected_error_report)
        self._retry_btn.setEnabled(bool(self._summary.get("has_failures")))
        self._retry_btn.clicked.connect(self._accept_retry)
        self._close_btn.clicked.connect(self.accept)

        self._fill_table()
        install_persistent_window_geometry(self, "run_summary_dialog")

    def action(self) -> str:
        return self._action

    def failed_inputs(self) -> list[str]:
        return list(self._summary.get("failed_inputs") or [])

    def _summary_text(self) -> str:
        total = int(self._summary.get("total") or 0)
        ok = int(self._summary.get("ok") or 0)
        errors = int(self._summary.get("errors") or 0)
        skipped = int(self._summary.get("skipped") or 0)
        move_ok = int(self._summary.get("move_ok") or 0)
        move_errors = int(self._summary.get("move_errors") or 0)
        archived = int(self._summary.get("archived") or 0)
        saved = self._summary.get("saved_label") or "0 B"
        before = self._summary.get("total_before_label") or "0 B"
        after = self._summary.get("total_after_label") or "0 B"
        text = (
            f"{total} Datei(en): {ok} OK, {errors} Fehler, {skipped} übersprungen | "
            f"Größe: {before} → {after} ({saved}) | "
            f"Verschoben: {move_ok} OK, {move_errors} Fehler | Archiviert: {archived}"
        )
        postprocess = str(self._summary.get("postprocess_summary_label") or "")
        if postprocess:
            text += f" | Zusatzdaten: {postprocess}"
        return text

    def _fill_table(self) -> None:
        rows = self._rows
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            report_path = str(row.get("error_report") or "")
            message = str(row.get("message") or "")
            report_name = Path(report_path).name if report_path else ""
            hint = message or ("Fehlerbericht erstellt" if report_path else "")
            values = [
                row.get("status_label", ""),
                row.get("input_name", ""),
                row.get("output_name", ""),
                row.get("extra_label", ""),
                hint,
                report_name,
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                tooltip = report_path if col_index == 5 and report_path else str(value)
                item.setToolTip(tooltip)
                if col_index == 0:
                    self._apply_status_color(item, row.get("status"))
                self._table.setItem(row_index, col_index, item)

        widths = [95, 245, 220, 210, 210, 160]
        for col_index, width in enumerate(widths):
            self._table.setColumnWidth(col_index, width)

    def _apply_status_color(self, item: QTableWidgetItem, status: str | None) -> None:
        if status == "error":
            item.setForeground(QColor("#a40000"))
        elif status == "skipped":
            item.setForeground(QColor("#8a6200"))
        else:
            item.setForeground(QColor("#0b6b2c"))

    def _accept_retry(self) -> None:
        self._action = self.ACTION_REQUEUE_FAILED
        self.accept()

    def _selected_error_report(self) -> str:
        current_row = self._table.currentRow()
        if current_row < 0 or current_row >= len(self._rows):
            return ""
        row = self._rows[current_row]
        return str(row.get("error_report") or "")

    def _on_selection_changed(self) -> None:
        report_path = self._selected_error_report()
        self._open_report_btn.setEnabled(bool(report_path and Path(report_path).exists()))

    def _open_selected_error_report(self) -> None:
        report_path = self._selected_error_report()
        if not report_path:
            return
        path = Path(report_path)
        if not path.exists():
            QMessageBox.warning(self, "Fehlerbericht", "Der Fehlerbericht wurde nicht gefunden.")
            self._on_selection_changed()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
