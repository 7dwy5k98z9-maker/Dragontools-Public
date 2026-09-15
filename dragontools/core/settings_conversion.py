# -*- coding: utf-8 -*-
"""Conversion, validation and source-analysis setting keys and defaults."""
from __future__ import annotations

SET_KEY_OUTPUT_CONTAINER_STANDARD = "convert/output_container_standard"
SET_KEY_OUTPUT_CONTAINER_DV = "convert/output_container_dv"
DEFAULT_OUTPUT_CONTAINER_STANDARD = "mkv"
DEFAULT_OUTPUT_CONTAINER_DV = "mp4"

# Separate policy switches for the explicit DV-Remux workflow.  The normal
# Dolby-Vision encoder keeps using ``SET_KEY_OUTPUT_CONTAINER_DV``; these two
# values only decide how sources that cannot be copied 1:1 are handled when
# the user presses the DV-Remux button.
SET_KEY_DV_REMUX_KEEP_DV7_MKV = "dv_remux/keep_dv7_mkv"
SET_KEY_DV_REMUX_ENCODE_DV5 = "dv_remux/encode_dv5"
DEFAULT_DV_REMUX_KEEP_DV7_MKV = False
DEFAULT_DV_REMUX_ENCODE_DV5 = True

SET_KEY_ALLOW_GROWTH = "storage/allow_bigger_than_source"
SET_KEY_SAVE_ALLOW_LARGER_OUTPUT = "save/allow_larger_output"
SET_KEY_SAVE_ALLOW_LARGER_OUTPUT_PERCENT = "save/allow_larger_output_percent"
SET_KEY_SAVE_MIN_OUTPUT_SIZE_ENABLED = "save/min_output_size_enabled"
SET_KEY_SAVE_MIN_OUTPUT_SIZE_PERCENT = "save/min_output_size_percent"

PROFILE_LABELS = {"film": "Filme", "anime": "Anime", "tv": "TV"}
PROFILE_LABELS_REVERSE = {v: k for k, v in PROFILE_LABELS.items()}
DEFAULT_PROFILES: dict[str, dict] = {
    "film_h265": {"label": "Film H.265", "codec": "h265", "crf": 22, "preset": "medium", "scale": None},
    "tv_h265": {"label": "TV H.265", "codec": "h265", "crf": 22, "preset": "medium", "scale": None},
    "anime_h265": {"label": "Anime H.265", "codec": "h265", "crf": 20, "preset": "slow", "scale": None},
    "film_h264": {"label": "Film H.264", "codec": "h264", "crf": 22, "preset": "medium", "scale": None},
    "tv_h264": {"label": "TV H.264", "codec": "h264", "crf": 21, "preset": "medium", "scale": None},
    "anime_h264": {"label": "Anime H.264", "codec": "h264", "crf": 19, "preset": "slow", "scale": None},
    "film_av1": {"label": "Film AV1", "codec": "av1", "crf": 28, "preset": "6", "scale": None},
    "tv_av1": {"label": "TV AV1", "codec": "av1", "crf": 27, "preset": "6", "scale": None},
    "anime_av1": {"label": "Anime AV1", "codec": "av1", "crf": 25, "preset": "5", "scale": None},
}

SET_KEY_AUTOCROP_ENABLED = "convert/autocrop_enabled"
SET_KEY_AUTOCROP_MODE = "convert/autocrop_mode"
SET_KEY_AUTOCROP_PROBE_START = "convert/autocrop_probe_start_s"
SET_KEY_AUTOCROP_PROBE_DURATION = "convert/autocrop_probe_duration_s"
SET_KEY_AUTOCROP_PROBE_INTERVAL = "convert/autocrop_probe_interval_s"
DEFAULT_AUTOCROP_MODE = "single"
DEFAULT_AUTOCROP_PROBE_START_S = 30
DEFAULT_AUTOCROP_PROBE_DURATION_S = 45
DEFAULT_AUTOCROP_PROBE_INTERVAL_S = 600

SET_KEY_IMAX_DETECT = "convert/imax_auto_detect"
SET_KEY_IMAX_PROBE_INTERVAL = "convert/imax_probe_interval_s"
SET_KEY_IMAX_PROBE_DURATION = "convert/imax_probe_duration_s"
SET_KEY_IMAX_MIN_VARIANCE_PERCENT = "convert/imax_min_variance_percent"
SET_KEY_IMAX_MIN_HITS = "convert/imax_min_hits"
DEFAULT_IMAX_PROBE_INTERVAL_S = 90
DEFAULT_IMAX_PROBE_DURATION_S = 3
DEFAULT_IMAX_MIN_VARIANCE_PERCENT = 15
DEFAULT_IMAX_MIN_HITS = 2

SET_KEY_PRESERVE_DV = "encoder/h265/preserve_dv"
SET_KEY_PRESERVE_HDRPLUS = "encoder/h265/preserve_hdrplus"
SET_KEY_AV1_PRESERVE_DV = "encoder/av1/preserve_dv"
SET_KEY_AV1_PRESERVE_HDRPLUS = "encoder/av1/preserve_hdrplus"

SET_KEY_OUTPUT_MIN_SIZE_KB = "validation/output_min_size_kb"
SET_KEY_OUTPUT_DURATION_MIN_PERCENT = "validation/duration_min_percent"
SET_KEY_OUTPUT_DURATION_MAX_PERCENT = "validation/duration_max_percent"
SET_KEY_OUTPUT_DURATION_MAX_EXTRA_S = "validation/duration_max_extra_s"
DEFAULT_OUTPUT_MIN_SIZE_KB = 1
DEFAULT_OUTPUT_DURATION_MIN_PERCENT = 90
DEFAULT_OUTPUT_DURATION_MAX_PERCENT = 125
DEFAULT_OUTPUT_DURATION_MAX_EXTRA_S = 60

SET_KEY_REPAIR_DURATION_REMUX_ENABLED = "repair/duration/remux_enabled"
SET_KEY_REPAIR_DURATION_TIMESTAMP_ENABLED = "repair/duration/timestamp_enabled"
DEFAULT_REPAIR_DURATION_REMUX_ENABLED = True
DEFAULT_REPAIR_DURATION_TIMESTAMP_ENABLED = True

SET_KEY_SOURCE_VISUAL_CHECK_ENABLED = "source_visual_check/enabled"
SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT = "source_visual_check/interval_percent"
SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S = "source_visual_check/sample_duration_s"
SET_KEY_SOURCE_VISUAL_CHECK_FPS = "source_visual_check/fps"
SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT = "source_visual_check/block_percent"
SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS = "source_visual_check/min_hits"
DEFAULT_SOURCE_VISUAL_CHECK_ENABLED = True
DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT = 10
DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S = 2
DEFAULT_SOURCE_VISUAL_CHECK_FPS = 2
DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT = 80
DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS = 4

__all__ = [
    name for name in globals()
    if name.startswith(("SET_KEY_", "DEFAULT_", "PROFILE_"))
]
