# -*- coding: utf-8 -*-
"""Interactive season selection for EPxx-only release names."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QInputDialog

from ..core.movie_renamer import parse_series_release_name


class MovieRenamerSeasonPromptMixin:
    """Ask once per series/folder for a missing season in EPxx releases."""

    def prompt_missing_seasons(self, rows: list[int] | None = None) -> bool:
        candidate_rows = rows if rows is not None else list(range(self.view.table.rowCount()))
        unresolved = [row for row in candidate_rows if self.table_controller.row_requires_season(row)]
        if not unresolved:
            return True

        groups: dict[tuple[str, str], list[int]] = {}
        for row in unresolved:
            path = Path(self.table_controller.row_path(row))
            parsed = parse_series_release_name(path)
            series_key = (parsed.series if parsed is not None else path.stem).casefold()
            groups.setdefault((str(path.parent), series_key), []).append(row)

        all_resolved = True
        for group_rows in groups.values():
            first_path = Path(self.table_controller.row_path(group_rows[0]))
            parsed = parse_series_release_name(first_path)
            series = parsed.series if parsed is not None else first_path.stem
            episodes: list[str] = []
            for row in group_rows[:5]:
                row_parsed = parse_series_release_name(self.table_controller.row_path(row))
                episodes.append(f"EP{(row_parsed.episode if row_parsed else 0):02d}")
            episode_text = ", ".join(episodes)
            if len(group_rows) > 5:
                episode_text += ", …"

            season, ok = QInputDialog.getInt(
                self.owner,
                "Staffel für EPxx wählen",
                f"Für {series} wurde nur eine Episodennummer erkannt ({episode_text}).\n"
                f"Welche Staffel gilt für {len(group_rows)} Datei(en) in diesem Ordner?",
                1,
                0,
                9999,
                1,
            )
            if not ok:
                all_resolved = False
                continue
            for row in group_rows:
                self.table_controller.set_row_season_override(row, season)

        return all_resolved
