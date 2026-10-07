# -*- coding: utf-8 -*-
"""Missing-season handling for EPxx-only renamer releases."""
from __future__ import annotations

from dataclasses import replace

from .movie_renamer_models import ParsedSeriesReleaseName


def normalize_episode_number(value, *, minimum=1):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and value.strip().isascii() and value.strip().isdecimal():
        number = int(value.strip())
    else:
        raise ValueError('Episoden- und Staffelnummern müssen ganze Zahlen sein.')
    if not minimum <= number <= 9999:
        raise ValueError('Episoden- oder Staffelnummer liegt außerhalb des gültigen Bereichs.')
    return number


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
        season = normalize_episode_number(season_override, minimum=0)
    except ValueError:
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
        episode = normalize_episode_number(episode_override)
    except ValueError:
        return parsed, "invalid"
    if episode <= 0 or episode > 9999:
        return parsed, "invalid"

    warnings = tuple(
        item for item in parsed.warnings
        if not (item.startswith("Episode ") and "manuell gesetzt" in item)
    ) + (f"Episode {episode} manuell gesetzt.",)
    numbers = tuple(range(episode, episode + len(parsed.episode_numbers)))
    if numbers[-1] > 9999:
        return parsed, 'invalid'
    return replace(parsed, episode=episode, episodes=numbers if parsed.episodes else (),
        episode_title='', episode_titles=(), episode_mapping_required=False, warnings=warnings), None
