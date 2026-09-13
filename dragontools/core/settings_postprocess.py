# -*- coding: utf-8 -*-
"""NFO and trickplay post-processing setting keys and defaults."""
from __future__ import annotations

SET_KEY_NFO_ENABLED = "postprocess/nfo/enabled"
SET_KEY_NFO_ONLY_UNAMBIGUOUS = "postprocess/nfo/only_unambiguous"
SET_KEY_NFO_FILEINFO_ENABLED = "postprocess/nfo/fileinfo_enabled"
SET_KEY_NFO_MOVIE_TARGET_NAME = "postprocess/nfo/movie_target_name"
SET_KEY_NFO_CONFLICT_MODE = "postprocess/nfo/conflict_mode"
DEFAULT_NFO_ENABLED = False
DEFAULT_NFO_ONLY_UNAMBIGUOUS = True
DEFAULT_NFO_FILEINFO_ENABLED = True
DEFAULT_NFO_MOVIE_TARGET_NAME = "movie.nfo"
DEFAULT_NFO_CONFLICT_MODE = "skip"

SET_KEY_TRICKPLAY_ENABLED = "postprocess/trickplay/enabled"
SET_KEY_TRICKPLAY_ONLY_MISSING = "postprocess/trickplay/only_missing"
SET_KEY_TRICKPLAY_WIDTH = "postprocess/trickplay/width"
SET_KEY_TRICKPLAY_TILE_COLUMNS = "postprocess/trickplay/tile_columns"
SET_KEY_TRICKPLAY_TILE_ROWS = "postprocess/trickplay/tile_rows"
SET_KEY_TRICKPLAY_INTERVAL_S = "postprocess/trickplay/interval_s"
SET_KEY_TRICKPLAY_JPEG_QUALITY = "postprocess/trickplay/jpeg_quality"
SET_KEY_TRICKPLAY_QSCALE = "postprocess/trickplay/qscale"
SET_KEY_TRICKPLAY_HWACCEL = "postprocess/trickplay/hwaccel"
SET_KEY_TRICKPLAY_MAX_JOBS = "postprocess/trickplay/max_jobs"
SET_KEY_TRICKPLAY_SOURCE_MODE = "postprocess/trickplay/source_mode"
SET_KEY_TRICKPLAY_CONFLICT_MODE = "postprocess/trickplay/conflict_mode"
DEFAULT_TRICKPLAY_ENABLED = False
DEFAULT_TRICKPLAY_ONLY_MISSING = True
DEFAULT_TRICKPLAY_WIDTH = 320
DEFAULT_TRICKPLAY_TILE_COLUMNS = 10
DEFAULT_TRICKPLAY_TILE_ROWS = 10
DEFAULT_TRICKPLAY_INTERVAL_S = 10
DEFAULT_TRICKPLAY_JPEG_QUALITY = 90
DEFAULT_TRICKPLAY_QSCALE = 4
DEFAULT_TRICKPLAY_HWACCEL = "cuda"
DEFAULT_TRICKPLAY_MAX_JOBS = 1
DEFAULT_TRICKPLAY_SOURCE_MODE = "output"
DEFAULT_TRICKPLAY_CONFLICT_MODE = "skip"

__all__ = [name for name in globals() if name.startswith(("SET_KEY_", "DEFAULT_"))]
