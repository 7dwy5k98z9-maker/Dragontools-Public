# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.movie_renamer import parse_series_release_name
from ..core.path_syntax import path_compare_key


class MovieRenamerResolveSearchMixin:
    """Manual search plus stable per-path request versioning."""

    def _version_jobs(self, jobs: list[tuple]) -> list[tuple]:
        versioned: list[tuple] = []
        for job in jobs:
            path = str(job[1])
            key = path_compare_key(path)
            request_id = self._request_versions.get(key, 0) + 1
            self._request_versions[key] = request_id
            versioned.append((*job, request_id))
        return versioned

    def invalidate_paths(self, paths: list[str]) -> None:
        clean = [str(path) for path in paths if str(path or "").strip()]
        for path in clean:
            key = path_compare_key(path)
            self._request_versions[key] = self._request_versions.get(key, 0) + 1
        if clean and self.thread is not None and self.thread.isRunning():
            self.thread.cancel_paths(clean)

    def on_proposal_ready(self, path: str, request_id: int, proposal) -> None:
        key = path_compare_key(path)
        if self._request_versions.get(key) != int(request_id):
            return
        row = self.table_controller.find_row_by_path(path)
        if row is not None:
            self.table_controller.on_proposal_ready(row, proposal)

    def resolve_series_query(self, rows: list[int], query: str) -> None:
        self._resolve_manual_query(rows, query, kind="series")

    def resolve_movie_query(self, rows: list[int], query: str) -> None:
        self._resolve_manual_query(rows, query, kind="movie")

    def _resolve_manual_query(self, rows: list[int], query: str, *, kind: str) -> None:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return
        jobs: list[tuple] = []
        for row in sorted(set(rows)):
            path = self.table_controller.row_path(row)
            if not path:
                continue
            self.table_controller.prepare_manual_search(row, normalized_query, kind=kind)
            jobs.append((
                row, path, kind, normalized_query, False,
                self.table_controller.row_season_override(row),
                self.table_controller.row_episode_override(row),
            ))
        self.start_jobs(jobs, automatic=False, priority=True)

    def resolve_all_candidates(self, rows: list[int]) -> None:
        jobs: list[tuple] = []
        for row in sorted(set(rows)):
            path = self.table_controller.row_path(row)
            if not path:
                continue
            kind = self.table_controller.row_search_kind(row)
            query = self.table_controller.current_search_text([row], kind=kind)
            self.table_controller.prepare_manual_search(row, query, kind=kind)
            jobs.append((
                row, path, kind, query, True,
                self.table_controller.row_season_override(row),
                self.table_controller.row_episode_override(row),
            ))
        self.start_jobs(jobs, automatic=False, priority=True)

    def rerun_rows(self, rows: list[int]) -> None:
        """Re-run normal candidate resolution after a structural row edit.

        This keeps each row's current series/movie query but does not force the
        expanded "Alle Treffer" mode.  It is used after changing the season or episode.
        """
        jobs: list[tuple] = []
        for row in sorted(set(rows)):
            path = self.table_controller.row_path(row)
            if not path:
                continue
            kind = self.table_controller.row_search_kind(row)
            query = self.table_controller.current_search_text([row], kind=kind)
            if kind == "series" and not query:
                parsed = parse_series_release_name(path)
                query = parsed.series if parsed is not None else ""
            self.table_controller.prepare_manual_search(row, query, kind=kind)
            jobs.append((
                row, path, kind, query, False,
                self.table_controller.row_season_override(row),
                self.table_controller.row_episode_override(row),
            ))
        self.start_jobs(jobs, automatic=False, priority=True)
