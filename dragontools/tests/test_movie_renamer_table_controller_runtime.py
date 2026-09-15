from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QLabel, QTableWidget

from dragontools.core.path_syntax import path_compare_key
from dragontools.gui.movie_renamer_actions import MovieRenamerActionController
from dragontools.gui.movie_renamer_table_controller import MovieRenamerTableController, RenamerColumns


def _controller(qtbot) -> MovieRenamerTableController:
    table = QTableWidget(0, RenamerColumns.HINTS + 1)
    qtbot.addWidget(table)
    return MovieRenamerTableController(table)


def _add_source(controller: MovieRenamerTableController, path: Path) -> int:
    path.write_bytes(b"video")
    controller.add_row(path)
    return controller.table.rowCount() - 1


def test_collect_rename_problems_detects_duplicate_target_names(tmp_path, qtbot):
    controller = _controller(qtbot)
    row_a = _add_source(controller, tmp_path / "A.mkv")
    row_b = _add_source(controller, tmp_path / "B.mkv")
    controller.set_item(row_a, controller.columns.TARGET, "gleich.mkv", editable=True)
    controller.set_item(row_b, controller.columns.TARGET, "gleich.mkv", editable=True)

    problems = controller.collect_rename_problems([row_a, row_b])

    assert any("Zielname mehrfach" in problem for problem in problems)


def test_collect_rename_problems_detects_existing_target(tmp_path, qtbot):
    controller = _controller(qtbot)
    row = _add_source(controller, tmp_path / "Quelle.mkv")
    (tmp_path / "Vorhanden.mkv").write_bytes(b"existing")
    controller.set_item(row, controller.columns.TARGET, "Vorhanden.mkv", editable=True)

    problems = controller.collect_rename_problems([row])

    assert any("Ziel existiert bereits" in problem for problem in problems)


@pytest.mark.skipif(os.name != "nt", reason="Windows-Dateisystemsemantik wird im Windows-CI geprüft")
def test_collect_rename_problems_allows_case_only_rename_of_same_source(tmp_path, qtbot):
    controller = _controller(qtbot)
    source = tmp_path / "Film.mkv"
    row = _add_source(controller, source)
    controller.set_item(row, controller.columns.TARGET, "film.mkv", editable=True)

    assert controller.collect_rename_problems([row]) == []


def test_known_path_keys_normalizes_windows_slash_variants(qtbot):
    controller = _controller(qtbot)
    controller.add_row(Path("placeholder.mkv"))
    controller.set_row_path(0, r"C:\\Media\\Anime\\Folge.mkv")

    keys = controller.known_path_keys()

    assert path_compare_key("C:/Media/Anime/Folge.mkv") in keys


def test_actions_controller_does_not_add_same_file_twice(tmp_path, qtbot):
    controller = _controller(qtbot)
    source = tmp_path / "Episode.mkv"
    source.write_bytes(b"video")
    view = SimpleNamespace(status_lbl=QLabel(), table=controller.table)
    resolver = SimpleNamespace(calls=0)
    resolver.schedule_new = lambda: setattr(resolver, "calls", resolver.calls + 1)
    actions = MovieRenamerActionController(None, view, controller, resolver)

    actions.add_paths([str(source), str(source)])

    assert controller.table.rowCount() == 1
    assert resolver.calls == 1
    assert view.status_lbl.text().startswith("1 Datei(en) hinzugefügt")
