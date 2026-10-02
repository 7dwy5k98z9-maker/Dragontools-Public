from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from types import SimpleNamespace

from dragontools.gui.movie_renamer_season_prompt import MovieRenamerSeasonPromptMixin


class _Item:
    def __init__(self, text: str):
        self._text = text

    def text(self) -> str:
        return self._text


class _TableController:
    class columns:
        TYPE = 0

    def __init__(self):
        self.episode_overrides: dict[int, int] = {}

    def selected_rows(self):
        return [0, 1, 2]

    def row_item(self, row: int, _column: int):
        return _Item("Film" if row == 2 else "Serie")

    def row_episode_override(self, row: int):
        return self.episode_overrides.get(row)

    def row_path(self, row: int):
        return ["Show.S01E03.mkv", "Show.S01E04.mkv", "Movie.2026.mkv"][row]

    def set_row_episode_override(self, row: int, episode: int):
        self.episode_overrides[row] = episode


class _Actions(MovieRenamerSeasonPromptMixin):
    pass


def test_edit_selected_episode_updates_only_series_rows_and_reruns_metadata(monkeypatch):
    table = _TableController()
    rerun_calls: list[list[int]] = []
    view = SimpleNamespace(status_lbl=SimpleNamespace(setText=lambda text: setattr(view, "status", text)))
    actions = _Actions()
    actions.owner = object()
    actions.table_controller = table
    actions.resolver = SimpleNamespace(rerun_rows=lambda rows: rerun_calls.append(list(rows)))
    actions.view = view

    monkeypatch.setattr(
        "dragontools.gui.movie_renamer_season_prompt.QInputDialog.getInt",
        lambda *_args, **_kwargs: (17, True),
    )

    actions.edit_selected_episode()

    assert table.episode_overrides == {0: 17, 1: 17}
    assert rerun_calls == [[0, 1]]
    assert "Episode 17" in view.status
    assert "2 Serien-Datei(en)" in view.status


def test_edit_selected_episode_cancel_keeps_existing_overrides(monkeypatch):
    table = _TableController()
    table.episode_overrides[0] = 9
    actions = _Actions()
    actions.owner = object()
    actions.table_controller = table
    actions.resolver = SimpleNamespace(rerun_rows=lambda _rows: (_ for _ in ()).throw(AssertionError("must not rerun")))
    actions.view = SimpleNamespace(status_lbl=SimpleNamespace(setText=lambda _text: None))

    monkeypatch.setattr(
        "dragontools.gui.movie_renamer_season_prompt.QInputDialog.getInt",
        lambda *_args, **_kwargs: (9, False),
    )

    actions.edit_selected_episode()
    assert table.episode_overrides == {0: 9}
