from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QLabel, QTableWidget

from dragontools.core.movie_renamer import build_rename_proposal
from dragontools.core.movie_renamer_year_override import normalize_year_override
from dragontools.gui.movie_renamer_actions import MovieRenamerActionController
from dragontools.gui.movie_renamer_resolve_search import MovieRenamerResolveSearchMixin
from dragontools.gui.movie_renamer_table_controller import MovieRenamerTableController, RenamerColumns
from dragontools.gui import movie_renamer_year_edit as ui


@pytest.mark.parametrize("value", [True, False, 2024.5, 2024.0, "abcd", "20", "20240", "-2024", "２０２４", 1799, 2200])
def test_invalid_year(value):
    with pytest.raises(ValueError):
        normalize_year_override(value)


@pytest.mark.parametrize("value, expected", [(None, None), ("", None), ("  ", None), (" 2024 ", 2024), (1800, 1800), (2199, 2199)])
def test_valid_year(value, expected):
    assert normalize_year_override(value) == expected


@pytest.mark.parametrize("kind, filename", [("movie", "Dune.1984.mkv"), ("series", "Dune.1984.S01E02.mkv")])
@pytest.mark.parametrize("year", [None, 2021])
def test_year_reaches_lookup_with_other_overrides(kind, filename, year):
    calls = []
    def resolver(*args):
        calls.append(args)
        return []
    proposal = build_rename_proposal(filename, force_kind=kind, movie_resolver=resolver,
                                    series_resolver=resolver, year_override=year,
                                    series_season_override=3, series_episode_override=7)
    assert calls
    assert all(args[-1] == (year or 1984) for args in calls)
    assert proposal.parsed.year == (year or 1984)
    if kind == "series":
        assert calls[0][1:3] == (3, 7)


def test_correct_remake_is_selected():
    proposal = build_rename_proposal("Dune.1984.mkv", year_override=2021,
        movie_resolver=lambda *_: [
            {"title": "Dune", "release_date": "1984-01-01", "id": 1},
            {"title": "Dune", "release_date": "2021-01-01", "id": 2},
        ])
    assert proposal.selected.year == 2021
    assert proposal.target_name == "Dune (2021).mkv"


@pytest.fixture
def controller(qtbot):
    table = QTableWidget(0, RenamerColumns.HINTS + 1)
    qtbot.addWidget(table)
    result = MovieRenamerTableController(table)
    from pathlib import Path
    result.add_row(Path("Dune.1984.mkv"))
    result.add_row(Path("Dune.2000.S01E02.mkv"))
    return result


@pytest.mark.parametrize("value, ok, expected_calls", [("2021", True, 1), ("", True, 1), ("abc", True, 0), ("2021", False, 0)])
def test_batch_edit_reset_invalid_and_cancel(controller, monkeypatch, value, ok, expected_calls):
    controller.set_row_year_override(0, 2020)
    controller.set_row_accepted(0, True)
    controller.set_item(0, RenamerColumns.TARGET, "old.mkv", editable=True)
    monkeypatch.setattr(controller, "selected_rows", lambda: [0, 1])
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *a, **kw: (value, ok))
    warnings = []
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *a: warnings.append(a))
    calls = []
    action = MovieRenamerActionController(None, SimpleNamespace(status_lbl=QLabel()), controller,
                                         SimpleNamespace(rerun_rows=lambda rows: calls.append(rows)))
    action.edit_selected_year()
    assert len(calls) == expected_calls
    if expected_calls:
        assert calls == [[0, 1]]
        assert controller.row_year_override(0) == (2021 if value else None)
        assert controller.row_year_override(1) == (2021 if value else None)
        assert not controller.row_accepted(0)
        assert controller.target_name(0) == ""
        assert controller.row_item(0, RenamerColumns.YEAR).text() == (value or "1984")
    else:
        assert controller.row_year_override(0) == 2020
        assert controller.row_accepted(0)
    assert bool(warnings) == (ok and value == "abc")


