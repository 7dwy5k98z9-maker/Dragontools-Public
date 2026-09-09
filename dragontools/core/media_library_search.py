from __future__ import annotations

"""Compatibility facade for media-library search.

Search concerns are separated into value classification, path/scope handling,
SQL construction and query orchestration while preserving the original import
location for callers.
"""

from pathlib import Path
from typing import Any

from .media_library_classification import (
    _audio_channels_signature, _audio_codec_signature, _codec_bucket,
    _deviation_value, _dynamic_range_bucket, _find_deviations,
    _has_german_audio, _resolution_bucket,
)
from .media_library_query import (
    _SearchSqlFragments, _append_media_type_filter, _append_preset_filter,
    _append_scope_filter, _append_text_filter, _build_search_query,
    _build_search_sql_fragments, _stream_type_condition,
)
from .media_library_scope import (
    _area_for_path, _mapping_prefixes_for_scope, _path_norm_sql,
    _path_prefix_condition,
)
from .media_library_search_service import search_library as _search_library


def search_library(
    db_path: str | Path,
    preset: str = "all",
    text: str = "",
    limit: int = 500,
    *,
    scope: str = "all",
    media_type: str = "all",
) -> list[dict[str, Any]]:
    """Stable public entry point delegating to the dedicated search service."""
    return _search_library(
        db_path,
        preset,
        text,
        limit,
        scope=scope,
        media_type=media_type,
    )


__all__ = ["search_library"]
