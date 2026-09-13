from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _class_span(path: Path, class_name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return int(cls.end_lineno or cls.lineno) - cls.lineno + 1


def test_nfo_scan_is_split_into_parser_paths_inventory_and_store() -> None:
    core = PACKAGE / "core"
    limits = {
        "media_library_nfo_scan.py": 160,
        "media_library_nfo_parser.py": 120,
        "media_library_nfo_paths.py": 110,
        "media_library_nfo_inventory.py": 120,
        "media_library_nfo_store.py": 280,
    }
    for name, maximum in limits.items():
        path = core / name
        assert path.exists(), name
        assert _line_count(path) <= maximum, f"{name} ist wieder zu groß"


def test_media_library_query_is_split_by_sql_responsibility() -> None:
    core = PACKAGE / "core"
    limits = {
        "media_library_query.py": 100,
        "media_library_query_fragments.py": 180,
        "media_library_query_presets.py": 260,
        "media_library_query_scope_filters.py": 100,
    }
    for name, maximum in limits.items():
        path = core / name
        assert path.exists(), name
        assert _line_count(path) <= maximum, f"{name} ist wieder zu groß"


def test_trickplay_service_is_orchestrator_not_monolith() -> None:
    worker = PACKAGE / "worker"
    service = worker / "trickplay_service.py"
    assert _line_count(service) <= 280
    assert _class_span(service, "TrickplayGenerator") <= 225
    for name in (
        "trickplay_models.py",
        "trickplay_paths.py",
        "trickplay_ffmpeg.py",
        "trickplay_commit.py",
        "trickplay_concurrency.py",
    ):
        path = worker / name
        assert path.exists(), name
        assert _line_count(path) <= 180, f"{name} ist wieder zu groß"
