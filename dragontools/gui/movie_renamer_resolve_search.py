# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox


class MovieRenamerResolveSearchMixin:
    """Manual/fallback search job preparation for the renamer coordinator."""

    def resolve_series_query(self, rows: list[int], query: str) -> None:
        self._resolve_manual_query(rows, query, kind="series")

    def resolve_movie_query(self, rows: list[int], query: str) -> None:
        self._resolve_manual_query(rows, query, kind="movie")

    def _resolve_manual_query(self, rows: list[int], query: str, *, kind: str) -> None:
        if self._search_running():
            return
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return
        jobs: list[tuple[int, str, str, str, bool]] = []
        for row in sorted(set(rows)):
            path = self.table_controller.row_path(row)
            if not path:
                continue
            self.table_controller.prepare_manual_search(row, normalized_query, kind=kind)
            jobs.append((row, path, kind, normalized_query, False))
        self.start_jobs(jobs, automatic=False)

    def resolve_all_candidates(self, rows: list[int]) -> None:
        if self._search_running():
            return
        jobs: list[tuple[int, str, str, str, bool]] = []
        for row in sorted(set(rows)):
            path = self.table_controller.row_path(row)
            if not path:
                continue
            kind = self.table_controller.row_search_kind(row)
            query = self.table_controller.current_search_text([row], kind=kind)
            self.table_controller.prepare_manual_search(row, query, kind=kind)
            jobs.append((row, path, kind, query, True))
        self.start_jobs(jobs, automatic=False)

    def _search_running(self) -> bool:
        if self.thread is None or not self.thread.isRunning():
            return False
        QMessageBox.information(self.owner, "Metadaten-Suche", "Die Vorschlagssuche läuft bereits.")
        return True
