from __future__ import annotations

import ast
from pathlib import Path


GUI_DIR = Path(__file__).resolve().parents[1] / "gui"


def _class(path: Path, name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)


def _methods(cls: ast.ClassDef) -> set[str]:
    return {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}


def test_main_window_is_small_composition_root():
    cls = _class(GUI_DIR / "main_window.py", "MainWindow")
    assert cls.end_lineno - cls.lineno + 1 <= 90
    assert _methods(cls) == {"__init__", "_set_icon", "_restore", "closeEvent"}

    source = (GUI_DIR / "main_window.py").read_text(encoding="utf-8")
    forbidden = {
        "read_active_move_journal",
        "read_active_job_journal",
        "recover_active_move_backups",
        "get_visible_tabs",
        "QTabWidget",
        "ConvertWidget(",
    }
    for token in forbidden:
        assert token not in source


def test_main_window_tab_and_recovery_owners_are_separate_and_bounded():
    tabs = _class(GUI_DIR / "main_window_tabs.py", "MainWindowTabsMixin")
    recovery = _class(GUI_DIR / "main_window_recovery.py", "MainWindowRecoveryMixin")

    tab_methods = _methods(tabs)
    recovery_methods = _methods(recovery)
    assert tab_methods.isdisjoint(recovery_methods)
    assert tabs.end_lineno - tabs.lineno + 1 <= 330
    assert recovery.end_lineno - recovery.lineno + 1 <= 225

    assert {"_init_tabs", "_create_tab_widget", "_apply_tab_visibility", "_handoff_iso_to_converter"} <= tab_methods
    assert {"_show_unfinished_move_journal", "_show_unfinished_job_journal", "_restore_move_resume_plan", "_restore_job_resume_plan"} <= recovery_methods


def test_main_window_legacy_method_surface_is_preserved_across_owners():
    main = _class(GUI_DIR / "main_window.py", "MainWindow")
    tabs = _class(GUI_DIR / "main_window_tabs.py", "MainWindowTabsMixin")
    recovery = _class(GUI_DIR / "main_window_recovery.py", "MainWindowRecoveryMixin")

    combined = _methods(main) | _methods(tabs) | _methods(recovery)
    expected = {
        "__init__", "_set_icon", "_init_tabs", "_make_placeholder", "_on_tab_activate",
        "_ensure_tab_loaded", "_tab_label", "_create_tab_widget", "_on_tab_close",
        "_close_current_tab", "_reopen_last_tab", "_reopen_all_tabs", "_reopen_tab",
        "_set_tab_visible_setting", "_toggle_tab", "_open_tab_manager", "_apply_tab_visibility",
        "_maybe_show_recovery_journals", "_maybe_show_unfinished_job_journal",
        "_show_unfinished_move_journal", "_maybe_show_replacement_reminders",
        "_open_unfinished_job_journal", "_open_unfinished_move_journal",
        "_show_unfinished_job_journal", "_restore_move_resume_plan", "_restore_job_resume_plan",
        "_ensure_converter_widget", "_handoff_iso_to_converter", "_open_movie_renamer_tab",
        "_open_quality_tester_tab", "_open_audio_video_matcher_tab", "_restore", "closeEvent",
    }
    assert combined == expected
