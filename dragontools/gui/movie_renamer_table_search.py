# -*- coding: utf-8 -*-
from __future__ import annotations


class MovieRenamerTableSearchMixin:
    """Manual-search helpers separated from table rendering/state."""

    def prepare_manual_search(self, row: int, query: str, *, kind: str) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        normalized = str(query or "").strip()
        self.table.removeCellWidget(row, self.columns.MATCH)
        self.set_row_proposal(row, None)
        if kind == "series":
            self.set_item(row, self.columns.TYPE, "Serie", editable=False)
            self.set_item(row, self.columns.SERIES, normalized, editable=False)
        else:
            self.set_item(row, self.columns.TYPE, "Film", editable=False)
            self.set_item(row, self.columns.QUERY, normalized, editable=False)
            self.set_item(row, self.columns.SERIES, "", editable=False)
        self.set_item(row, self.columns.MATCH, "manuelle Suche …", editable=False)
        self.set_item(row, self.columns.PROVIDER, "", editable=False)
        self.set_item(row, self.columns.SCORE, "", editable=False)
        self.set_status(row, "🔎 Suche")

    def prepare_manual_series_search(self, row: int, query: str) -> None:
        self.prepare_manual_search(row, query, kind="series")

    def prepare_manual_movie_search(self, row: int, query: str) -> None:
        self.prepare_manual_search(row, query, kind="movie")

    def manual_series_search_selection(self) -> tuple[list[int], int, str]:
        rows = self.selected_rows()
        return rows, 0, self.current_search_text(rows, kind="series")

    def manual_movie_search_selection(self) -> tuple[list[int], str]:
        rows = self.selected_rows()
        return rows, self.current_search_text(rows, kind="movie")

    def row_search_kind(self, row: int) -> str:
        return "series" if self.row_item(row, self.columns.TYPE).text() == "Serie" else "movie"

    def current_search_text(self, rows: list[int], *, kind: str) -> str:
        values: set[str] = set()
        for row in rows:
            if kind == "series":
                value = (
                    self.row_item(row, self.columns.SERIES).text().strip()
                    or self.row_item(row, self.columns.QUERY).text().strip()
                )
            else:
                value = (
                    self.row_item(row, self.columns.QUERY).text().strip()
                    or self.row_item(row, self.columns.SERIES).text().strip()
                )
            if value:
                values.add(value)
        return next(iter(values)) if len(values) == 1 else ""
