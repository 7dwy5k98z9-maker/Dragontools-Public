"""Compatibility façade for Jellyfin auxiliary metadata import."""
from __future__ import annotations

from .media_library_jellyfin_metadata_loader import (
    kind_from_item_value_type as _kind_from_item_value_type,
    load_jellyfin_auxiliary_metadata,
    split_values as _split_values,
)
from .media_library_jellyfin_metadata_types import JellyfinAuxMetadata, actual as _actual, key as _key
from .media_library_jellyfin_metadata_writer import apply_auxiliary_metadata, apply_collection_metadata

__all__ = [
    "JellyfinAuxMetadata",
    "load_jellyfin_auxiliary_metadata",
    "apply_auxiliary_metadata",
    "apply_collection_metadata",
    "_key",
    "_actual",
    "_split_values",
    "_kind_from_item_value_type",
]
