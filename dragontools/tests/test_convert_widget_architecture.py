from __future__ import annotations

import ast
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"


def _module(name: str):
    path = GUI_DIR / name
    return path, ast.parse(path.read_text(encoding="utf-8"))


def test_convert_widget_has_no_desktop_or_preflight_business_dependencies():
    _path, tree = _module("convert_widget.py")
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)

    forbidden = {
        "os",
        "subprocess",
        "sys",
        "pathlib",
        "QMessageBox",
        "build_batch_preflight_rows",
        "ProfileManager",
        "EncoderProfileService",
        "ConversionController",
        "ConversionResultService",
        "MovePreflightController",
    }
    assert not (imported & forbidden)


def test_convert_widget_collaborators_stay_focused():
    modules = (
        "convert_widget_composition.py",
        "convert_widget_recovery.py",
        "convert_widget_runtime_ui.py",
        "convert_widget_paths.py",
        "convert_widget_host_actions.py",
    )
    for name in modules:
        path = GUI_DIR / name
        assert path.exists(), name


def test_convert_widget_paths_own_codec_specific_settings_constants():
    owners: set[str] = set()
    for path in GUI_DIR.glob("convert_widget*.py"):
        source = path.read_text(encoding="utf-8")
        if "SET_KEY_PATH_H265_TV" in source or "SET_KEY_PATH_AV1_TV" in source:
            owners.add(path.name)
    assert owners == {"convert_widget_paths.py"}


def test_convert_widget_does_not_own_preflight_builder():
    owners: set[str] = set()
    for path in GUI_DIR.glob("convert_widget*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "build_batch_preflight_rows":
                owners.add(path.name)
    assert "convert_widget.py" not in owners
    assert "convert_widget_recovery.py" in owners
