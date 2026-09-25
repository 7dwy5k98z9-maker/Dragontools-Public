# -*- coding: utf-8 -*-
"""Per-row season/episode override state for the renamer."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from ..core.movie_renamer import parse_series_release_name


class MovieRenamerSeriesOverrideStateMixin:
    def row_requires_season(self, row: int) -> bool:
        meta = self.row_meta(row)
        return bool(meta.get("season_missing")) and meta.get("season_override") is None

    def row_season_override(self, row: int) -> int | None:
        value = self.row_meta(row).get("season_override")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def set_row_season_override(self, row: int, season: int) -> None:
        season_value = int(season)
        if season_value < 0 or season_value > 9999:
            raise ValueError("Staffel muss zwischen 0 und 9999 liegen.")
        meta = self.row_meta(row)
        meta["season_override"] = season_value
        meta["season_missing"] = False
        self.row_item(row, self.columns.ACCEPT).setData(Qt.ItemDataRole.UserRole, meta)

        parsed = parse_series_release_name(self.row_path(row))
        if parsed is not None:
            episode = self.row_episode_override(row)
            if episode is None:
                episode = int(parsed.episode)
            self.set_item(
                row, self.columns.QUERY,
                f"S{season_value:02d}E{int(episode):02d}",
                editable=False,
            )
            hints = [
                item for item in parsed.warnings
                if not item.startswith("Staffel fehlt im EPxx-Muster")
                and "Staffel 1 wurde als Standard angenommen" not in item
            ]
            hints.append(f"Staffel {season_value} manuell gesetzt.")
            self.set_item(row, self.columns.HINTS, "; ".join(hints), editable=False)
        self.set_status(row, "bereit")

    def row_episode_override(self, row: int) -> int | None:
        value = self.row_meta(row).get("episode_override")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def set_row_episode_override(self, row: int, episode: int) -> None:
        episode_value = int(episode)
        if episode_value < 0 or episode_value > 9999:
            raise ValueError("Episode muss zwischen 0 und 9999 liegen.")
        meta = self.row_meta(row)
        meta["episode_override"] = episode_value
        self.row_item(row, self.columns.ACCEPT).setData(Qt.ItemDataRole.UserRole, meta)

        parsed = parse_series_release_name(self.row_path(row))
        if parsed is not None:
            season = self.row_season_override(row)
            if season is None:
                season = int(parsed.season)
            self.set_item(
                row, self.columns.QUERY,
                f"S{int(season):02d}E{episode_value:02d}",
                editable=False,
            )
            hints = [
                item for item in parsed.warnings
                if not (item.startswith("Episode ") and "manuell gesetzt" in item)
            ]
            hints.append(f"Episode {episode_value} manuell gesetzt.")
            self.set_item(row, self.columns.HINTS, "; ".join(hints), editable=False)
        self.set_status(row, "bereit")


__all__ = ["MovieRenamerSeriesOverrideStateMixin"]
