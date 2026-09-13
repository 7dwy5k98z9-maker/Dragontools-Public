from __future__ import annotations

"""Kompatibilitätsfassade für Mediathek-Schreiboperationen."""

from .media_library_repository_items import (
    _average_bitrate,
    _fallback_item_from_path,
    _insert_item,
    _item_from_media_info,
    _streams_from_media_info,
    _streams_from_media_info_with_sidecars,
    record_media_file,
)
from .media_library_repository_moves import (
    _deactivate_existing_episode_identity,
    _deactivate_paths,
    record_moved_file,
    record_moved_file_from_settings,
)
from .media_library_sidecars import (
    _language_from_sidecar_name,
    _nfo_status_for_path,
    _subtitle_sidecar_streams,
    _trickplay_status_for_path,
)

__all__ = [
    "record_media_file", "record_moved_file", "record_moved_file_from_settings",
]
