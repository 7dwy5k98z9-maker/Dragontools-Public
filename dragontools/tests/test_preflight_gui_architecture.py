from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui"


def test_preflight_dialog_is_orchestrator_not_god_class():
    path = GUI / "preflight_dialog.py"
    source = path.read_text(encoding="utf-8")
    assert "suggest_movie_metadata_for_file" not in source
    assert "suggest_series_metadata_for_name" not in source
    assert "find_series_dir_from_settings" not in source
    assert "find_existing_series_dir" not in source
    assert "QScrollArea" not in source


def test_move_preflight_controller_is_orchestrator_not_god_class():
    path = GUI / "move_preflight_controller.py"
    source = path.read_text(encoding="utf-8")
    for forbidden in (
        "QDialogButtonBox",
        "QInputDialog",
        "QRadioButton",
        "QListWidget",
        "resolve_film_target_for_path",
        "normalize_relative_move_subpath",
    ):
        assert forbidden not in source
