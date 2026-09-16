# -*- coding: utf-8 -*-
"""Release-style warning classification for Renamer and Preflight."""
from __future__ import annotations

import re
from pathlib import Path

from .movie_renamer_parsing import parse_movie_release_name, parse_series_release_name


def release_style_warnings(value: str | Path) -> tuple[str, ...]:
    """Classify common non-normalized release-name traits without renaming."""
    source = Path(value)
    stem = source.stem
    warnings: list[str] = []
    separators = re.findall(r"(?<=[A-Za-z0-9])[._](?=[A-Za-z0-9])", stem)
    if len(separators) >= 2:
        warnings.append("Release-Trenner (Punkte/Unterstriche) erkannt")

    parsed_series = parse_series_release_name(source)
    if parsed_series is not None:
        if parsed_series.release_group:
            warnings.append(f"Release-Gruppe: {parsed_series.release_group}")
        if parsed_series.technical_tags:
            warnings.append("Technik-Tags: " + ", ".join(parsed_series.technical_tags[:4]))
    else:
        parsed_movie = parse_movie_release_name(source)
        if parsed_movie.release_group:
            warnings.append(f"Release-Gruppe: {parsed_movie.release_group}")
        if parsed_movie.technical_tags:
            warnings.append("Technik-Tags: " + ", ".join(parsed_movie.technical_tags[:4]))
    return tuple(dict.fromkeys(warnings))
