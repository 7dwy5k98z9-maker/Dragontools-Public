# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.settings import (
    DEFAULT_NFO_CONFLICT_MODE,
    DEFAULT_NFO_ENABLED,
    DEFAULT_NFO_FILEINFO_ENABLED,
    DEFAULT_NFO_MOVIE_TARGET_NAME,
    DEFAULT_NFO_ONLY_UNAMBIGUOUS,
    DEFAULT_TRICKPLAY_ENABLED,
    DEFAULT_TRICKPLAY_CONFLICT_MODE,
    DEFAULT_TRICKPLAY_HWACCEL,
    DEFAULT_TRICKPLAY_INTERVAL_S,
    DEFAULT_TRICKPLAY_JPEG_QUALITY,
    DEFAULT_TRICKPLAY_MAX_JOBS,
    DEFAULT_TRICKPLAY_ONLY_MISSING,
    DEFAULT_TRICKPLAY_QSCALE,
    DEFAULT_TRICKPLAY_SOURCE_MODE,
    DEFAULT_TRICKPLAY_TILE_COLUMNS,
    DEFAULT_TRICKPLAY_TILE_ROWS,
    DEFAULT_TRICKPLAY_WIDTH,
    SET_KEY_NFO_CONFLICT_MODE,
    SET_KEY_NFO_ENABLED,
    SET_KEY_NFO_FILEINFO_ENABLED,
    SET_KEY_NFO_MOVIE_TARGET_NAME,
    SET_KEY_NFO_ONLY_UNAMBIGUOUS,
    SET_KEY_TRICKPLAY_ENABLED,
    SET_KEY_TRICKPLAY_CONFLICT_MODE,
    SET_KEY_TRICKPLAY_HWACCEL,
    SET_KEY_TRICKPLAY_INTERVAL_S,
    SET_KEY_TRICKPLAY_JPEG_QUALITY,
    SET_KEY_TRICKPLAY_MAX_JOBS,
    SET_KEY_TRICKPLAY_ONLY_MISSING,
    SET_KEY_TRICKPLAY_QSCALE,
    SET_KEY_TRICKPLAY_SOURCE_MODE,
    SET_KEY_TRICKPLAY_TILE_COLUMNS,
    SET_KEY_TRICKPLAY_TILE_ROWS,
    SET_KEY_TRICKPLAY_WIDTH,
    settings_bool,
    settings_int,
    settings_text,
)

from .postprocess_models import NfoSettings, PostProcessConfig
from .trickplay_service import TrickplaySettings


def config_from_settings(settings) -> PostProcessConfig:
    conflict_modes = {"skip", "overwrite", "backup"}
    nfo_conflict = settings_text(
        settings,
        SET_KEY_NFO_CONFLICT_MODE,
        DEFAULT_NFO_CONFLICT_MODE,
        allowed=conflict_modes,
    )
    movie_target_name = settings_text(
        settings,
        SET_KEY_NFO_MOVIE_TARGET_NAME,
        DEFAULT_NFO_MOVIE_TARGET_NAME,
    )
    trickplay_source_mode = settings_text(
        settings,
        SET_KEY_TRICKPLAY_SOURCE_MODE,
        DEFAULT_TRICKPLAY_SOURCE_MODE,
        allowed={"output", "source"},
    )
    trickplay_conflict_mode = settings_text(
        settings,
        SET_KEY_TRICKPLAY_CONFLICT_MODE,
        "",
        allowed=conflict_modes,
    )
    if not trickplay_conflict_mode:
        only_missing = settings_bool(
            settings,
            SET_KEY_TRICKPLAY_ONLY_MISSING,
            DEFAULT_TRICKPLAY_ONLY_MISSING,
        )
        trickplay_conflict_mode = "skip" if only_missing else "overwrite"
    if trickplay_conflict_mode not in conflict_modes:
        trickplay_conflict_mode = DEFAULT_TRICKPLAY_CONFLICT_MODE

    return PostProcessConfig(
        nfo=NfoSettings(
            enabled=settings_bool(settings, SET_KEY_NFO_ENABLED, DEFAULT_NFO_ENABLED),
            only_unambiguous=settings_bool(
                settings,
                SET_KEY_NFO_ONLY_UNAMBIGUOUS,
                DEFAULT_NFO_ONLY_UNAMBIGUOUS,
            ),
            include_fileinfo=settings_bool(
                settings,
                SET_KEY_NFO_FILEINFO_ENABLED,
                DEFAULT_NFO_FILEINFO_ENABLED,
            ),
            movie_target_name=movie_target_name,
            conflict_mode=nfo_conflict,
        ),
        trickplay=TrickplaySettings(
            enabled=settings_bool(settings, SET_KEY_TRICKPLAY_ENABLED, DEFAULT_TRICKPLAY_ENABLED),
            only_missing=settings_bool(
                settings,
                SET_KEY_TRICKPLAY_ONLY_MISSING,
                DEFAULT_TRICKPLAY_ONLY_MISSING,
            ),
            conflict_mode=trickplay_conflict_mode,
            width=settings_int(
                settings,
                SET_KEY_TRICKPLAY_WIDTH,
                DEFAULT_TRICKPLAY_WIDTH,
                minimum=16,
            ),
            tile_columns=settings_int(
                settings,
                SET_KEY_TRICKPLAY_TILE_COLUMNS,
                DEFAULT_TRICKPLAY_TILE_COLUMNS,
                minimum=1,
            ),
            tile_rows=settings_int(
                settings,
                SET_KEY_TRICKPLAY_TILE_ROWS,
                DEFAULT_TRICKPLAY_TILE_ROWS,
                minimum=1,
            ),
            interval_s=settings_int(
                settings,
                SET_KEY_TRICKPLAY_INTERVAL_S,
                DEFAULT_TRICKPLAY_INTERVAL_S,
                minimum=1,
            ),
            jpeg_quality=settings_int(
                settings,
                SET_KEY_TRICKPLAY_JPEG_QUALITY,
                DEFAULT_TRICKPLAY_JPEG_QUALITY,
                minimum=1,
                maximum=100,
            ),
            qscale=settings_int(
                settings,
                SET_KEY_TRICKPLAY_QSCALE,
                DEFAULT_TRICKPLAY_QSCALE,
                minimum=2,
                maximum=31,
            ),
            hwaccel=settings_text(
                settings,
                SET_KEY_TRICKPLAY_HWACCEL,
                DEFAULT_TRICKPLAY_HWACCEL,
                allowed={"cuda", "none", "qsv", "dxva2", "d3d11va"},
            ),
            max_jobs=settings_int(
                settings,
                SET_KEY_TRICKPLAY_MAX_JOBS,
                DEFAULT_TRICKPLAY_MAX_JOBS,
                minimum=1,
                maximum=8,
            ),
            source_mode=trickplay_source_mode,
        ),
    )
