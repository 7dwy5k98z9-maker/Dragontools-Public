# -*- coding: utf-8 -*-
"""GUI-Controller für Mediathek-Pfad-Mappings."""
from __future__ import annotations

from typing import Callable

from PyQt6.QtWidgets import QMessageBox, QTableWidget, QTableWidgetItem

from ..core.media_library_types import PathMapping


class MediaLibraryMappingController:
    def __init__(self, *, parent, view, service, settings, get_db_path: Callable[[], str]) -> None:
        self._parent = parent
        self._view = view
        self._service = service
        self._settings = settings
        self._get_db_path = get_db_path

    def set_rows(self, mappings: list[PathMapping]) -> None:
        self._view.mapping_table.setRowCount(0)
        for mapping in mappings:
            self.add_row(mapping)

    def add_row(self, mapping: PathMapping | None = None) -> None:
        mapping = mapping or PathMapping("", "", "")
        row = self._view.mapping_table.rowCount()
        self._view.mapping_table.insertRow(row)
        self._view.mapping_table.setItem(row, 0, QTableWidgetItem(mapping.label))
        self._view.mapping_table.setItem(row, 1, QTableWidgetItem(mapping.external_prefix))
        self._view.mapping_table.setItem(row, 2, QTableWidgetItem(mapping.local_prefix))

    def remove_selected_rows(self) -> None:
        rows = sorted({item.row() for item in self._view.mapping_table.selectedItems()}, reverse=True)
        for row in rows:
            self._view.mapping_table.removeRow(row)

    def mappings(self) -> list[PathMapping]:
        mappings: list[PathMapping] = []
        for row in range(self._view.mapping_table.rowCount()):
            label = self.table_text(self._view.mapping_table, row, 0)
            external = self.table_text(self._view.mapping_table, row, 1)
            local = self.table_text(self._view.mapping_table, row, 2)
            if external and local:
                mappings.append(PathMapping(label, external, local))
        return mappings

    def save(self) -> None:
        try:
            self._service.save_mappings(self._settings, self._get_db_path(), self.mappings())
        except Exception as exc:
            QMessageBox.warning(
                self._parent,
                "Mapping",
                f"Mapping wurde gespeichert, aber nicht in die DB geschrieben:\n{exc}",
            )
            return
        QMessageBox.information(self._parent, "Mapping", "Pfad-Mapping wurde gespeichert.")

    def fill_from_storage_paths(self) -> None:
        rows = self._service.storage_path_mappings(self._settings)
        if not rows:
            QMessageBox.information(
                self._parent,
                "Pfad-Mapping",
                "In den Speicherpfaden sind noch keine Zielordner hinterlegt.",
            )
            return
        self.set_rows(rows)

    @staticmethod
    def table_text(table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item else ""
