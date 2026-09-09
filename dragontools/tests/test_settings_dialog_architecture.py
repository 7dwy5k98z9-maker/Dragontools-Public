# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "dragontools" / "gui"
SECTIONS = GUI / "settings_sections"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _method_span(path: Path, class_name: str, method_name: str) -> int:
    tree = _tree(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return int(child.end_lineno or child.lineno) - child.lineno + 1
    raise AssertionError(f"{class_name}.{method_name} fehlt in {path}")


def _literal_tuple_assignment(path: Path, class_name: str, name: str) -> tuple[str, ...]:
    tree = _tree(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.Assign):
                    if any(isinstance(target, ast.Name) and target.id == name for target in child.targets):
                        return tuple(ast.literal_eval(child.value))
    raise AssertionError(f"{class_name}.{name} fehlt in {path}")


def _section_titles() -> set[str]:
    path = GUI / "settings_dialog.py"
    tree = _tree(path)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog":
            for child in node.body:
                if isinstance(child, ast.Assign):
                    if any(isinstance(target, ast.Name) and target.id == "SECTION_TITLES" for target in child.targets):
                        return set(ast.literal_eval(child.value))
    raise AssertionError("SettingsDialog.SECTION_TITLES fehlt")


def test_settings_dialog_is_orchestrator_not_god_class() -> None:
    path = GUI / "settings_dialog.py"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 220
    assert _method_span(path, "SettingsDialog", "_init_ui") <= 30
    assert _method_span(path, "SettingsDialog", "_load") <= 10
    assert _method_span(path, "SettingsDialog", "_save") <= 30
    text = "\n".join(lines)
    assert "QGroupBox(" not in text
    assert "SET_KEY_" not in text


def test_settings_sections_cover_every_visible_section_exactly_once() -> None:
    classes = {
        "storage.py": "StorageLoggingSection",
        "runtime.py": "RuntimeToolsSection",
        "media.py": "MediaPostprocessSection",
        "video.py": "VideoAnalysisSection",
        "safety.py": "SafetyValidationSection",
    }
    seen: list[str] = []
    for filename, class_name in classes.items():
        path = SECTIONS / filename
        assert path.is_file()
        keys = _literal_tuple_assignment(path, class_name, "section_keys")
        seen.extend(keys)
        for method in ("build", "load", "save"):
            assert _method_span(path, class_name, method) > 0
    assert len(seen) == len(set(seen)), "Ein sichtbarer Settings-Bereich besitzt mehrere Owner"
    assert set(seen) == _section_titles()


def test_no_replacement_god_section_was_created() -> None:
    classes = {
        "storage.py": "StorageLoggingSection",
        "runtime.py": "RuntimeToolsSection",
        "media.py": "MediaPostprocessSection",
        "video.py": "VideoAnalysisSection",
        "safety.py": "SafetyValidationSection",
    }
    for filename, class_name in classes.items():
        path = SECTIONS / filename
        assert len(path.read_text(encoding="utf-8").splitlines()) <= 380
        assert _method_span(path, class_name, "build") <= 240
        assert _method_span(path, class_name, "load") <= 100
        assert _method_span(path, class_name, "save") <= 100


def test_settings_dialog_uses_public_collaborator_helpers_without_private_aliases() -> None:
    path = GUI / "settings_dialog.py"
    tree = _tree(path)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    public = {
        "browse_media_library_db", "open_media_library_dialog", "open_timeout_settings",
        "sync_autocrop_mode", "cleanup_logs", "auto_detect", "auto_detect_all",
    }
    assert public <= methods
    assert not {f"_{name}" for name in public} & methods


def test_output_container_has_direct_settings_menu_entry() -> None:
    menu_text = (GUI / "main_window_menus.py").read_text(encoding="utf-8")
    actions_text = (GUI / "main_window_settings_actions.py").read_text(encoding="utf-8")

    assert 'QAction("📦 Ausgabecontainer"' in menu_text
    assert "triggered=self._open_settings_containers" in menu_text
    assert "def _open_settings_containers(self):" in actions_text
    assert 'visible_sections=("containers",)' in actions_text
