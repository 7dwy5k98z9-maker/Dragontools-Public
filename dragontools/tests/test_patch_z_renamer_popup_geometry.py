from __future__ import annotations

import ast
from pathlib import Path


COMBO = Path(__file__).resolve().parents[1] / "gui" / "movie_renamer_candidate_combo.py"
VIEW = Path(__file__).resolve().parents[1] / "gui" / "movie_renamer_view.py"


def _show_popup_node() -> ast.FunctionDef:
    tree = ast.parse(COMBO.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WideCandidateComboBox":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "showPopup":
                    return child
    raise AssertionError("WideCandidateComboBox.showPopup fehlt")


def test_candidate_popup_does_not_set_view_minimum_width() -> None:
    """Long metadata labels must never enlarge the main-window minimum size."""
    node = _show_popup_node()
    called = {
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    }
    assert "setMinimumWidth" not in called
    assert "setFixedWidth" not in called


def test_candidate_popup_is_resized_only_after_qt_created_it() -> None:
    node = _show_popup_node()
    source = ast.get_source_segment(COMBO.read_text(encoding="utf-8"), node) or ""
    super_pos = source.find("super().showPopup()")
    resize_pos = source.find("popup.resize(")
    assert super_pos >= 0
    assert resize_pos > super_pos
    assert "available.width() - 40" in source


def test_candidate_combo_content_hint_cannot_widen_main_window() -> None:
    source = COMBO.read_text(encoding="utf-8")
    tree = ast.parse(source)
    combo = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WideCandidateComboBox"
    )
    class_source = ast.get_source_segment(source, combo) or ""
    assert "QSizePolicy.Policy.Ignored" in class_source
    assert "def minimumSizeHint" in class_source
    assert "return QSize(0, hint.height())" in class_source
    assert "def sizeHint" in class_source
    assert "_LAYOUT_SIZE_HINT_WIDTH" in class_source


def test_renamer_header_state_is_migrated_and_section_width_is_bounded() -> None:
    source = VIEW.read_text(encoding="utf-8")
    assert '_HEADER_STATE_KEY = "renamer/table_header_state_v2"' in source
    assert "header.setMaximumSectionSize(1200)" in source


def test_rename_table_cannot_lock_main_window_width_after_row_removal() -> None:
    source = VIEW.read_text(encoding="utf-8")
    tree = ast.parse(source)
    table = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RenameTable"
    )
    class_source = ast.get_source_segment(source, table) or ""
    assert "QSizePolicy.Policy.Ignored" in class_source
    assert "def minimumSizeHint" in class_source
    assert "return QSize(0, hint.height())" in class_source
    assert "rowsRemoved.connect(self._schedule_geometry_refresh)" in class_source
    assert "modelReset.connect(self._schedule_geometry_refresh)" in class_source
    assert "QTimer.singleShot(0, self._refresh_geometry_chain)" in class_source
    assert "widget.updateGeometry()" in class_source
    assert "layout.invalidate()" in class_source
