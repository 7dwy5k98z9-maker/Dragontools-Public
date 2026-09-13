from __future__ import annotations

import ast
from pathlib import Path

from dragontools.worker.iso_selection import (
    choose_auto_titles,
    detect_series_episode_titles,
)

PACKAGE = Path(__file__).resolve().parents[1]


def test_iso_series_disc_ignores_play_all_and_short_extra():
    titles = [
        {"id": 1, "duration": 2700, "size": 10},
        {"id": 2, "duration": 2760, "size": 10},
        {"id": 3, "duration": 2640, "size": 10},
        {"id": 10, "duration": 8100, "size": 30},  # Alle abspielen
        {"id": 11, "duration": 420, "size": 1},   # kurzes Extra
    ]

    assert detect_series_episode_titles(titles) == [1, 2, 3]
    assert choose_auto_titles(titles) == ([1, 2, 3], True)


def test_iso_movie_with_unrelated_extras_falls_back_to_main_title():
    titles = [
        {"id": 0, "duration": 7200, "size": 30},
        {"id": 1, "duration": 1800, "size": 5},
        {"id": 2, "duration": 900, "size": 3},
        {"id": 3, "duration": 300, "size": 1},
    ]

    assert detect_series_episode_titles(titles) == []
    assert choose_auto_titles(titles) == ([0], False)


def test_iso_episode_only_disc_detects_all_similar_titles():
    titles = [
        {"id": 1, "duration": 1440, "size": 8},
        {"id": 2, "duration": 1460, "size": 8},
        {"id": 3, "duration": 1420, "size": 8},
        {"id": 4, "duration": 1490, "size": 8},
    ]

    assert detect_series_episode_titles(titles) == [1, 2, 3, 4]


def test_iso_series_detection_can_be_disabled_for_legacy_main_title_behavior():
    titles = [
        {"id": 1, "duration": 2700, "size": 10},
        {"id": 2, "duration": 2720, "size": 10},
        {"id": 9, "duration": 5440, "size": 25},
    ]

    assert choose_auto_titles(titles, detect_series_disc=False) == ([9], False)


def test_iso_series_duration_tolerance_is_configurable():
    titles = [
        {"id": 1, "duration": 1000, "size": 5},
        {"id": 2, "duration": 1180, "size": 5},
    ]

    assert detect_series_episode_titles(titles, duration_tolerance=0.15) == []
    assert detect_series_episode_titles(titles, duration_tolerance=0.20) == [1, 2]


def test_iso_thread_and_widget_keep_series_detection_as_explicit_option():
    thread_source = (PACKAGE / "worker" / "iso_thread.py").read_text(encoding="utf-8")
    widget_source = "\n".join(
        (PACKAGE / "gui" / name).read_text(encoding="utf-8")
        for name in ("iso_widget.py", "iso_widget_view.py", "iso_widget_runtime.py")
    )

    assert "auto_series_disc: bool = True" in thread_source
    assert "detect_series_disc=self.auto_series_disc" in thread_source
    assert 'QCheckBox("Serien-Disc automatisch erkennen")' in widget_source
    assert "auto_series_disc_cb.setChecked(True)" in widget_source
    assert "tid in suggested" in widget_source


def test_renamer_manual_search_can_override_detected_media_type():
    actions_path = PACKAGE / "gui" / "movie_renamer_search_actions.py"
    resolver_path = PACKAGE / "gui" / "movie_renamer_resolve_search.py"
    table_path = PACKAGE / "gui" / "movie_renamer_table_search.py"

    actions = ast.parse(actions_path.read_text(encoding="utf-8"))
    resolver = ast.parse(resolver_path.read_text(encoding="utf-8"))
    table = ast.parse(table_path.read_text(encoding="utf-8"))

    action_cls = next(node for node in actions.body if isinstance(node, ast.ClassDef))
    assert {node.name for node in action_cls.body if isinstance(node, ast.FunctionDef)} >= {
        "manual_series_search", "manual_movie_search", "edit_search_query", "show_all_candidates"
    }

    resolver_cls = next(node for node in resolver.body if isinstance(node, ast.ClassDef))
    resolve_text = ast.unparse(resolver_cls)
    assert "kind='series'" in resolve_text
    assert "kind='movie'" in resolve_text
    assert "for row in sorted(set(rows))" in resolve_text

    table_cls = next(node for node in table.body if isinstance(node, ast.ClassDef))
    selection = next(node for node in table_cls.body if isinstance(node, ast.FunctionDef) and node.name == "manual_series_search_selection")
    selection_text = ast.unparse(selection)
    assert "selected_rows()" in selection_text
    assert "== 'Serie'" not in selection_text
