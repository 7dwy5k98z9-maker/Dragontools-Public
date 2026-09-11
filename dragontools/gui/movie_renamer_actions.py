# -*- coding: utf-8 -*-
"""User actions and filesystem commit for the renamer GUI."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

from ..core.movie_renamer import rename_movie_file
from ..core.paths import VIDEO_EXTENSIONS, is_video_file, path_compare_key
from .drop_path_extractor import _iter_video_files_in_folder
from .movie_renamer_search_actions import MovieRenamerSearchActionsMixin


class MovieRenamerActionController(MovieRenamerSearchActionsMixin):
    def __init__(self, owner, view, table_controller, resolver) -> None:
        self.owner = owner
        self.view = view
        self.table_controller = table_controller
        self.resolver = resolver

    def add_paths(self, paths: list[str]) -> None:
        expanded: list[str] = []
        ignored = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                folder_files, folder_ignored = _iter_video_files_in_folder(str(path))
                expanded.extend(folder_files)
                ignored += folder_ignored
            elif is_video_file(path):
                expanded.append(str(path))
            else:
                ignored += 1

        added = 0
        existing = self.table_controller.known_path_keys()
        for raw in expanded:
            path = Path(raw)
            key = path_compare_key(path)
            if key in existing:
                continue
            self.table_controller.add_row(path)
            existing.add(key)
            added += 1

        message = f"{added} Datei(en) hinzugefügt."
        if ignored:
            message += f" {ignored} Eintrag/Einträge ignoriert."
        self.view.status_lbl.setText(message)
        if added:
            self.resolver.schedule_new()

    def choose_files(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(VIDEO_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self.owner,
            "Videodateien auswählen",
            "",
            f"Videodateien ({patterns});;Alle Dateien (*)",
        )
        if paths:
            self.add_paths(paths)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self.owner, "Ordner auswählen")
        if folder:
            self.add_paths([folder])

    def accept_selected(self) -> None:
        rows = self.table_controller.selected_rows()
        if not rows:
            QMessageBox.information(
                self.owner,
                "Auswahl akzeptieren",
                "Bitte zuerst eine oder mehrere Zeilen markieren.",
            )
            return
        for row in rows:
            if self.table_controller.row_proposal(row) is not None:
                self.table_controller.set_row_accepted(row, True)
                self.table_controller.set_status(row, "✅ akzeptiert")
        self.view.status_lbl.setText(f"{len(rows)} Zeile(n) akzeptiert.")

    def accept_safe(self) -> None:
        count = 0
        for row in range(self.view.table.rowCount()):
            proposal = self.table_controller.row_proposal(row)
            if proposal and proposal.can_auto_accept:
                self.table_controller.set_row_accepted(row, True)
                self.table_controller.set_status(row, "✅ sicher")
                count += 1
        self.view.status_lbl.setText(f"{count} sichere Vorschläge akzeptiert.")

    def reject_selected(self) -> None:
        rows = self.table_controller.selected_rows()
        if not rows:
            QMessageBox.information(
                self.owner,
                "Auswahl ablehnen",
                "Bitte zuerst eine oder mehrere Zeilen markieren.",
            )
            return
        for row in rows:
            self.table_controller.set_row_accepted(row, False)
            self.table_controller.set_status(row, "🚫 abgelehnt")
        self.view.status_lbl.setText(f"{len(rows)} Zeile(n) abgelehnt.")

    def execute_rename(self) -> None:
        rows = [
            row
            for row in range(self.view.table.rowCount())
            if self.table_controller.row_accepted(row)
        ]
        if not rows:
            QMessageBox.information(self.owner, "Umbenennung", "Keine akzeptierten Vorschläge vorhanden.")
            return

        problems = self.table_controller.collect_rename_problems(rows)
        if problems:
            QMessageBox.warning(self.owner, "Umbenennung nicht möglich", "\n".join(problems[:12]))
            return

        reply = QMessageBox.question(
            self.owner,
            "Umbenennung ausführen",
            f"{len(rows)} Datei(en) werden im aktuellen Ordner umbenannt.\n\nFortfahren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        renamed_rows: list[int] = []
        failed: list[str] = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for row in rows:
                source = self.table_controller.row_path(row)
                target_name = self.table_controller.target_name(row)
                try:
                    rename_movie_file(source, target_name)
                except Exception as exc:
                    # Batch boundary: one bad file must not abort the remaining renames.
                    failed.append(f"{Path(source).name}: {exc}")
                    self.table_controller.set_status(row, "❌ Fehler")
                    continue
                renamed_rows.append(row)
        finally:
            QApplication.restoreOverrideCursor()

        for row in sorted(renamed_rows, reverse=True):
            self.view.table.removeRow(row)

        message = f"{len(renamed_rows)} Datei(en) umbenannt und aus der Liste entfernt."
        if failed:
            message += f" {len(failed)} Fehler blieb(en) zur Prüfung in der Liste."
            QMessageBox.warning(
                self.owner,
                "Umbenennung mit Fehlern",
                message + "\n\n" + "\n".join(failed[:8]),
            )
        self.view.status_lbl.setText(message)

    def remove_selected(self) -> None:
        for row in sorted(self.table_controller.selected_rows(), reverse=True):
            self.view.table.removeRow(row)
        self.view.status_lbl.setText("Auswahl entfernt.")

    def clear(self) -> None:
        self.view.table.setRowCount(0)
        self.view.status_lbl.setText("Liste geleert.")
