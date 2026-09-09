# -*- coding: utf-8 -*-
"""Move-Regeln: schlanke Fassade plus zentrale Zielpfad-Orchestrierung."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.paths import join_user_path
from .move_rule_config import _DEFAULT_MOVE_RULES, migrate_move_rules
from .move_series_detection import (
    _SER_EP_RE, _MULTI_EP_E_RE, _MULTI_EP_X_RE, _SEP_BEFORE, _DOUBLE_BEFORE, _SEP_AFTER,
    _decide_series_block, _clean_series_name, parse_series_match_details, parse_series_season_episode,
)
from .move_path_helpers import (
    _WIN_FORBIDDEN_SEGMENT_CHARS, _WIN_RESERVED_NAMES, sanitize_win_segment, move_safe_stem,
    default_film_series_name, film_bucket_from_title, normalize_relative_move_subpath,
    apply_relative_move_subpath, _normalize_for_dir_match, _strip_dir_year_suffix,
)
from .move_series_directories import (
    find_series_dir_candidates, find_existing_series_dir, resolve_series_root_dir,
    _SPECIALS_FOLDER_NAMES, find_specials_subfolder,
)

def resolve_target_path(
    *,
    kind: str,
    base_path: str | None = None,
    film_name: str | None = None,
    series_name: str | None = None,
    season: int | None = None,
    mode: str = "single",
    series_dir: str | None = None,
    relative_subpath: str | None = None,
) -> str | None:
    """Zentrale Zielpfad-Auflösung für Serien und Filme."""
    if kind == "series":
        if season is None:
            return None
        if series_dir:
            root = str(series_dir)
        else:
            if not base_path:
                return None
            safe_series = sanitize_win_segment(series_name, fallback="Unbekannt")
            existing = find_existing_series_dir(base_path, safe_series)
            root = existing if existing else join_user_path(base_path, safe_series)

        # Staffel 0 = Specials: zuerst vorhandenen Ordner suchen,
        # sonst "Specials" anlegen – nie "Staffel 00"
        if season == 0:
            existing_specials = find_specials_subfolder(root)
            if existing_specials:
                return existing_specials
            return join_user_path(root, "Specials")

        return join_user_path(root, f"Staffel {int(season):02d}")

    if kind != "film" or not base_path and mode != "series_explorer":
        return None

    safe_film = sanitize_win_segment(film_name, fallback="Unbekannt")
    if mode == "single":
        bucket = film_bucket_from_title(safe_film)
        return join_user_path(base_path, bucket, safe_film)
    if mode == "series":
        safe_series = sanitize_win_segment(series_name, fallback=safe_film)
        bucket = film_bucket_from_title(safe_series)
        series_root = join_user_path(base_path, bucket, safe_series)
        subpath = normalize_relative_move_subpath(relative_subpath)
        if subpath:
            series_root = join_user_path(series_root, *subpath.split("/"))
        return join_user_path(series_root, safe_film)
    if mode == "series_explorer" and series_dir:
        root = str(series_dir)
        subpath = normalize_relative_move_subpath(relative_subpath)
        if subpath:
            root = join_user_path(root, *subpath.split("/"))
        return join_user_path(root, safe_film)
    return None


def resolve_film_target_for_path(
    path: str,
    *,
    base_path: str | None,
    mode: str = "single",
    film_name: str | None = None,
    series_name: str | None = None,
    series_dir: str | None = None,
    relative_subpath: str | None = None,
) -> str | None:
    """Zentrale Film-Zielauflösung für konkrete Dateien.

    UI und MoveThread sollen hier nur Nutzereingaben durchreichen; Stem-
    Bereinigung und Pfadentscheidung bleiben in diesem Modul.
    """
    stem = film_name.strip() if film_name else move_safe_stem(path)
    if not stem:
        return None
    return resolve_target_path(
        kind="film",
        base_path=base_path,
        film_name=stem,
        series_name=(series_name or stem),
        mode=mode,
        series_dir=series_dir,
        relative_subpath=relative_subpath,
    )


def planned_target_dir(entry: Any) -> str | None:
    """Extrahiert den finalen Zielordner aus alter oder neuer planned-target-Struktur."""
    if isinstance(entry, (str, Path)):
        text = str(entry).strip()
        return text or None
    if isinstance(entry, dict):
        target = entry.get("target")
        if isinstance(target, (str, Path)):
            text = str(target).strip()
            return text or None
    return None


def valid_move_bases(
    tv_path: str | None,
    anime_path: str | None,
    filme_path: str | None,
) -> list[Path]:
    """Normalisiert die konfigurierten Move-Basisordner."""
    bases: list[Path] = []
    for base in (tv_path, anime_path, filme_path):
        if not base:
            continue
        try:
            bases.append(Path(base).resolve())
        except OSError:
            continue
    return bases


def is_planned_move_target_valid(
    path: str,
    target: str,
    *,
    tv_path: str | None,
    anime_path: str | None,
    filme_path: str | None,
) -> bool:
    """Zentrale Plausibilitätsprüfung für geplante Move-Ziele."""
    if not target or not str(target).strip():
        return False

    try:
        target_path = Path(target).resolve()
    except OSError:
        return False

    video_suffixes = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".wmv"}
    if target_path.exists() and target_path.is_file():
        return False
    if target_path.suffix.lower() in video_suffixes:
        return False

    bases = valid_move_bases(tv_path, anime_path, filme_path)
    if not bases:
        return False

    try:
        if not any(target_path == base or target_path.is_relative_to(base) for base in bases):
            return False
    except ValueError:
        return False

    parsed = parse_series_match_details(Path(path).name)
    if parsed and parsed.get("series"):
        expected_bases = valid_move_bases(tv_path, anime_path, None)
    else:
        expected_bases = valid_move_bases(None, None, filme_path)

    if expected_bases and not any(
        target_path == base or target_path.is_relative_to(base)
        for base in expected_bases
    ):
        return False

    return True
