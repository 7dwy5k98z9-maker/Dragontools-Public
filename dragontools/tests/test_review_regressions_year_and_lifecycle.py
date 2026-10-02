from pathlib import Path
from types import SimpleNamespace
import queue
import sys
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QTableWidget

from dragontools.core.movie_renamer import build_rename_proposal
from dragontools.core.renamer_candidate_decision import apply_candidate_decision
from dragontools.gui.movie_renamer_table_controller import MovieRenamerTableController, RenamerColumns
from dragontools.worker.tool_runner import _dispatch_callbacks, run_tool


@pytest.mark.parametrize('kind', ['movie', 'series'])
@pytest.mark.parametrize('year', [None, 1990, 2024])
def test_provider_year_is_evidence_not_search_echo(kind, year):
    raw = {'title': 'Example', 'series': 'Example', 'season': 1, 'episode': 1,
           'episode_title': 'Pilot', 'year': year}
    proposal = build_rename_proposal('Example.S01E01.mkv' if kind == 'series' else 'Example.mkv',
        year_override=2024, movie_resolver=lambda *a: [raw], series_resolver=lambda *a: [raw])
    assert proposal.selected.year == year
    assert proposal.can_auto_accept is (year == 2024)
    reapplied = apply_candidate_decision(proposal, 0, proposal.source_path).proposal
    assert reapplied.can_auto_accept is (year == 2024)
    assert any('Provider-Jahr' in w for w in reapplied.warnings) is (year != 2024)


def test_series_remake_beats_old_series_and_candidate_switch_stays_safe():
    rows = [dict(series='Example', season=1, episode=1, episode_title='Pilot', year=y) for y in (1990, 2024)]
    proposal = build_rename_proposal('Example.S01E01.mkv', year_override=2024,
                                    series_resolver=lambda *a: rows, minimum_score_override=0.8)
    assert proposal.selected.year == 2024
    old_index = next(i for i, c in enumerate(proposal.candidates) if c.year == 1990)
    old = apply_candidate_decision(proposal, old_index, proposal.source_path).proposal
    assert not old.can_auto_accept
    current_index = next(i for i, c in enumerate(old.candidates) if c.year == 2024)
    current = apply_candidate_decision(old, current_index, old.source_path).proposal
    assert not any('Provider-Jahr' in w for w in current.warnings)


@pytest.mark.parametrize('kind', ['episode_object', 'series_object', 'dict'])
def test_missing_provider_year_is_not_fabricated(kind):
    from dragontools.core.movie_renamer_candidate_mapping import _series_candidate_from_result
    from dragontools.core.movie_renamer import parse_series_release_name
    parsed = parse_series_release_name('Example.2024.S01E01.mkv')
    values = {'episode_object': SimpleNamespace(season_number=1, episode_number=1, show_name='Example', title='Pilot'),
              'series_object': SimpleNamespace(name='Example', first_air_year=None),
              'dict': {'series': 'Example', 'episode_title': 'Pilot'}}
    candidate = _series_candidate_from_result(values[kind], parsed)
    assert candidate.year is None
    assert candidate.score < 0.9


def test_alias_rule_cannot_override_year_safety():
    from dragontools.core.movie_renamer_candidate_mapping import _series_candidate_from_result
    from dragontools.core.movie_renamer import parse_series_release_name
    parsed = parse_series_release_name('Alias.2024.S01E01.mkv')
    candidate = _series_candidate_from_result({'series': 'Example', 'episode_title': 'Pilot', 'year': 1990},
                                               parsed, title_exception=lambda _: 'Example')
    assert candidate.score < 0.9


@pytest.fixture
def table_controller(qtbot):
    table = QTableWidget(0, RenamerColumns.HINTS + 1)
    qtbot.addWidget(table)
    controller = MovieRenamerTableController(table)
    controller.add_row(Path('Example.S01E01.mkv'))
    controller.set_row_accepted(0, True)
    controller.set_item(0, RenamerColumns.TARGET, 'Old.mkv', editable=True)
    return controller


