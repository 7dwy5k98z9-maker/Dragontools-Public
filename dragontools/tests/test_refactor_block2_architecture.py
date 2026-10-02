from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def test_nfo_scan_is_split_into_parser_paths_inventory_and_store() -> None:
    core = PACKAGE / "core"
    modules = (
        "media_library_nfo_scan.py",
        "media_library_nfo_parser.py",
        "media_library_nfo_paths.py",
        "media_library_nfo_inventory.py",
        "media_library_nfo_store.py",
    )
    for name in modules:
        path = core / name
        assert path.exists(), name


def test_media_library_query_is_split_by_sql_responsibility() -> None:
    core = PACKAGE / "core"
    modules = (
        "media_library_query.py",
        "media_library_query_fragments.py",
        "media_library_query_presets.py",
        "media_library_query_scope_filters.py",
    )
    for name in modules:
        path = core / name
        assert path.exists(), name


def test_trickplay_service_is_orchestrator_not_monolith() -> None:
    worker = PACKAGE / "worker"
    service = worker / "trickplay_service.py"
    for name in (
        "trickplay_models.py",
        "trickplay_paths.py",
        "trickplay_ffmpeg.py",
        "trickplay_commit.py",
        "trickplay_concurrency.py",
    ):
        path = worker / name
        assert path.exists(), name
