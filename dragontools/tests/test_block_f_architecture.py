from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _function_size(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return int(node.end_lineno or node.lineno) - node.lineno + 1
    raise AssertionError(f"Funktion {name!r} nicht gefunden in {path}")


def test_media_library_search_remains_orchestrator_sized():
    path = ROOT / "dragontools" / "core" / "media_library_search.py"
    assert _function_size(path, "search_library") <= 80


def test_media_info_text_builder_remains_orchestrator_sized():
    path = ROOT / "dragontools" / "gui" / "media_info_text_builder.py"
    assert _function_size(path, "build_media_info_text") <= 60


def test_move_preflight_uses_existing_shared_ui_helper():
    path = ROOT / "dragontools" / "gui" / "move_preflight_controller.py"
    source = path.read_text(encoding="utf-8")
    assert "from .file_list_utils import set_file_list_item_text" not in source
    assert "from .ui_helpers import set_file_list_item_text" in source
