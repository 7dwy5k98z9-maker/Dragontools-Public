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


def test_main_window_tab_bar_can_shrink_without_forcing_window_width():
    source = (GUI_DIR / "main_window_tabs.py").read_text(encoding="utf-8")

    # Viele lange Tab-Titel dürfen nicht als aufsummierte Mindestbreite bis
    # zum QMainWindow propagiert werden. Bei Platzmangel muss die Tab-Leiste
    # stattdessen scrollen bzw. Text kürzen können.
    assert "def minimumSizeHint(self) -> QSize:" in source
    assert "setUsesScrollButtons(True)" in source
    assert "setElideMode(Qt.TextElideMode.ElideRight)" in source
    assert "QSizePolicy.Policy.Ignored" in source


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


def test_renamer_view_does_not_force_a_wide_main_window_and_has_configurable_columns():
    view_source = (GUI_DIR / "movie_renamer_view.py").read_text(encoding="utf-8")
    view_state_source = (GUI_DIR / "movie_renamer_view_state.py").read_text(encoding="utf-8")
    widget_source = (GUI_DIR / "movie_renamer_widget.py").read_text(encoding="utf-8")

    # Die Aktionsleiste darf nicht wieder alle Renamer-Aktionen in einer
    # einzigen horizontalen Mindestbreite zusammenfassen.
    assert "toolbar = QGridLayout()" in view_source
    assert "toolbar_rows = (" in view_source

    # Tabellenbreiten bleiben Nutzerentscheidung statt Fensterzwang.
    assert "header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)" in view_source
    assert "⚙ Spalten" in view_source
    assert "_HEADER_STATE_KEY = \"renamer/table_header_state_v1\"" in view_source
    assert "hidden_by_default = {self.columns.ACCEPT, self.columns.TYPE, self.columns.HINTS}" in view_state_source

    # Sichtbarkeit, Reihenfolge und Breiten werden über dieselben QSettings
    # persistiert, die der Renamer ohnehin verwendet.
    assert "MovieRenamerView(self, RenamerColumns, self.settings)" in widget_source
