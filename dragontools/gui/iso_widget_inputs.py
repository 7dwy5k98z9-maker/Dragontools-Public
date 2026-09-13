from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog


class ISOWidgetInputMixin:
    """Input-list, output-path and explicit title selection behavior."""

    def _append_log(self, text: str) -> None:
        if self.log_edit is not None:
            self.log_edit.append(text)

    def _add_paths(self, paths: list[str]) -> None:
        if self.input_list is None:
            return
        existing = {
            str(Path(self.input_list.item(i).text()).resolve())
            for i in range(self.input_list.count())
        }
        added = 0
        for raw in paths:
            if not raw:
                continue
            path = str(Path(raw).resolve())
            if path in existing:
                continue
            self.input_list.addItem(path)
            existing.add(path)
            added += 1
        if added:
            self._append_log(f"ℹ️ {added} Eingabe(n) hinzugefügt.")

    def _add_iso_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "ISO-Dateien auswählen",
            "",
            "ISO-Dateien (*.iso);;Alle Dateien (*)",
        )
        self._add_paths(paths)

    def _add_disc_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Disc-Ordner auswählen", "")
        if folder:
            self._add_paths([folder])

    def _remove_selected(self) -> None:
        if self.input_list is None:
            return
        rows = sorted({idx.row() for idx in self.input_list.selectedIndexes()}, reverse=True)
        if not rows:
            return
        removed_paths = []
        for row in rows:
            item = self.input_list.takeItem(row)
            if item is not None:
                removed_paths.append(item.text())
        if self._analyzed_input_path and self._analyzed_input_path in removed_paths:
            self._analyzed_input_path = None
            if self.title_list is not None:
                self.title_list.clear()
        self._append_log(f"ℹ️ {len(removed_paths)} Eingabe(n) entfernt.")

    def _clear_inputs(self) -> None:
        if self.input_list is not None:
            self.input_list.clear()
        if self.title_list is not None:
            self.title_list.clear()
        self._analyzed_input_path = None
        self._append_log("ℹ️ Eingabeliste geleert.")

    def _browse_output(self) -> None:
        if self.output_edit is None:
            return
        folder = QFileDialog.getExistingDirectory(self, "Zielordner wählen", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def _current_input_path(self) -> str | None:
        if self.input_list is None or self.input_list.count() == 0:
            return None
        current = self.input_list.currentItem()
        if current is not None:
            return current.text()
        selected = self.input_list.selectedItems()
        if selected:
            return selected[0].text()
        return self.input_list.item(0).text()

    def _collect_selected_titles(self) -> dict[str, list[int]]:
        if self.title_list is None or not self._analyzed_input_path:
            return {}
        title_ids: list[int] = []
        for item in self.title_list.selectedItems():
            tid = item.data(Qt.ItemDataRole.UserRole)
            path = item.data(Qt.ItemDataRole.UserRole + 1)
            if path == self._analyzed_input_path and isinstance(tid, int):
                title_ids.append(tid)
        return {self._analyzed_input_path: title_ids} if title_ids else {}
