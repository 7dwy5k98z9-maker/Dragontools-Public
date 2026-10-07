"""Native Qt behavior for approval, provider context and worker ownership."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QTableWidget, QLabel
from dragontools.gui import movie_renamer_metadata_browser as browser
from dragontools.gui import movie_renamer_resolver as resolver_module
from dragontools.gui.movie_renamer_table_controller import MovieRenamerTableController, RenamerColumns
from dragontools.core.movie_renamer import build_movie_rename_proposal


def _controller(qtbot):
    table = QTableWidget(0, RenamerColumns.HINTS + 1)
    qtbot.addWidget(table)
    controller = MovieRenamerTableController(table)
    controller.add_row(Path('Film.2024.mkv'))
    return controller


@pytest.mark.parametrize('update', ['candidate', 'proposal'])
def test_changed_candidate_or_new_proposal_revokes_old_approval(qtbot, update):
    controller = _controller(qtbot)
    proposal = build_movie_rename_proposal('Film.2024.mkv', resolver=lambda *a: [
        dict(title='Film', year=2024, id=1), dict(title='Film', year=1990, id=2)], show_all_candidates=True)
    controller.on_proposal_ready(0, proposal)
    controller.set_row_accepted(0, True)
    if update == 'candidate':
        controller.apply_candidate(0, 1)
    else:
        controller.on_proposal_ready(0, build_movie_rename_proposal('Film.2024.mkv', resolver=lambda *a: []))
    assert not controller.row_accepted(0)


@pytest.mark.parametrize('route', ['resolve_all', 'resolve_new'])
def test_normal_search_routes_honor_manually_selected_kind_and_query(qtbot, monkeypatch, route):
    controller = _controller(qtbot)
    controller.prepare_manual_search(0, 'Meine Serie', kind='series')
    controller.set_status(0, 'bereit')
    coordinator = resolver_module.MovieRenamerResolveCoordinator(None, None, controller,
        SimpleNamespace(table=controller.table))
    queued = []
    monkeypatch.setattr(coordinator, 'start_jobs', lambda jobs, **kw: queued.extend(jobs))
    getattr(coordinator, route)()
    assert queued[0][2:4] == ('series', 'Meine Serie')


class _Worker(QObject):
    succeeded = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)
    finished = pyqtSignal()
    def __init__(self, token=1, fn=None, parent=None, *, running=False, start_error=False):
        super().__init__(parent)
        self.token = token
        self.running = running
        self.start_error = start_error
    def start(self):
        if self.start_error:
            raise RuntimeError('start failed')
    def isRunning(self):
        return self.running
    def requestInterruption(self):
        pass
    def deleteLater(self):
        pass


def _dialog(monkeypatch):
    from dragontools.gui import movie_renamer_browser_runtime as runtime
    monkeypatch.setattr(browser.RenamerMetadataBrowserService, 'from_settings', lambda *_: object())
    monkeypatch.setattr(browser, 'install_persistent_window_geometry', lambda *a: None)
    monkeypatch.setattr(browser, 'save_window_geometry', lambda *a: None)
    monkeypatch.setattr(runtime, 'save_window_geometry', lambda *a: None)
    return browser.MovieRenamerMetadataBrowserDialog(None)


@pytest.mark.parametrize('running', [False, True])
def test_browser_start_error_restores_controls_and_keeps_live_worker(qtbot, monkeypatch, running):
    dialog = _dialog(monkeypatch)
    qtbot.addWidget(dialog)
    worker = _Worker(running=running, start_error=True)
    monkeypatch.setattr(browser, '_BrowserWorker', lambda *a: worker)
    monkeypatch.setattr(browser.QMessageBox, 'warning', lambda *a: None)
    dialog._start_worker(lambda: None, lambda *a: None, busy_text='START')
    assert dialog._busy is running
    assert dialog.search_btn.isEnabled() is not running
    assert (worker in dialog._workers) is running
    dialog._prepare_dialog_finish()


def test_browser_finished_without_result_releases_busy_state(qtbot, monkeypatch):
    dialog = _dialog(monkeypatch)
    qtbot.addWidget(dialog)
    worker = _Worker()
    monkeypatch.setattr(browser, '_BrowserWorker', lambda *a: worker)
    dialog._start_worker(lambda: None, lambda *a: None, busy_text='START')
    worker.finished.emit()
    assert not dialog._busy and dialog.search_btn.isEnabled()


def test_browser_callbacks_cannot_access_destroyed_native_dialog(qapp, monkeypatch):
    from PyQt6 import sip
    dialog = _dialog(monkeypatch)
    worker = _Worker()
    monkeypatch.setattr(browser, '_BrowserWorker', lambda *a: worker)
    callback = Mock()
    dialog._start_worker(lambda: None, callback, busy_text='START')
    token = dialog._latest_token
    sip.delete(dialog)
    worker.succeeded.emit(token, 'stale')
    callback.assert_not_called()


def test_closed_priority_queue_cannot_replace_physically_running_resolver(qtbot, monkeypatch):
    controller = _controller(qtbot)
    view = SimpleNamespace(table=controller.table, set_busy=lambda *a: None, status_lbl=QLabel())
    coordinator = resolver_module.MovieRenamerResolveCoordinator(None, None, controller, view)
    held = SimpleNamespace(isRunning=lambda: True, enqueue_priority=lambda jobs: 0)
    coordinator.thread = held
    factory = Mock()
    monkeypatch.setattr(resolver_module, 'config_from_settings', lambda *a, **kw: object())
    monkeypatch.setattr(resolver_module, 'MovieRenameResolveThread', factory)
    coordinator.start_jobs([(0, 'Film.2024.mkv', 'movie', 'Film', False, None, None)], automatic=False, priority=True)
    assert coordinator.thread is held
    factory.assert_not_called()


def test_missing_season_prompt_keeps_remakes_separate(qtbot, monkeypatch):
    from dragontools.gui import movie_renamer_season_prompt as module
    from dragontools.gui.movie_renamer_actions import MovieRenamerActionController
    controller = _controller(qtbot)
    controller.table.setRowCount(0)
    for name in ['Ranma (1989) EP01.mkv', 'Ranma (2024) EP01.mkv']:
        controller.add_row(Path(name))
    prompts = []
    def choose(*a, **kw):
        prompts.append(a)
        return len(prompts), True
    monkeypatch.setattr(module.QInputDialog, 'getInt', choose)
    action = MovieRenamerActionController(None, SimpleNamespace(table=controller.table), controller, None)
    assert action.prompt_missing_seasons([0, 1])
    assert len(prompts) == 2
    assert controller.row_season_override(0) == 1
    assert controller.row_season_override(1) == 2


def test_browser_construction_is_visible_and_close_cancels_before_start(qtbot, monkeypatch):
    dialog = _dialog(monkeypatch)
    qtbot.addWidget(dialog)
    worker = _Worker()
    worker.start = Mock()
    def construct(*args):
        owners = dialog.iter_shutdown_workers()
        assert len(owners) == 1 and owners[0].isRunning()
        owners[0].requestInterruption()
        return worker
    monkeypatch.setattr(browser, '_BrowserWorker', construct)
    dialog._start_worker(lambda: None, lambda *a: None, busy_text='START')
    worker.start.assert_not_called()
    assert not dialog._busy


def test_resolver_pending_request_runs_after_owner_finishes_and_stale_finish_is_ignored(qtbot, monkeypatch):
    controller = _controller(qtbot)
    view = SimpleNamespace(table=controller.table, set_busy=Mock(), status_lbl=QLabel())
    coordinator = resolver_module.MovieRenamerResolveCoordinator(None, None, controller, view)
    old = SimpleNamespace(isRunning=lambda: False, enqueue_priority=lambda _: 0)
    coordinator.thread = old
    new = Mock()
    monkeypatch.setattr(resolver_module, 'config_from_settings', lambda *a, **kw: object())
    monkeypatch.setattr(resolver_module, 'MovieRenameResolveThread', Mock(return_value=new))
    coordinator.start_jobs([(0, controller.row_path(0), 'movie', 'Film', False, None, None)], automatic=False, priority=True)
    new.start.assert_not_called()
    coordinator.on_finished(old)
    qtbot.waitUntil(lambda: new.start.call_count == 1)
    assert coordinator.thread is new
    coordinator.on_finished(old)
    assert coordinator.thread is new


def test_finished_notification_does_not_release_a_physically_live_resolver(qtbot, monkeypatch):
    controller = _controller(qtbot)
    view = SimpleNamespace(table=controller.table, set_busy=Mock(), status_lbl=QLabel())
    coordinator = resolver_module.MovieRenamerResolveCoordinator(None, None, controller, view)
    held = SimpleNamespace(isRunning=lambda: True)
    coordinator.thread = held
    coordinator.on_finished(held)
    assert coordinator.thread is held
    view.set_busy.assert_not_called()
    held.isRunning = lambda: False
    coordinator.on_finished(held)
    assert coordinator.thread is None


def test_resolver_start_exception_restores_controls_and_clears_stopped_owner(qtbot, monkeypatch):
    controller = _controller(qtbot)
    view = SimpleNamespace(table=controller.table, set_busy=Mock(), status_lbl=QLabel())
    coordinator = resolver_module.MovieRenamerResolveCoordinator(None, None, controller, view)
    new = Mock(isRunning=Mock(return_value=False), start=Mock(side_effect=RuntimeError('START')))
    monkeypatch.setattr(resolver_module, 'config_from_settings', lambda *a, **kw: object())
    monkeypatch.setattr(resolver_module, 'MovieRenameResolveThread', Mock(return_value=new))
    monkeypatch.setattr(resolver_module.QMessageBox, 'warning', lambda *a: None)
    coordinator.start_jobs([(0, controller.row_path(0), 'movie', 'Film', False, None, None)], automatic=False)
    assert coordinator.thread is None
    assert view.set_busy.call_args.args == (False,)


def test_resolver_constructor_close_cancels_claim_and_never_starts_worker(qtbot, monkeypatch):
    controller = _controller(qtbot)
    view = SimpleNamespace(table=controller.table, set_busy=Mock(), status_lbl=QLabel())
    coordinator = resolver_module.MovieRenamerResolveCoordinator(None, None, controller, view)
    new = Mock(isRunning=Mock(return_value=False))
    def construct(*a):
        owners = coordinator.iter_shutdown_workers()
        assert len(owners) == 1 and owners[0].isRunning()
        coordinator.shutdown()
        return new
    monkeypatch.setattr(resolver_module, 'config_from_settings', lambda *a, **kw: object())
    monkeypatch.setattr(resolver_module, 'MovieRenameResolveThread', construct)
    monkeypatch.setattr(resolver_module.QMessageBox, 'warning', lambda *a: None)
    coordinator.start_jobs([(0, controller.row_path(0), 'movie', 'Film', False, None, None)], automatic=False)
    new.start.assert_not_called()
    assert coordinator.thread is None
