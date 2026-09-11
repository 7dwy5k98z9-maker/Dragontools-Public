# -*- coding: utf-8 -*-
"""GUI-Controller für Mediathek-Suche, gespeicherte Abfragen und SQL-Konsole."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)


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
        self._last_search_request: dict[str, str] | None = None

    @property
    def last_rows(self) -> list[dict[str, Any]]:
        return self._last_rows

    @last_rows.setter
    def last_rows(self, rows: list[dict[str, Any]]) -> None:
        self._last_rows = rows

    def refresh_saved_queries(self) -> None:
        data = self._service.load_saved_queries(self._get_db_path())
        self._fill_saved_combo(self._view.saved_search_combo, data.get("search", []))
        self._fill_saved_combo(self._view.saved_sql_combo, data.get("sql", []))

    @staticmethod
    def _fill_saved_combo(combo, rows: list[dict[str, Any]]) -> None:
        current_name = str(combo.currentText() or "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— auswählen —", None)
        for row in rows:
            combo.addItem(str(row.get("name") or ""), dict(row))
        index = combo.findText(current_name)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def run_search(self) -> None:
        request = {
            "preset": str(self._view.search_option_combo.currentData() or "all"),
            "text": self._view.search_text_edit.text(),
            "scope": str(self._view.search_scope_combo.currentData() or "all"),
            "media_type": str(self._view.search_type_combo.currentData() or "all"),
        }
        rows = self._service.search(
            self._get_db_path(),
            request["preset"],
            request["text"],
            scope=request["scope"],
            media_type=request["media_type"],
            limit=500,
        )
        self._last_search_request = request
        self._last_rows = rows
        table = self._view.search_table
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for row in rows:
            idx = table.rowCount()
            table.insertRow(idx)
            for col, value in enumerate(self._presenter.search_row_values(row, request["preset"])):
                item = QTableWidgetItem("" if value is None else str(value))
                if col in {3, 4, 5} and value is not None:
                    try:
                        item.setData(Qt.ItemDataRole.EditRole, int(value))
                    except (TypeError, ValueError):
                        pass
                table.setItem(idx, col, item)
        table.setSortingEnabled(True)
        suffix = " (Anzeige max. 500)" if len(rows) >= 500 else ""
        self._view.search_result_label.setText(f"{len(rows)} Treffer{suffix}")

    def export_search_csv(self) -> None:
        if not self._last_rows or not self._last_search_request:
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
            request = self._last_search_request
            target, exported_count = self._service.export_search_csv(
                self._get_db_path(),
                request["preset"],
                request["text"],
                file_name,
                scope=request["scope"],
                media_type=request["media_type"],
            )
            QMessageBox.information(
                self._parent,
                "CSV-Export",
                f"Trefferliste vollständig exportiert ({exported_count} Treffer):\n{target}",
            )
        except Exception as exc:
            QMessageBox.critical(self._parent, "CSV-Export fehlgeschlagen", str(exc))

    def save_current_search(self) -> None:
        name, accepted = QInputDialog.getText(self._parent, "Suche speichern", "Name der Suche:")
        if not accepted or not name.strip():
            return
        payload = {
            "mode": str(self._view.search_mode_combo.currentData() or "all"),
            "preset": str(self._view.search_option_combo.currentData() or "all"),
            "scope": str(self._view.search_scope_combo.currentData() or "all"),
            "media_type": str(self._view.search_type_combo.currentData() or "all"),
            "text": self._view.search_text_edit.text(),
        }
        self._service.save_named_query(self._get_db_path(), "search", name, payload)
        self.refresh_saved_queries()
        index = self._view.saved_search_combo.findText(name.strip())
        if index >= 0:
            self._view.saved_search_combo.setCurrentIndex(index)

    def load_saved_search(self) -> None:
        row = self._view.saved_search_combo.currentData()
        if not isinstance(row, dict):
            return
        mode_index = self._view.search_mode_combo.findData(str(row.get("mode") or "all"))
        if mode_index >= 0:
            self._view.search_mode_combo.setCurrentIndex(mode_index)
        self._view.update_search_options()
        preset_index = self._view.search_option_combo.findData(str(row.get("preset") or "all"))
        if preset_index >= 0:
            self._view.search_option_combo.setCurrentIndex(preset_index)
        scope_index = self._view.search_scope_combo.findData(str(row.get("scope") or "all"))
        if scope_index >= 0:
            self._view.search_scope_combo.setCurrentIndex(scope_index)
        type_index = self._view.search_type_combo.findData(str(row.get("media_type") or "all"))
        if type_index >= 0:
            self._view.search_type_combo.setCurrentIndex(type_index)
        self._view.search_text_edit.setText(str(row.get("text") or ""))

    def delete_saved_search(self) -> None:
        row = self._view.saved_search_combo.currentData()
        if not isinstance(row, dict):
            return
        self._service.delete_named_query(self._get_db_path(), "search", str(row.get("name") or ""))
        self.refresh_saved_queries()

    def save_current_sql(self) -> None:
        sql = self._view.sql_edit.toPlainText().strip()
        if not sql:
            return
        name, accepted = QInputDialog.getText(self._parent, "SQL-Abfrage speichern", "Name der Abfrage:")
        if not accepted or not name.strip():
            return
        self._service.save_named_query(self._get_db_path(), "sql", name, {"sql": sql})
        self.refresh_saved_queries()
        index = self._view.saved_sql_combo.findText(name.strip())
        if index >= 0:
            self._view.saved_sql_combo.setCurrentIndex(index)

    def load_saved_sql(self) -> None:
        row = self._view.saved_sql_combo.currentData()
        if isinstance(row, dict):
            self._view.sql_edit.setPlainText(str(row.get("sql") or ""))

    def delete_saved_sql(self) -> None:
        row = self._view.saved_sql_combo.currentData()
        if not isinstance(row, dict):
            return
        self._service.delete_named_query(self._get_db_path(), "sql", str(row.get("name") or ""))
        self.refresh_saved_queries()

    def show_sql_help(self) -> None:
        try:
            content = self._service.schema_help(self._get_db_path())
        except Exception as exc:
            QMessageBox.critical(self._parent, "SQL-Hilfe", str(exc))
            return
        dialog = QDialog(self._parent)
        dialog.setWindowTitle("Mediathek SQL-Hilfe – Tabellen, Attribute und Beispiele")
        dialog.resize(980, 720)
        layout = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        if hasattr(text, "setMarkdown"):
            text.setMarkdown(content)
        else:
            text.setPlainText(content)
        layout.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def export_sql_help(self) -> None:
        default = Path(self._get_db_path()).parent / "dragontools_mediathek_schema.md"
        file_name, _ = QFileDialog.getSaveFileName(
            self._parent,
            "SQL-Hilfe / Datenbankschema exportieren",
            str(default),
            "Markdown (*.md);;Text (*.txt);;Alle Dateien (*)",
        )
        if not file_name:
            return
        try:
            target = self._service.export_schema_help(self._get_db_path(), file_name)
            QMessageBox.information(self._parent, "Schema-Info", f"Schema-Info exportiert:\n{target}")
        except Exception as exc:
            QMessageBox.critical(self._parent, "Schema-Export fehlgeschlagen", str(exc))

    def run_sql(self) -> None:
        sql = self._view.sql_edit.toPlainText().strip()
        if not sql:
            return
        if self._service.sql_is_mutating(sql):
            answer = QMessageBox.question(
                self._parent,
                "SQL ausführen",
                "Diese Abfrage ist kein reines SELECT und kann die DragonTools-Mediathek verändern. "
                "Vor der Ausführung wird automatisch eine Sicherung erstellt. Fortfahren?",
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
