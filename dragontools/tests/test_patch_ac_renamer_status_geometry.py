# -*- coding: utf-8 -*-
import ast
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]


def _source():
    return (PACKAGE / "gui/movie_renamer_view.py").read_text(encoding="utf-8")


def test_renamer_status_label_cannot_force_main_window_width():
    source = _source()
    assert "class RenamerStatusLabel(QLabel):" in source
    assert "return QSize(0, hint.height())" in source
    assert 'RenamerStatusLabel("Bereit.' in source
    marker = 'self.status_lbl = RenamerStatusLabel('
    start = source.index(marker)
    block = source[start:start + 1800]
    assert "self.status_lbl.setWordWrap(True)" in block
    assert "self.status_lbl.setMinimumWidth(0)" in block
    assert "QSizePolicy.Policy.Ignored" in block


def test_status_label_has_bounded_layout_size_hint():
    tree = ast.parse(_source())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RenamerStatusLabel")
    methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    assert {"minimumSizeHint", "sizeHint"} <= methods


def test_rename_jellyfin_status_can_contain_long_fallback_text():
    source = (PACKAGE / "core/jellyfin_refresh_service.py").read_text(encoding="utf-8")
    assert "Gezielte Jellyfin-Aktualisierung fehlgeschlagen" in source
    assert "{exc}" in source


def test_whole_renamer_page_cannot_raise_main_window_minimum_width():
    source = (PACKAGE / "gui/movie_renamer_widget.py").read_text(encoding="utf-8")
    assert "self.setMinimumWidth(0)" in source
    assert "QSizePolicy.Policy.Ignored" in source
    assert "def minimumSizeHint(self) -> QSize:" in source
    assert "return QSize(0, hint.height())" in source
