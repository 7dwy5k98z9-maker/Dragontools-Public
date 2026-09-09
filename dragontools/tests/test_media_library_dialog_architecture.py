from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIALOG = ROOT / "gui" / "media_library_dialog.py"
VIEW = ROOT / "gui" / "media_library_dialog_view.py"
SERVICE = ROOT / "gui" / "media_library_dialog_service.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _class(path: Path, name: str) -> ast.ClassDef:
    for node in _tree(path).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"Klasse {name} fehlt in {path.name}")


def test_media_library_dialog_is_thin_orchestrator():
    cls = _class(DIALOG, "MediaLibraryDialog")
    assert cls.end_lineno - cls.lineno + 1 <= 340
    assert max(
        (node.end_lineno - node.lineno + 1)
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
    ) <= 50


def test_dialog_does_not_import_database_search_or_export_implementations():
    forbidden_modules = {
        "media_library_db",
        "media_library_export",
        "media_library_jellyfin",
        "media_library_scan",
        "media_library_search",
    }
    imported = set()
    for node in _tree(DIALOG).body:
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.rsplit(".", 1)[-1])
    assert not (imported & forbidden_modules)


def test_dialog_has_no_direct_sqlite_or_destructive_file_calls():
    forbidden = {"execute_sql", "initialize_database", "cleanup_inactive_media_items", "unlink", "rmtree", "replace"}
    used = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(_tree(DIALOG))
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not (used & forbidden)


def test_view_contains_widget_construction_but_no_core_business_imports():
    tree = _tree(VIEW)
    assert any(isinstance(node, ast.Call) and getattr(node.func, "id", "") == "QGroupBox" for node in ast.walk(tree))
    core_imports = [
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module and ".core" in node.module
    ]
    assert core_imports == []


def test_service_is_qt_independent():
    tree = _tree(SERVICE)
    qt_imports = [
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("PyQt6")
    ]
    assert qt_imports == []


def test_dialog_does_not_mirror_view_widgets_as_legacy_attributes():
    text = DIALOG.read_text(encoding="utf-8")
    assert "_expose_legacy_widget_attributes" not in text
    assert "self.tabs" not in text
    assert "self.db_path_edit" not in text
    assert "self.scan_progress" not in text