def test_no_selection_does_not_open_dialog(controller, monkeypatch):
    messages = []
    monkeypatch.setattr(ui.QMessageBox, "information", lambda *a: messages.append(a))
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *a, **kw: pytest.fail("No selection"))
    MovieRenamerActionController(None, None, controller, None).edit_selected_year()
    assert len(messages) == 1


def test_year_snapshot_and_reset_reject_old_results(controller, monkeypatch):
    harness = MovieRenamerResolveSearchMixin()
    harness.table_controller = controller
    harness._request_versions = {}
    job = (0, controller.row_path(0), "movie", "Dune", False, None, None)
    controller.set_row_year_override(0, 2021)
    first = harness._version_jobs([job])[0]
    controller.set_row_year_override(0, None)
    second = harness._version_jobs([job])[0]
    assert first[7] == 2021
    assert second[-1] > first[-1]
    applied = []
    monkeypatch.setattr(controller, "on_proposal_ready", lambda *args: applied.append(args))
    harness.on_proposal_ready(job[1], first[-1], "stale")
    harness.on_proposal_ready(job[1], second[-1], "fresh")
    assert applied == [(0, "fresh")]


@pytest.mark.parametrize("year", [None, 2021])
def test_worker_passes_year(qtbot, monkeypatch, year):
    from dragontools.gui import movie_renamer_resolver as worker_module
    calls = []
    monkeypatch.setattr(worker_module, "client_from_config", lambda *args: object())
    monkeypatch.setattr(worker_module, "build_rename_proposal", lambda *args, **kwargs: calls.append(kwargs))
    base = (0, "Dune.1984.mkv", "movie", "Dune", False, None, None)
    job = (*base, 1) if year is None else (*base, year, 1)
    worker = worker_module.MovieRenameResolveThread([job], None)
    worker.run()
    assert len(calls) == 1
    assert calls[0]["year_override"] == year


@pytest.mark.parametrize("route", ["resolve_all", "resolve_new", "rerun_rows", "resolve_all_candidates", "resolve_movie_query", "resolve_series_query"])
def test_every_search_route_snapshots_year(controller, monkeypatch, route):
    from dragontools.gui.movie_renamer_resolver import MovieRenamerResolveCoordinator
    coordinator = MovieRenamerResolveCoordinator(None, None, controller, SimpleNamespace(table=controller.table))
    controller.set_row_year_override(0, 2021)
    queued = []
    monkeypatch.setattr(coordinator, "start_jobs", lambda jobs, **kw: queued.extend(coordinator._version_jobs(jobs)))
    args = () if route in ("resolve_all", "resolve_new") else ([0],)
    if route in ("resolve_movie_query", "resolve_series_query"):
        args = ([0], "Dune")
    getattr(coordinator, route)(*args)
    assert queued[0][7] == 2021
    assert queued[0][-1] == 1


def test_year_button_is_wired_and_available_during_search(qtbot, monkeypatch):
    from pathlib import Path
    from dragontools.gui import movie_renamer_widget as widget_module
    monkeypatch.setattr(widget_module, "QSettings", lambda *a: None)
    widget = widget_module.MovieRenamerWidget()
    qtbot.addWidget(widget)
    widget._table_controller.add_row(Path("Dune.1984.mkv"))
    widget.table.selectRow(0)
    monkeypatch.setattr(ui.QInputDialog, "getText", lambda *a, **kw: ("2021", True))
    calls = []
    monkeypatch.setattr(widget._resolver, "rerun_rows", lambda rows: calls.append(rows))
    widget._view.set_busy(True)
    assert widget.edit_year_btn.isEnabled()
    assert not widget.rename_btn.isEnabled()
    widget.edit_year_btn.click()
    assert calls == [[0]]
    assert widget._table_controller.row_year_override(0) == 2021
