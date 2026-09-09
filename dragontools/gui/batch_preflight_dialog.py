# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from ..core.batch_preflight import (
    default_batch_preflight_report_path,
    format_batch_preflight_report,
    split_problem_rows,
)
from .ui_helpers import install_persistent_window_geometry


class BatchPreflightDialog(QDialog):
    ACTION_START = "start"
    ACTION_SKIP_PROBLEMS = "skip_problems"
    ACTION_CANCEL = "cancel"

    _COLUMNS = [
        "Status",
        "Datei",
        "Video",
        "HDR/DV",
        "Audio",
        "Untertitel",
        "Ziel",
        "Pipeline",
        "Profil",
        "Hinweise",
    ]

    def __init__(
        self,
        rows: list[dict],
        parent=None,
        *,
        title: str | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self._rows = list(rows)
        self._action = self.ACTION_CANCEL
        self._read_only = read_only

        self.setWindowTitle(title or "Batch-Preflight")
        self.resize(1180, 680)

        layout = QVBoxLayout(self)
        self._summary_label = QLabel(self._summary_text())
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
        self._table.itemSelectionChanged.connect(self._update_detail_from_selection)
        layout.addWidget(self._table, 1)

        self._detail = QTextEdit(self)
        self._detail.setReadOnly(True)
        self._detail.setMinimumHeight(120)
        layout.addWidget(self._detail)

        button_layout = QHBoxLayout()
        self._save_btn = QPushButton("Bericht speichern", self)
        button_layout.addWidget(self._save_btn)
        button_layout.addStretch(1)
        self._skip_btn = QPushButton("Problemdateien überspringen", self)
        self._start_btn = QPushButton("Starten", self)
        self._cancel_btn = QPushButton("Abbrechen", self)
        button_layout.addWidget(self._skip_btn)
        button_layout.addWidget(self._start_btn)
        button_layout.addWidget(self._cancel_btn)
        layout.addLayout(button_layout)

        self._save_btn.clicked.connect(self._save_report)
        self._skip_btn.clicked.connect(self._accept_skip_problems)
        self._start_btn.clicked.connect(self._accept_start)
        self._cancel_btn.clicked.connect(self.reject)

        ok_rows, problem_rows = split_problem_rows(self._rows)
        self._skip_btn.setEnabled(bool(ok_rows and problem_rows))
        if self._read_only:
            self._skip_btn.hide()
            self._cancel_btn.hide()
            self._start_btn.setText("Schliessen")

        self._fill_table()
        if self._rows:
            self._table.selectRow(0)
        install_persistent_window_geometry(self, "batch_preflight_dialog")

    def action(self) -> str:
        return self._action

    def accepted_files(self) -> list[str]:
        if self._action == self.ACTION_SKIP_PROBLEMS:
            return [row["path"] for row in self._rows if row.get("severity") == "ok"]
        if self._action == self.ACTION_START:
            return [row["path"] for row in self._rows]
        return []

    def skipped_files(self) -> list[str]:
        if self._action != self.ACTION_SKIP_PROBLEMS:
            return []
        return [row["path"] for row in self._rows if row.get("severity") != "ok"]

    def reject(self) -> None:
        self._action = self.ACTION_CANCEL
        super().reject()

    def _summary_text(self) -> str:
        total = len(self._rows)
        ok = sum(1 for row in self._rows if row.get("severity") == "ok")
        warn = sum(1 for row in self._rows if row.get("severity") == "warn")
        error = sum(1 for row in self._rows if row.get("severity") == "error")
        return f"{total} Datei(en): {ok} OK, {warn} Warnung(en), {error} Fehler"

    def _fill_table(self) -> None:
        self._table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            values = [
                row.get("status", ""),
                row.get("name", ""),
                row.get("video", ""),
                row.get("hdr", ""),
                row.get("audio", ""),
                row.get("subtitles", ""),
                row.get("target", ""),
                row.get("pipeline", ""),
                row.get("profile", ""),
                self._warning_cell_text(row),
            ]
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                item.setData(Qt.ItemDataRole.UserRole, row_index)
                if col_index == 0:
                    self._apply_status_color(item, row.get("severity"))
                self._table.setItem(row_index, col_index, item)

        widths = [90, 240, 140, 120, 240, 140, 210, 150, 130, 240]
        for col_index, width in enumerate(widths):
            self._table.setColumnWidth(col_index, width)

    def _apply_status_color(self, item: QTableWidgetItem, severity: str | None) -> None:
        if severity == "error":
            item.setForeground(QColor("#a40000"))
        elif severity == "warn":
            item.setForeground(QColor("#9a6500"))
        else:
            item.setForeground(QColor("#0b6b2c"))

    def _warning_cell_text(self, row: dict) -> str:
        warnings = [str(w) for w in row.get("warnings") or [] if w]
        if not warnings:
            return "-"
        first = warnings[0]
        remaining = len(warnings) - 1
        return first if remaining <= 0 else f"{first} (+{remaining})"

    def _selected_row(self) -> dict | None:
        selected = self._table.selectedItems()
        if not selected:
            return None
        index = selected[0].data(Qt.ItemDataRole.UserRole)
        try:
            return self._rows[int(index)]
        except (TypeError, ValueError, IndexError):
            return None

    def _update_detail_from_selection(self) -> None:
        row = self._selected_row()
        if row is None:
            self._detail.clear()
            return

        warnings = [str(w) for w in row.get("warnings") or [] if w]
        reasons = [str(v) for v in row.get("decision_reasons") or [] if v]
        lines = [
            f"Datei: {row.get('path', '')}",
            f"Pipeline: {row.get('pipeline', '-')}",
            f"Profil: {row.get('profile', '-')}",
            f"Analyse: {row.get('analysis_source', '-')}",
            "",
            "Entscheidungen:",
        ]
        if reasons:
            lines.extend(f"- {reason}" for reason in reasons)
        else:
            lines.append("- Keine Details verfügbar")
        lines.extend([
            "",
            "Hinweise:",
        ])
        if warnings:
            lines.extend(f"- {warning}" for warning in warnings)
        else:
            lines.append("- Keine")
        self._detail.setPlainText("\n".join(lines))

    def _accept_start(self) -> None:
        self._action = self.ACTION_START
        self.accept()

    def _accept_skip_problems(self) -> None:
        accepted = [row for row in self._rows if row.get("severity") == "ok"]
        if not accepted:
            QMessageBox.warning(self, "Keine OK-Dateien", "Es gibt keine Datei ohne Warnung oder Fehler.")
            return
        self._action = self.ACTION_SKIP_PROBLEMS
        self.accept()

    def _save_report(self) -> None:
        suggested = str(default_batch_preflight_report_path())
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Regel-/Profil-Simulator-Bericht speichern",
            suggested,
            "Textdateien (*.txt);;Alle Dateien (*)",
        )
        if not path:
            return
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(format_batch_preflight_report(self._rows), encoding="utf-8")
        except Exception as exc:
            QMessageBox.critical(self, "Bericht konnte nicht gespeichert werden", str(exc))
            return
        QMessageBox.information(self, "Bericht gespeichert", f"Regel-/Profil-Simulator-Bericht wurde gespeichert:\n{target}")
