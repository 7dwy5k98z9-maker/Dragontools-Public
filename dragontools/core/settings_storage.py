# -*- coding: utf-8 -*-
"""Storage, logging, tool-path, move and parallelism setting keys."""
from __future__ import annotations

SET_KEY_PATH_TV = "paths/tv"
SET_KEY_PATH_ANIME = "paths/anime"
SET_KEY_PATH_FILME = "paths/filme"

SET_KEY_PATH_H264_TV = "paths/h264/tv"
SET_KEY_PATH_H264_ANIME = "paths/h264/anime"
SET_KEY_PATH_H264_FILME = "paths/h264/filme"
SET_KEY_PATH_H265_TV = "paths/h265/tv"
SET_KEY_PATH_H265_ANIME = "paths/h265/anime"
SET_KEY_PATH_H265_FILME = "paths/h265/filme"
SET_KEY_PATH_AV1_TV = "paths/av1/tv"
SET_KEY_PATH_AV1_ANIME = "paths/av1/anime"
SET_KEY_PATH_AV1_FILME = "paths/av1/filme"

SET_KEY_H264_LOG_ROOT = "paths/h264_log_root"
SET_KEY_H264_LOG_ENABLED = "logging/h264_enabled"
SET_KEY_H265_LOG_ROOT = "paths/h265_log_root"
SET_KEY_H265_LOG_ENABLED = "logging/h265_enabled"
SET_KEY_AV1_LOG_ROOT = "paths/av1_log_root"
SET_KEY_AV1_LOG_ENABLED = "logging/av1_enabled"
SET_KEY_LOG_ROOT = SET_KEY_H265_LOG_ROOT
SET_KEY_LOG_ENABLED = SET_KEY_H265_LOG_ENABLED
LOG_ROOT_KEYS = (SET_KEY_LOG_ROOT, SET_KEY_H264_LOG_ROOT, SET_KEY_AV1_LOG_ROOT)
LOG_ENABLED_KEYS = (SET_KEY_LOG_ENABLED, SET_KEY_H264_LOG_ENABLED, SET_KEY_AV1_LOG_ENABLED)
SET_KEY_VERBOSE_LOG_ROOT = "logging/verbose_log_root"
SET_KEY_VERBOSE_LOG_ENABLED = "logging/verbose_log_enabled"

TOOL_KEYS: dict[str, tuple[str, str]] = {
    "ffmpeg": ("tools/ffmpeg/use_custom", "tools/ffmpeg/dir"),
    "mkv": ("tools/mkv/use_custom", "tools/mkv/dir"),
    "makemkvcon": ("tools/makemkvcon/use_custom", "tools/makemkvcon/dir"),
    "rmts": ("tools/rmts/use_custom", "tools/rmts/dir"),
    "handbrake": ("tools/handbrake/use_custom", "tools/handbrake/dir"),
    "mediainfo": ("tools/mediainfo/use_custom", "tools/mediainfo/dir"),
    "dovi_tool": ("tools/dovi_tool/use_custom", "tools/dovi_tool/dir"),
    "hdr10plus_tool": ("tools/hdr10plus_tool/use_custom", "tools/hdr10plus_tool/dir"),
    "mp4box": ("tools/mp4box/use_custom", "tools/mp4box/dir"),
}

SET_KEY_ACTIVE_ALL_TV = "move/active_tv"
SET_KEY_ACTIVE_ALL_ANIME = "move/active_anime"
SET_KEY_ACTIVE_ALL_FILME = "move/active_filme"
SET_KEY_SERIES_DEFAULT_TYPE = "move/series_default_type"
SET_KEY_SHUTDOWN_COUNTDOWN = "move/shutdown_countdown_seconds"
SET_KEY_MOVE_CONFLICT = "move/conflict_mode"
SET_KEY_PREFLIGHT_SAVE_REPORT = "preflight/save_report"

SET_KEY_PARALLEL_CPU_JOBS = "parallel/cpu_jobs"
SET_KEY_PARALLEL_GPU_JOBS = "parallel/gpu_jobs"
SET_KEY_PARALLEL_DEFAULTS_MIGRATED = "parallel/defaults_cpu1_gpu2_migrated"
DEFAULT_PARALLEL_CPU_JOBS = 1
DEFAULT_PARALLEL_GPU_JOBS = 2
MAX_PARALLEL_JOBS = 8

__all__ = [name for name in globals() if name.startswith(("SET_KEY_", "DEFAULT_", "LOG_", "TOOL_", "MAX_"))]
