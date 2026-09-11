from __future__ import annotations

import ast
from pathlib import Path

import dragontools.core.media_library as media_library


def test_media_library_facade_preserves_public_api() -> None:
    expected = {
        "SCHEMA_VERSION",
        "DEFAULT_DB_FILENAME",
        "PathMapping",
        "LibraryStats",
        "LibraryImportResult",
        "LibraryLightScanResult",
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
        "scan_nfo_inventory",
        "import_jellyfin_database",
        "execute_sql",
        "search_library",
        "find_series_root",
        "find_series_dir_from_settings",
    }
    assert set(media_library.__all__) == expected
    for name in expected:
        assert hasattr(media_library, name), name


def test_media_library_facade_contains_no_business_logic() -> None:
    path = Path(media_library.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def test_media_library_implementation_is_split_by_responsibility() -> None:
    core = Path(media_library.__file__).parent
    expected_modules = {
        "media_library_db.py",
        "media_library_export.py",
        "media_library_jellyfin.py",
        "media_library_paths.py",
        "media_library_repository.py",
        "media_library_scan.py",
        "media_library_search.py",
        "media_library_types.py",
        "media_library_utils.py",
    }
    modules = {path.name: path for path in core.glob("media_library_*.py")}
    assert expected_modules <= set(modules)
    assert len(Path(media_library.__file__).read_text(encoding="utf-8").splitlines()) < 120
    assert max(len(path.read_text(encoding="utf-8").splitlines()) for path in modules.values()) < 700
