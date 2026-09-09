from __future__ import annotations

"""Stable public facade for the DragonTools media-library subsystem.

The implementation is split by responsibility. Existing callers may continue
importing the documented API from :mod:`dragontools.core.media_library`.
"""

from .media_library_db import (
    backup_database,
    cleanup_inactive_media_items,
    execute_sql,
    get_stats,
    initialize_database,
    normalize_database_stream_types,
)
from .media_library_export import (
    export_database,
    export_database_to_csv,
    export_media_overview_to_csv,
    export_search_results_to_csv,
)
from .media_library_jellyfin import import_jellyfin_database
from .media_library_paths import (
    apply_path_mappings,
    dump_path_mappings,
    find_series_dir_from_settings,
    find_series_root,
    get_path_mappings,
    load_path_mappings,
    save_path_mappings,
)
from .media_library_repository import (
    record_media_file,
    record_moved_file,
    record_moved_file_from_settings,
)
from .media_library_scan import scan_storage_paths_to_database
from .media_library_search import search_library
from .media_library_types import (
    DEFAULT_DB_FILENAME,
    SCHEMA_VERSION,
    LibraryImportResult,
    LibraryScanResult,
    LibraryStats,
    PathMapping,
    default_media_library_db_path,
    default_media_library_dir,
    describe_series_path_resolution,
)

__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_DB_FILENAME",
    "PathMapping",
    "LibraryStats",
    "LibraryImportResult",
    "LibraryScanResult",
    "describe_series_path_resolution",
    "default_media_library_dir",
    "default_media_library_db_path",
    "initialize_database",
    "backup_database",
    "export_database",
    "export_database_to_csv",
    "export_media_overview_to_csv",
    "export_search_results_to_csv",
    "load_path_mappings",
    "dump_path_mappings",
    "save_path_mappings",
    "get_path_mappings",
    "apply_path_mappings",
    "get_stats",
    "normalize_database_stream_types",
    "cleanup_inactive_media_items",
    "record_media_file",
    "record_moved_file",
    "record_moved_file_from_settings",
    "scan_storage_paths_to_database",
    "import_jellyfin_database",
    "execute_sql",
    "search_library",
    "find_series_root",
    "find_series_dir_from_settings",
]
