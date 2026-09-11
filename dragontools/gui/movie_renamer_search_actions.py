# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QInputDialog, QMessageBox


class MovieRenamerSearchActionsMixin:
    """Manual search actions kept separate from filesystem rename actions."""

    def manual_series_search(self) -> None:
        rows, _skipped, current = self.table_controller.manual_series_search_selection()
        self._prompt_and_resolve(rows, current, kind="series")

    def manual_movie_search(self) -> None:
        rows, current = self.table_controller.manual_movie_search_selection()
        self._prompt_and_resolve(rows, current, kind="movie")

    def edit_search_query(self) -> None:
        rows = self.table_controller.selected_rows()
        if not rows:
            QMessageBox.information(self.owner, "Suchbegriff bearbeiten", "Bitte eine oder mehrere Zeilen markieren.")
            return
        kinds = {
            "series" if self.table_controller.row_item(row, self.table_controller.columns.TYPE).text() == "Serie" else "movie"
            for row in rows
        }
        if len(kinds) != 1:
            QMessageBox.information(
                self.owner,
                "Suchbegriff bearbeiten",
                "Bitte nur Filme oder nur Serien gemeinsam markieren.",
            )
            return
        kind = next(iter(kinds))
        current = self.table_controller.current_search_text(rows, kind=kind)
        self._prompt_and_resolve(rows, current, kind=kind, title="Suchbegriff bearbeiten")

    def show_all_candidates(self) -> None:
        rows = self.table_controller.selected_rows()
        if not rows:
            QMessageBox.information(self.owner, "Alle Treffer anzeigen", "Bitte eine oder mehrere Zeilen markieren.")
            return
        self.resolver.resolve_all_candidates(rows)

    def _prompt_and_resolve(self, rows: list[int], current: str, *, kind: str, title: str | None = None) -> None:
        if not rows:
            label = "Als Serie suchen" if kind == "series" else "Als Film suchen"
            QMessageBox.information(self.owner, label, "Bitte eine oder mehrere Zeilen markieren.")
            return
        label = title or ("Als Serie suchen" if kind == "series" else "Als Film suchen")
        field = "Serien-Suchbegriff:" if kind == "series" else "Film-Suchbegriff:"
        query, ok = QInputDialog.getText(self.owner, label, field, text=current)
        query = str(query or "").strip()
        if not ok or not query:
            return
        if kind == "series":
            self.resolver.resolve_series_query(rows, query)
            kind_label = "Seriensuche"
        else:
            self.resolver.resolve_movie_query(rows, query)
            kind_label = "Filmsuche"
        self.view.status_lbl.setText(f"Manuelle {kind_label} für {len(rows)} Datei(en) gestartet.")
