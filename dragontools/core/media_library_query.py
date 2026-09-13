from __future__ import annotations

"""Compatibility facade and final SELECT builder for media-library search SQL."""

from .media_library_query_filters import NFO_ISSUE_LEVEL_SQL, append_text_filter
from .media_library_query_fragments import (
    _SearchSqlFragments,
    _build_search_sql_fragments,
    _stream_type_condition,
)
from .media_library_query_presets import _append_preset_filter
from .media_library_query_scope_filters import _append_media_type_filter, _append_scope_filter

_append_text_filter = append_text_filter


def _build_search_query(
    where: list[str],
    *,
    deviation_criterion: str,
    sql: _SearchSqlFragments,
    apply_limit: bool = True,
) -> str:
    del sql  # Kept in the signature for compatibility with existing callers/tests.
    query = f"""
        SELECT
            mi.id AS _media_id,
            mi.item_type, mi.title, mi.original_title, mi.series_title, mi.season, mi.episode, mi.year,
            mi.container, mi.duration_s, mi.video_bitrate, mi.overall_bitrate,
            mi.nfo_status, mi.nfo_path, mi.nfo_type, mi.nfo_scanned_at, mi.trickplay_status,
            {NFO_ISSUE_LEVEL_SQL} AS nfo_issue_level,
            mi.video_codec, mi.width, mi.height,
            mi.is_hdr, mi.has_hdr10plus, mi.has_dolby_vision,
            mi.size_bytes, mi.analysis_status, mi.path, mi.parent_path, mi.filename
        FROM media_items mi
        WHERE {' AND '.join(where)}
        ORDER BY coalesce(mi.series_title, mi.title, mi.filename), mi.season, mi.episode
    """
    if not deviation_criterion and apply_limit:
        query += " LIMIT ?"
    return query


__all__ = [
    "_SearchSqlFragments",
    "_append_media_type_filter",
    "_append_preset_filter",
    "_append_scope_filter",
    "_append_text_filter",
    "_build_search_query",
    "_build_search_sql_fragments",
    "_stream_type_condition",
]
