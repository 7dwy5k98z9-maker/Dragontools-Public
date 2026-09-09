# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QTableWidgetItem

from ..core.paths import VIDEO_EXTENSIONS, is_video_file, path_compare_key
from .drop_path_extractor import _iter_video_files_in_folder


class QualityTesterFilesMixin:
    def _add_files_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Videodateien auswählen",
            "",
            f"Video-Dateien ({' '.join('*' + ext for ext in sorted(VIDEO_EXTENSIONS))})",
        )
        self._add_paths(files)

    def _add_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ordner auswählen")
        if not folder:
            return
        self._add_paths([str(p) for p in _iter_video_files_in_folder(folder)])

    def _add_paths(self, paths: list[str]) -> None:
        existing = {
            path_compare_key(self.file_table.item(row, 1).text())
            for row in range(self.file_table.rowCount())
            if self.file_table.item(row, 1)
        }
        for raw in paths or []:
            path = Path(raw)
            if path.is_dir():
                for child in _iter_video_files_in_folder(str(path)):
                    self._add_paths([str(child)])
                continue
            if not path.exists() or not is_video_file(path):
                continue
            key = path_compare_key(path)
            if key in existing:
                continue
            existing.add(key)
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            self.file_table.setItem(row, 0, QTableWidgetItem(path.name))
            self.file_table.setItem(row, 1, QTableWidgetItem(str(path.resolve())))

    def _remove_selected_files(self) -> None:
        rows = sorted({idx.row() for idx in self.file_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.file_table.removeRow(row)

    def _choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", self.output_dir.text())
        if folder:
            self.output_dir.setText(folder)

    def _collect_files(self) -> list[str]:
        files = []
        for row in range(self.file_table.rowCount()):
            item = self.file_table.item(row, 1)
            if item and item.text().strip():
                files.append(item.text().strip())
        return files

    def _collect_runs(self) -> list[dict]:
        runs = []
        for row in range(self.run_table.rowCount()):
            active_item = self.run_table.item(row, self.RUN_COL_ACTIVE)
            if active_item and active_item.checkState() != Qt.CheckState.Checked:
                continue
            runs.append(self._row_to_dict(row))
        return runs[:20]
