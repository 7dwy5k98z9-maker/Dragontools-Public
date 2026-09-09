# -*- coding: utf-8 -*-
"""GUI-Controller für Mediathek-Suche, CSV-Trefferexport und SQL-Konsole."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem


class MediaLibrarySearchController:
    def __init__(
        self,
        *,
        parent,
        view,
        service,
        presenter,
        get_db_path: Callable[[], str],
        refresh_stats: Callable[[], None],
    ) -> None:
        self._parent = parent
        self._view = view
        self._service = service
        self._presenter = presenter
        self._get_db_path = get_db_path
        self._refresh_stats = refresh_stats
        self._last_rows: list[dict[str, Any]] = []

    @property
    def last_rows(self) -> list[dict[str, Any]]:
        return self._last_rows

    @last_rows.setter
    def last_rows(self, rows: list[dict[str, Any]]) -> None:
        self._last_rows = rows

    def run_search(self) -> None:
        preset = str(self._view.search_option_combo.currentData() or "all")
        rows = self._service.search(
            self._get_db_path(),
            preset,
            self._view.search_text_edit.text(),
            scope=str(self._view.search_scope_combo.currentData() or "all"),
            media_type=str(self._view.search_type_combo.currentData() or "all"),
        )
        self._last_rows = rows
        table = self._view.search_table
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row in rows:
            idx = table.rowCount()
            table.insertRow(idx)
            for col, value in enumerate(self._presenter.search_row_values(row, preset)):
                item = QTableWidgetItem("" if value is None else str(value))
                if col in {3, 4, 5} and value is not None:
                    try:
                        item.setData(Qt.ItemDataRole.EditRole, int(value))
                    except (TypeError, ValueError):
                        pass
                table.setItem(idx, col, item)
        table.setSortingEnabled(True)
        self._view.search_result_label.setText(f"{len(rows)} Treffer")

    def export_search_csv(self) -> None:
        if not self._last_rows:
            QMessageBox.information(self._parent, "CSV-Export", "Es gibt noch keine Trefferliste zum Exportieren.")
            return
        file_name, _ = QFileDialog.getSaveFileName(
            self._parent,
            "Trefferliste als CSV speichern",
            str(Path.home() / "dragontools_mediathek_treffer.csv"),
            "CSV-Dateien (*.csv);;Alle Dateien (*)",
        )
        if not file_name:
            return
        try:
            target = self._service.export_search_csv(self._last_rows, file_name)
            QMessageBox.information(self._parent, "CSV-Export", f"Trefferliste exportiert:\n{target}")
        except Exception as exc:
            QMessageBox.critical(self._parent, "CSV-Export fehlgeschlagen", str(exc))

    def run_sql(self) -> None:
        sql = self._view.sql_edit.toPlainText().strip()
        if not sql:
            return
        if self._service.sql_is_mutating(sql):
            answer = QMessageBox.question(
                self._parent,
                "SQL ausführen",
                "Dieser Befehl ändert die DragonTools-Mediathek. Vorher wird eine Sicherung erstellt. Fortfahren?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            columns, rows, message = self._service.execute_sql(self._get_db_path(), sql)
        except Exception as exc:
            QMessageBox.critical(self._parent, "SQL-Fehler", str(exc))
            return
        table = self._view.sql_result_table
        table.setRowCount(0)
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        for row in rows:
            idx = table.rowCount()
            table.insertRow(idx)
            for col, value in enumerate(row):
                table.setItem(idx, col, QTableWidgetItem("" if value is None else str(value)))
        self._refresh_stats()
        QMessageBox.information(self._parent, "SQL", message)
