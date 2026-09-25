# -*- coding: utf-8 -*-
"""Missing-season handling for EPxx-only renamer releases."""
from __future__ import annotations

from dataclasses import replace

from .movie_renamer_models import ParsedSeriesReleaseName


def apply_series_season_override(
    parsed: ParsedSeriesReleaseName,
    season_override: int | None,
) -> tuple[ParsedSeriesReleaseName, str | None]:
    """Apply an explicit season to a parsed series release.

    Returns ``(parsed, issue)``. ``issue`` is ``None`` on success,
    ``"missing"`` when no season was supplied, and ``"invalid"`` for an
    out-of-range value.
    """
    if season_override is None:
        return (parsed, "missing") if parsed.season_missing else (parsed, None)
    try:
        season = int(season_override)
    except (TypeError, ValueError):
        return parsed, "invalid"
    if season < 0 or season > 9999:
        return parsed, "invalid"

    warnings = tuple(
        item for item in parsed.warnings
        if not item.startswith("Staffel fehlt im EPxx-Muster")
        and not item.startswith("Staffel ")
        and "Staffel 1 wurde als Standard angenommen" not in item
    ) + (f"Staffel {season} manuell gesetzt.",)
    return replace(
        parsed,
        season=season,
        season_missing=False,
        warnings=warnings,
    ), None


def apply_series_episode_override(
    parsed: ParsedSeriesReleaseName,
    episode_override: int | None,
) -> tuple[ParsedSeriesReleaseName, str | None]:
    """Apply an explicit episode number to a parsed series release."""
    if episode_override is None:
        return parsed, None
    try:
        episode = int(episode_override)
    except (TypeError, ValueError):
        return parsed, "invalid"
    if episode < 0 or episode > 9999:
        return parsed, "invalid"

    warnings = tuple(
        item for item in parsed.warnings
        if not (item.startswith("Episode ") and "manuell gesetzt" in item)
    ) + (f"Episode {episode} manuell gesetzt.",)
    return replace(parsed, episode=episode, warnings=warnings), None
