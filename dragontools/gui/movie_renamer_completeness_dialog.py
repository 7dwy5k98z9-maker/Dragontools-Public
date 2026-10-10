"""Recognized-season/series selection and an exportable completeness table."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                            QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem,
                            QHeaderView, QFileDialog, QMessageBox)

from ..core.renamer_completeness_export import REPORT_HEADERS, result_cells, write_completeness_csv
from .movie_renamer_completeness_runtime import CompletenessDialogRuntimeMixin


class MovieRenamerCompletenessDialog(CompletenessDialogRuntimeMixin, QDialog):
    def __init__(self, targets, config, parent=None, *, whole_series=False):
        super().__init__(parent)
        self.config = config
        self.worker = None
        self.closed = False
        self.report = ()
        self.setWindowTitle("Serie prüfen" if whole_series else "Staffel prüfen")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(1060, 720)
        self._build(targets)

    def _build(self, targets):
        root = QVBoxLayout(self)
        hint = QLabel("Auswahl aus den erkannten Zuordnungen der aktuellen Renamer-Liste. "
                      "Verglichen werden alle Folgen der jeweiligen Quelle, einschließlich Specials "
                      "und angekündigter Folgen. Unterschiedliche Quellen bleiben getrennt.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.choices = QListWidget()
        self.choices.setMaximumHeight(210)
        for index, target in enumerate(targets):
            item = QListWidgetItem(target.label)
            item.setData(Qt.ItemDataRole.UserRole, target)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if index == 0 else Qt.CheckState.Unchecked)
            self.choices.addItem(item)
        root.addWidget(self.choices)
        controls = QHBoxLayout()
        self.select_all_btn = QPushButton("Alle auswählen")
        self.select_none_btn = QPushButton("Keine auswählen")
        self.check_btn = QPushButton("Prüfen")
        self.select_all_btn.clicked.connect(lambda: self.select_all(True))
        self.select_none_btn.clicked.connect(lambda: self.select_all(False))
        self.check_btn.clicked.connect(self.start_check)
        controls.addWidget(self.select_all_btn)
        controls.addWidget(self.select_none_btn)
        controls.addStretch()
        controls.addWidget(self.check_btn)
        root.addLayout(controls)
        self.results_table = QTableWidget(0, len(REPORT_HEADERS))
        self.results_table.setHorizontalHeaderLabels(REPORT_HEADERS)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((190, 85, 70, 125, 120, 95, 100, 170, 150, 260)):
            self.results_table.setColumnWidth(column, width)
        root.addWidget(self.results_table, 1)
        self.status = QLabel("Staffel(n)/Serie(n) auswählen und auf Prüfen klicken.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        footer = QHBoxLayout()
        self.export_btn = QPushButton("CSV exportieren")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_report)
        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(self.reject)
        footer.addWidget(self.export_btn)
        footer.addStretch()
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def select_all(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for index in range(self.choices.count()):
            self.choices.item(index).setCheckState(state)

    def selected_targets(self):
        return tuple(self.choices.item(index).data(Qt.ItemDataRole.UserRole)
                     for index in range(self.choices.count())
                     if self.choices.item(index).checkState() == Qt.CheckState.Checked)

    def set_busy(self, busy):
        for control in (self.choices, self.check_btn, self.select_all_btn, self.select_none_btn):
            control.setEnabled(not busy)
        self.export_btn.setEnabled(not busy and bool(self.report))

    def present_report(self):
        self.results_table.setRowCount(len(self.report))
        for row, result in enumerate(self.report):
            for column, value in enumerate(result_cells(result)):
                item = QTableWidgetItem(value)
                item.setToolTip(result.note if column == 4 and result.note else value)
                self.results_table.setItem(row, column, item)

    def export_report(self):
        if not self.report or self.worker is not None:
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Vollständigkeit exportieren",
                                                  "Serien-Vollstaendigkeit.csv", "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            write_completeness_csv(self.report, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export fehlgeschlagen", str(exc))
        else:
            self.status.setText(f"Tabelle exportiert: {path}")
