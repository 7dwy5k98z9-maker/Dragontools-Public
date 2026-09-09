from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"


def _class_len(path: Path, class_name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return int(cls.end_lineno or cls.lineno) - cls.lineno + 1


def test_preflight_dialog_is_orchestrator_not_god_class():
    path = GUI / "preflight_dialog.py"
    source = path.read_text(encoding="utf-8")
    assert _class_len(path, "PreFlightDialog") <= 220
    assert "suggest_movie_metadata_for_file" not in source
    assert "suggest_series_metadata_for_name" not in source
    assert "find_series_dir_from_settings" not in source
    assert "find_existing_series_dir" not in source
    assert "QScrollArea" not in source


def test_move_preflight_controller_is_orchestrator_not_god_class():
    path = GUI / "move_preflight_controller.py"
    source = path.read_text(encoding="utf-8")
    assert _class_len(path, "MovePreflightController") <= 180
    for forbidden in (
        "QDialogButtonBox",
        "QInputDialog",
        "QRadioButton",
        "QListWidget",
        "resolve_film_target_for_path",
        "normalize_relative_move_subpath",
    ):
        assert forbidden not in source


def test_preflight_refactor_modules_stay_bounded():
    limits = {
        "preflight_widgets.py": 50,
        "preflight_widget_common.py": 80,
        "preflight_series_widget.py": 430,
        "preflight_film_widget.py": 220,
        "preflight_view.py": 220,
        "preflight_metadata.py": 220,
        "move_preflight_workflow.py": 240,
        "move_lifecycle_coordinator.py": 450,
        "move_request_dialogs.py": 320,
    }
    for name, limit in limits.items():
        lines = (GUI / name).read_text(encoding="utf-8").splitlines()
        assert len(lines) <= limit, f"{name} ist mit {len(lines)} Zeilen wieder zu groß"
