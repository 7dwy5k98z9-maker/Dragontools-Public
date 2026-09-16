# -*- coding: utf-8 -*-
"""Missing-season handling for EPxx-only renamer releases."""
from __future__ import annotations

from dataclasses import replace

from .movie_renamer_models import ParsedSeriesReleaseName


def apply_series_season_override(
    parsed: ParsedSeriesReleaseName,
    season_override: int | None,
) -> tuple[ParsedSeriesReleaseName, str | None]:
    """Apply an explicit season to an EPxx-only parsed release.

    Returns ``(parsed, issue)``. ``issue`` is ``None`` on success,
    ``"missing"`` when no season was supplied, and ``"invalid"`` for an
    out-of-range value.
    """
    if not parsed.season_missing:
        return parsed, None
    if season_override is None:
        return parsed, "missing"
    try:
        season = int(season_override)
    except (TypeError, ValueError):
        return parsed, "invalid"
    if season < 0 or season > 9999:
        return parsed, "invalid"

    warnings = tuple(
        item for item in parsed.warnings
        if not item.startswith("Staffel fehlt im EPxx-Muster")
    ) + (f"Staffel {season} manuell für EPxx gesetzt.",)
    return replace(
        parsed,
        season=season,
        season_missing=False,
        warnings=warnings,
    ), None
