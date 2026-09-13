# -*- coding: utf-8 -*-
from __future__ import annotations

from ..core.settings import (
    DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
    DEFAULT_SOURCE_VISUAL_CHECK_ENABLED,
    DEFAULT_SOURCE_VISUAL_CHECK_FPS,
    DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
    DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS,
    DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
    SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
    SET_KEY_SOURCE_VISUAL_CHECK_ENABLED,
    SET_KEY_SOURCE_VISUAL_CHECK_FPS,
    SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
    SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS,
    SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
    settings_bool,
    settings_int,
)
from .source_visual_models import SourceVisualCheckSettings


def source_visual_settings_from_qsettings(settings) -> SourceVisualCheckSettings:
    return SourceVisualCheckSettings(
        enabled=settings_bool(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_ENABLED,
            DEFAULT_SOURCE_VISUAL_CHECK_ENABLED,
        ),
        interval_percent=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
            DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
            minimum=5,
            maximum=50,
        ),
        sample_duration_s=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
            DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
            minimum=1,
            maximum=10,
        ),
        fps=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_FPS,
            DEFAULT_SOURCE_VISUAL_CHECK_FPS,
            minimum=1,
            maximum=10,
        ),
        block_percent=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
            DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
            minimum=50,
            maximum=100,
        ),
        min_hits=settings_int(
            settings,
            SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS,
            DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS,
            minimum=1,
            maximum=20,
        ),
    )


__all__ = ["source_visual_settings_from_qsettings"]
