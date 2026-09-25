# -*- coding: utf-8 -*-
"""Interactive season selection for EPxx-only release names."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QInputDialog, QMessageBox

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

    def edit_selected_season(self) -> None:
        """Manually override the season for selected series rows.

        Unlike the EPxx prompt this is intentionally available for every
        parsed series row, including SxxExx and inferred bare E19 releases.
        """
        rows = self.table_controller.selected_rows()
        if not rows:
            QMessageBox.information(
                self.owner,
                "Staffel ändern",
                "Bitte zuerst eine oder mehrere Serien-Zeilen markieren.",
            )
            return

        series_rows: list[int] = []
        detected_seasons: set[int] = set()
        for row in rows:
            if self.table_controller.row_item(row, self.table_controller.columns.TYPE).text() != "Serie":
                continue
            series_rows.append(row)
            override = self.table_controller.row_season_override(row)
            if override is not None:
                detected_seasons.add(override)
                continue
            parsed = parse_series_release_name(self.table_controller.row_path(row))
            if parsed is not None:
                detected_seasons.add(int(parsed.season))

        if not series_rows:
            QMessageBox.information(
                self.owner,
                "Staffel ändern",
                "Die markierte Auswahl enthält keine als Serie erkannten Dateien.",
            )
            return

        default_season = next(iter(detected_seasons)) if len(detected_seasons) == 1 else 1
        season, ok = QInputDialog.getInt(
            self.owner,
            "Staffel ändern",
            f"Staffel für {len(series_rows)} ausgewählte Serien-Datei(en):",
            default_season,
            0,
            9999,
            1,
        )
        if not ok:
            return

        for row in series_rows:
            self.table_controller.set_row_season_override(row, season)

        rerun = getattr(self.resolver, "rerun_rows", None)
        if callable(rerun):
            rerun(series_rows)
        self.view.status_lbl.setText(
            f"Staffel {season} für {len(series_rows)} Serien-Datei(en) gesetzt; Metadaten werden neu gesucht."
        )


    def edit_selected_episode(self) -> None:
        """Manually override the episode number for selected series rows."""
        rows = self.table_controller.selected_rows()
        if not rows:
            QMessageBox.information(
                self.owner,
                "Episode ändern",
                "Bitte zuerst eine oder mehrere Serien-Zeilen markieren.",
            )
            return

        series_rows: list[int] = []
        detected_episodes: set[int] = set()
        for row in rows:
            if self.table_controller.row_item(row, self.table_controller.columns.TYPE).text() != "Serie":
                continue
            series_rows.append(row)
            override = self.table_controller.row_episode_override(row)
            if override is not None:
                detected_episodes.add(override)
                continue
            parsed = parse_series_release_name(self.table_controller.row_path(row))
            if parsed is not None:
                detected_episodes.add(int(parsed.episode))

        if not series_rows:
            QMessageBox.information(
                self.owner,
                "Episode ändern",
                "Die markierte Auswahl enthält keine als Serie erkannten Dateien.",
            )
            return

        default_episode = next(iter(detected_episodes)) if len(detected_episodes) == 1 else 1
        episode, ok = QInputDialog.getInt(
            self.owner,
            "Episode ändern",
            f"Episode für {len(series_rows)} ausgewählte Serien-Datei(en):",
            default_episode,
            0,
            9999,
            1,
        )
        if not ok:
            return

        for row in series_rows:
            self.table_controller.set_row_episode_override(row, episode)

        rerun = getattr(self.resolver, "rerun_rows", None)
        if callable(rerun):
            rerun(series_rows)
        self.view.status_lbl.setText(
            f"Episode {episode} für {len(series_rows)} Serien-Datei(en) gesetzt; Metadaten werden neu gesucht."
        )
