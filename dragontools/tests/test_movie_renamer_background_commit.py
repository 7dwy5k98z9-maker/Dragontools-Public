"""Native Qt regressions for slow, safe rename transactions."""
from pathlib import Path
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QSettings, QThread, QTimer
from PyQt6.QtWidgets import QMessageBox

from dragontools.gui import movie_renamer_actions as actions_module
from dragontools.gui import movie_renamer_widget as widget_module
from dragontools.gui.application_shutdown import collect_shutdown_workers, shutdown_workers
from dragontools.gui.movie_renamer_commit_runtime import MovieRenameCommitThread


@pytest.fixture
def renamer(qtbot, monkeypatch, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(widget_module, "QSettings", lambda *_args: settings)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    refreshed = []
    monkeypatch.setattr(actions_module, "dispatch_after_rename", lambda paths, *_args, **_kw: refreshed.extend(paths))
    widget = widget_module.MovieRenamerWidget()
    qtbot.addWidget(widget)
    widget.show()
    gates = []
    yield widget, refreshed, gates
    for gate in gates:
        gate.set()
    worker = widget._actions.commit.thread
    if worker is not None:
        worker.requestInterruption()
        assert worker.wait(5000)
        qtbot.waitUntil(lambda: not widget._actions.commit.busy)


def add_file(widget, tmp_path, name="Film.mkv"):
    source = tmp_path / name
    source.write_bytes(b"original video content")
    controller = widget._table_controller
    row = controller.add_row(source)
    controller.set_item(row, controller.columns.TARGET, "New " + name, editable=True)
    controller.set_row_accepted(row, True)
    return source, source.with_name("New " + name)


def test_slow_rename_runs_off_gui_thread_and_gui_keeps_ticking(renamer, qtbot, monkeypatch, tmp_path):
    widget, refreshed, gates = renamer
    source, target = add_file(widget, tmp_path)
    entered, release = threading.Event(), threading.Event()
    gates.append(release)
    original = actions_module.rename_movie_file
    checking_threads = []

    def slow_rename(source, target_name):
        checking_threads.append(QThread.currentThread())
        entered.set()
        assert release.wait(5)
        return original(source, target_name)

    monkeypatch.setattr(actions_module, "rename_movie_file", slow_rename)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(10)
    try:
        widget.execute_rename()
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        assert widget._actions.commit.busy
        assert not widget.table.isEnabled()
        assert not widget.rename_btn.isEnabled()
        assert source.exists() and not target.exists()
        assert "1/1:" in widget.status_lbl.text()
        assert all(thread is not widget.thread() for thread in checking_threads)
        widget.execute_rename()
        widget.clear()
        widget.add_paths([str(tmp_path / "Another.mkv")])
        assert widget.table.rowCount() == 1
        release.set()
        qtbot.waitUntil(lambda: not widget._actions.commit.busy)
    finally:
        timer.stop()
    assert len(checking_threads) == 1
    assert target.read_bytes() == b"original video content"
    assert not source.exists()
    assert widget.table.rowCount() == 0
    assert refreshed == [(str(source), str(target))]
    assert widget.rename_btn.isEnabled() and widget.table.isEnabled()


def test_failed_file_remains_and_next_file_is_renamed(renamer, qtbot, monkeypatch, tmp_path):
    widget, refreshed, _gates = renamer
    bad, bad_target = add_file(widget, tmp_path, "Bad.mkv")
    good, good_target = add_file(widget, tmp_path, "Good.mkv")
    original = actions_module.rename_movie_file

    def fail_first(source, target):
        if Path(source) == bad:
            raise OSError("source changed")
        return original(source, target)

    monkeypatch.setattr(actions_module, "rename_movie_file", fail_first)
    widget.execute_rename()
    qtbot.waitUntil(lambda: not widget._actions.commit.busy)
    assert bad.exists() and not bad_target.exists()
    assert good_target.exists() and not good.exists()
    assert widget.table.rowCount() == 1
    assert "Fehler" in widget._table_controller.row_item(0, widget.COL_STATUS).text()
    assert refreshed == [(str(good), str(good_target))]


def test_shutdown_finishes_current_file_and_skips_next(renamer, qtbot, monkeypatch, tmp_path):
    widget, refreshed, gates = renamer
    first, first_target = add_file(widget, tmp_path, "First.mkv")
    second, second_target = add_file(widget, tmp_path, "Second.mkv")
    entered, release = threading.Event(), threading.Event()
    gates.append(release)
    original = actions_module.rename_movie_file

    def hold_commit(source, target):
        entered.set()
        assert release.wait(5)
        return original(source, target)

    monkeypatch.setattr(actions_module, "rename_movie_file", hold_commit)
    widget.execute_rename()
    qtbot.waitUntil(entered.is_set)
    workers = collect_shutdown_workers([widget])
    assert widget._actions.commit.thread in workers
    assert not shutdown_workers(workers, timeout_ms=0).ok
    assert widget.close() is False
    assert widget._actions.commit.thread in collect_shutdown_workers([widget])
    release.set()
    qtbot.waitUntil(lambda: not widget._actions.commit.busy)
    assert first_target.exists() and not first.exists()
    assert second.exists() and not second_target.exists()
    assert widget.table.rowCount() == 1
    assert "Abbruch" in widget.status_lbl.text()
    assert refreshed == [(str(first), str(first_target))]


def test_confirmation_reentry_does_not_start_duplicate_batch(renamer, qtbot, monkeypatch, tmp_path):
    widget, _refreshed, _gates = renamer
    source, target = add_file(widget, tmp_path)
    confirmations = []

    def confirm(*_args):
        confirmations.append(True)
        assert collect_shutdown_workers([widget])
        widget.execute_rename()
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    widget.execute_rename()
    qtbot.waitUntil(lambda: not widget._actions.commit.busy)
    assert confirmations == [True]
    assert target.exists() and not source.exists()


def test_close_during_confirmation_cancels_before_file_operation(renamer, monkeypatch, tmp_path):
    widget, refreshed, _gates = renamer
    source, target = add_file(widget, tmp_path)

    def confirm(*_args):
        assert not shutdown_workers(collect_shutdown_workers([widget]), timeout_ms=0).ok
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    widget.execute_rename()
    assert not widget._actions.commit.busy
    assert widget.table.isEnabled() and widget.rename_btn.isEnabled()
    assert source.exists() and not target.exists() and not refreshed


def test_worker_start_failure_restores_controls_and_ownership(renamer, monkeypatch, tmp_path):
    widget, refreshed, _gates = renamer
    source, target = add_file(widget, tmp_path)

    def fail_start(_self):
        raise RuntimeError("thread could not start")

    monkeypatch.setattr(MovieRenameCommitThread, "start", fail_start)
    widget.execute_rename()
    assert not widget._actions.commit.busy
    assert widget.table.isEnabled() and widget.rename_btn.isEnabled()
    assert "thread could not start" in widget.status_lbl.text()
    assert not collect_shutdown_workers([widget])
    assert source.exists() and not target.exists() and not refreshed


def test_search_completion_cannot_unlock_running_rename(renamer):
    widget, _refreshed, _gates = renamer
    widget._view.set_busy(True)
    widget._view.set_rename_busy(True)
    widget._view.set_busy(False)
    assert not widget.table.isEnabled()
    assert all(not button.isEnabled() for button in widget._view.action_buttons)
    widget._view.set_busy(True)
    widget._view.set_rename_busy(False)
    assert widget.table.isEnabled()
    assert not widget.rename_btn.isEnabled()
    assert widget.add_files_btn.isEnabled()
    widget._view.set_busy(False)
    assert widget.rename_btn.isEnabled()


def test_target_created_after_confirmation_is_preserved(renamer, qtbot, monkeypatch, tmp_path):
    widget, refreshed, gates = renamer
    source, target = add_file(widget, tmp_path)
    entered, release = threading.Event(), threading.Event()
    gates.append(release)
    original = actions_module.rename_movie_file

    def hold_rename(source, target_name):
        entered.set()
        assert release.wait(5)
        return original(source, target_name)

    monkeypatch.setattr(actions_module, "rename_movie_file", hold_rename)
    widget.execute_rename()
    qtbot.waitUntil(entered.is_set)
    target.write_bytes(b"created by another process")
    release.set()
    qtbot.waitUntil(lambda: not widget._actions.commit.busy)
    assert source.read_bytes() == b"original video content"
    assert target.read_bytes() == b"created by another process"
    assert widget.table.rowCount() == 1 and not refreshed
