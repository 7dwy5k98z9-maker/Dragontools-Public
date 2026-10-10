import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtWidgets import QMessageBox, QFileDialog

from dragontools.core.online_metadata_types import OnlineMetadataConfig
from dragontools.core.renamer_completeness import recognized_series, completeness_targets, compare_season
from dragontools.gui.movie_renamer_completeness_dialog import MovieRenamerCompletenessDialog
from dragontools.gui import movie_renamer_completeness_runtime as runtime
from dragontools.gui import movie_renamer_widget as widget_module
from dragontools.gui.application_shutdown import collect_shutdown_workers, shutdown_workers
from dragontools.tests.test_renamer_completeness import proposal


def targets(whole_series=False):
    return completeness_targets(recognized_series([proposal(), proposal(season=2)]), whole_series=whole_series)


@pytest.fixture
def dialog(qtbot):
    instance = MovieRenamerCompletenessDialog(targets(), OnlineMetadataConfig())
    qtbot.addWidget(instance)
    instance.show()
    yield instance
    worker = instance.worker
    if worker is not None:
        worker.requestInterruption()
        assert worker.wait(5000)
        qtbot.waitUntil(lambda: instance.worker is None)


def test_popup_selects_known_seasons_and_exports_missing_episodes(dialog, qtbot, monkeypatch, tmp_path):
    class Service:
        def __init__(self, _config):
            pass

        def check(self, target, **_kwargs):
            return (compare_season(target.series, target.season, (1, 2, 3)),)

    monkeypatch.setattr(runtime, "RenamerCompletenessService", Service)
    dialog.select_all(True)
    qtbot.mouseClick(dialog.check_btn, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dialog.worker is None)
    assert dialog.results_table.rowCount() == 2
    assert dialog.results_table.item(0, 7).text() == "2, 3"
    assert dialog.export_btn.isEnabled()
    path = tmp_path / "report.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(path), "CSV"))
    qtbot.mouseClick(dialog.export_btn, Qt.MouseButton.LeftButton)
    assert path.exists() and "Unvollständig" in path.read_text(encoding="utf-8-sig")


def test_query_is_async_and_closing_preserves_shutdown_ownership(dialog, qtbot, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Service:
        def __init__(self, _config):
            pass

        def check(self, target, **_kwargs):
            entered.set()
            assert release.wait(5)
            return (compare_season(target.series, target.season, (1, 2)),)

    monkeypatch.setattr(runtime, "RenamerCompletenessService", Service)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(10)
    try:
        dialog.start_check()
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        worker = dialog.worker
        dialog.start_check()
        assert dialog.worker is worker and not dialog.check_btn.isEnabled()
        dialog.reject()
        assert dialog.closed and not dialog.isVisible()
        assert worker in collect_shutdown_workers([dialog])
        assert not shutdown_workers([worker], timeout_ms=0).ok
    finally:
        release.set()
        timer.stop()
    qtbot.waitUntil(lambda: dialog.worker is None)
    assert not dialog.report


def test_provider_failure_is_visible_and_exportable(dialog, qtbot, monkeypatch):
    class Service:
        def __init__(self, _config):
            pass

        def check(self, *_args, **_kwargs):
            raise RuntimeError("Provider offline")

    monkeypatch.setattr(runtime, "RenamerCompletenessService", Service)
    dialog.start_check()
    qtbot.waitUntil(lambda: dialog.worker is None)
    assert dialog.results_table.item(0, 4).text() == "Nicht prüfbar"
    assert "Provider offline" in dialog.results_table.item(0, 9).text()
    assert "0 vollständig" in dialog.status.text()


def test_empty_selection_does_not_query(dialog):
    dialog.select_all(False)
    dialog.start_check()
    assert dialog.worker is None and "auswählen" in dialog.status.text()


def test_buttons_use_recognized_rows_without_requiring_acceptance(qtbot, monkeypatch, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(widget_module, "QSettings", lambda *_args: settings)
    monkeypatch.setattr(runtime, "config_from_settings", lambda *_args, **_kwargs: OnlineMetadataConfig())
    empty = []
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: empty.append(True))
    widget = widget_module.MovieRenamerWidget()
    qtbot.addWidget(widget)
    assert widget.check_season_completeness() is None and empty
    row = widget._table_controller.add_row(proposal().source_path)
    widget._table_controller.on_proposal_ready(row, proposal())
    widget._table_controller.set_row_accepted(row, False)
    opened = widget.check_season_completeness()
    assert opened.choices.count() == 1 and "Staffel 1" in opened.choices.item(0).text()
    opened.reject()
    series_dialog = widget.check_series_completeness()
    assert series_dialog.selected_targets()[0].season is None
    series_dialog.reject()
    widget._view.set_busy(True)
    assert not widget.check_season_btn.isEnabled() and not widget.check_series_btn.isEnabled()
    widget._view.set_busy(False)
    widget._view.set_rename_busy(True)
    assert not widget.check_season_btn.isEnabled() and not widget.check_series_btn.isEnabled()


def test_worker_start_failure_restores_dialog_controls(dialog, monkeypatch):
    def fail_start(_worker):
        raise RuntimeError("thread start failed")
    monkeypatch.setattr(runtime.CompletenessThread, "start", fail_start)
    dialog.start_check()
    assert dialog.worker is None and dialog.check_btn.isEnabled()
    assert "thread start failed" in dialog.status.text()
