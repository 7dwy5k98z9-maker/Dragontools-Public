from __future__ import annotations

# Compatibility facade: path-mapping persistence and series resolution now live
# in focused implementation modules. Existing imports from media_library_paths
# intentionally continue to work.
from .media_library_path_mappings import (
    _area_from_path_components, _area_from_root, _area_key, _area_label, _has_prefix,
    _join_mapped_path, _mapping_candidates_from_search_bases, _mapping_identity,
    _matches_any_mapping_prefix, _matching_current_mappings, _normalize_slashes,
    _prefix_rest, _unique_mappings, apply_path_mappings, dump_path_mappings,
    get_path_mappings, load_path_mappings, save_path_mappings,
)
from .media_library_series_paths import (
    _match_base, _series_root_candidates_for_current_paths, _series_root_from_db_row,
    find_series_dir_from_settings, find_series_root,
)
from .media_library_movie_paths import find_movie_dir_from_settings, find_movie_root

__all__ = [
    "load_path_mappings", "dump_path_mappings", "save_path_mappings",
    "get_path_mappings", "apply_path_mappings", "find_series_root",
    "find_series_dir_from_settings", "find_movie_root",
    "find_movie_dir_from_settings",
]