@pytest.mark.parametrize('edit', ['query', 'season', 'episode', 'year'])
def test_every_search_edit_revokes_approval_and_target(table_controller, edit):
    c = table_controller
    if edit == 'query':
        c.prepare_manual_search(0, 'New', kind='series')
    else:
        getattr(c, f'set_row_{edit}_override')(0, 2024 if edit == 'year' else 2)
    assert not c.row_accepted(0)
    assert c.target_name(0) == ''
    assert c.row_proposal(0) is None
    proposal = build_rename_proposal('Example.S01E01.mkv', series_resolver=lambda *a: [])
    c.on_proposal_ready(0, proposal)
    assert not c.row_accepted(0)


@pytest.mark.parametrize('status', ['✅', '❌', '⚠️', '⏭️'])
@pytest.mark.parametrize('remove', [False, True])
@pytest.mark.parametrize('more_pending', [False, True])
def test_last_postprocess_result_finishes_even_when_removed(status, remove, more_pending):
    from dragontools.tests.test_conversion_result_service import _service
    service, state, *_ = _service()
    service._set_file_list_item_text = lambda *a: None
    service._ui.file_list = SimpleNamespace(remove_path=lambda *a: None)
    state.pending_postprocess_inputs.add('input.mkv')
    if more_pending:
        state.pending_postprocess_inputs.add('other.mkv')
    if remove:
        state.pending_remove_paths.add('input.mkv')
    state.finish_waiting_for_postprocess = True
    finished = []
    service.on_finished = lambda: finished.append(True)
    service.on_file_result('input.mkv', 'output.mkv', status)
    assert len(finished) == int(not more_pending)
    assert state.finish_waiting_for_postprocess is more_pending
    service.on_file_result('input.mkv', 'output.mkv', status)
    assert len(finished) == int(not more_pending)


def test_callback_dispatch_yields_even_if_queue_refills():
    pending = queue.Queue()
    seen = []
    def callback(text):
        seen.append(text)
        if len(seen) < 100:
            pending.put((callback, text))
    pending.put((callback, 'line'))
    _dispatch_callbacks(pending, label='test', log=None)
    assert 0 < len(seen) <= 32
    assert not pending.empty()


@pytest.mark.parametrize('abort', [False, True])
def test_output_flood_cannot_starve_timeout_or_abort(monkeypatch, abort):
    monkeypatch.setattr('dragontools.worker.tool_process_lifecycle.mark_activity', lambda *a, **kw: None)
    worker = SimpleNamespace(abort_requested=False)
    def callback(_line):
        if abort:
            worker.abort_requested = True
        time.sleep(0.005)
    result = run_tool([sys.executable, '-B', '-u', '-c',
        'import time\nfor i in range(500):\n print(i,flush=True)\n time.sleep(0.003)'],
        timeout_s=10 if abort else 0.1, worker=worker, abort_on_request=True, stdout_line=callback)
    assert result.aborted if abort else result.timed_out
    assert not result.ok


@pytest.mark.parametrize('key, expected_renames', [(Qt.Key.Key_Return, 1), (Qt.Key.Key_Escape, 0)])
def test_rename_dialog_enter_confirms_escape_cancels(qtbot, monkeypatch, table_controller, key, expected_renames):
    from dragontools.gui import movie_renamer_actions as actions_module
    c = table_controller
    calls = []
    monkeypatch.setattr(actions_module, 'rename_movie_file', lambda *a: calls.append(a) or Path('New.mkv'))
    monkeypatch.setattr(actions_module, 'dispatch_after_rename', lambda *a, **kw: None)
    seen_defaults = []
    timer = QTimer()
    def answer():
        box = QApplication.activeModalWidget()
        if isinstance(box, QMessageBox):
            timer.stop()
            seen_defaults.append(box.standardButton(box.defaultButton()))
            qtbot.keyClick(box, key)
    timer.timeout.connect(answer)
    timer.start(20)
    action = actions_module.MovieRenamerActionController(None, SimpleNamespace(table=c.table, status_lbl=QLabel()), c, None)
    try:
        action.execute_rename()
    finally:
        timer.stop()
    assert seen_defaults == [QMessageBox.StandardButton.Yes]
    assert len(calls) == expected_renames
