"""Regression coverage for complete media hashing in the startup GUI thread."""
from pathlib import Path
import threading

from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtWidgets import QMainWindow

from dragontools.core import move_journal, move_journal_recovery
from dragontools.core.transaction_identity import path_receipt
from dragontools.gui import move_journal_recovery_thread as background
from dragontools.gui.application_shutdown import collect_shutdown_workers, shutdown_workers
from dragontools.gui.application_worker_sources import application_worker_sources
from dragontools.gui.move_resume_dialog import MoveResumeDialog


def test_completed_rows_do_not_touch_media_files(monkeypatch):
    row = {"status": "ok", "phase": "completed", "dest_path": r"\\nas\film.mkv",
           "cleanup_pending": False, "backup_pairs": []}
    def unexpected_io(*args, **kwargs):
        raise AssertionError("Completed media must not be scanned again at startup")
    monkeypatch.setattr(Path, "exists", unexpected_io)
    result = move_journal_recovery.recover_interrupted_backups({"files": {"source.mkv": row}})
    assert not any(result.values())
    assert row["status"] == "ok"


def test_completed_row_with_backup_still_verifies_and_cleans_it(tmp_path):
    destination = tmp_path / "film.mkv"
    destination.write_bytes(b"verified new film")
    backup = tmp_path / "film.mkv.__dragontools_backup__old"
    backup.write_bytes(b"old film")
    row = {"status": "ok", "phase": "completed", "dest_path": str(destination),
           "commit_proof": {"destination": path_receipt(destination)},
           "backup_pairs": [{"original": str(destination), "backup": str(backup),
                             "receipt": path_receipt(backup)}]}
    result = move_journal_recovery.recover_interrupted_backups(
        {"files": {str(tmp_path / "missing-source.mkv"): row}})
    assert result["cleaned"] == 1
    assert not backup.exists()
    assert destination.read_bytes() == b"verified new film"


def test_completed_row_with_pending_cleanup_is_not_skipped(tmp_path):
    source = tmp_path / "source.mkv"
    destination = tmp_path / "film.mkv"
    source.write_bytes(b"source")
    destination.write_bytes(b"film")
    row = {"status": "ok", "phase": "completed", "dest_path": str(destination),
           "cleanup_pending": True, "backup_pairs": [],
           "commit_proof": {"source": path_receipt(source),
                            "destination": path_receipt(destination)}}
    result = move_journal_recovery.recover_interrupted_backups({"files": {str(source): row}})
    assert result["cleaned"] == 1
    assert not source.exists()


def test_stop_is_observed_before_starting_another_journal(monkeypatch):
    monkeypatch.setattr(move_journal, "read_active_move_journals", lambda root: [{"_journal_path": "a"}])
    monkeypatch.setattr(move_journal, "recover_interrupted_backups",
                        lambda data: (_ for _ in ()).throw(AssertionError("should not recover")))
    assert not any(move_journal.recover_active_move_backups(should_stop=lambda: True).values())


class RecoveryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.presented = []

    def _present_move_journal(self, payload, **options):
        self.presented.append((payload, options, QThread.currentThread()))


def test_slow_recovery_keeps_ui_timer_running_and_prepares_once(qtbot, monkeypatch):
    window = RecoveryWindow()
    qtbot.addWidget(window)
    entered = threading.Event()
    release = threading.Event()
    heartbeat = []
    def slow_recovery(**kwargs):
        assert QThread.currentThread() is not window.thread()
        entered.set()
        assert release.wait(5)
        return {"restored": 0}
    monkeypatch.setattr(background, "recover_active_move_backups", slow_recovery)
    monkeypatch.setattr(background, "read_active_move_journal", lambda: None)
    background.start_move_journal_recovery(window, on_ready=window._present_move_journal,
                                         show_empty_message=False, quiet_errors=True)
    thread = window._move_journal_recovery_thread
    try:
        qtbot.waitUntil(entered.is_set)
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
        assert thread.isRunning()
        background.start_move_journal_recovery(window, on_ready=window._present_move_journal,
                                             show_empty_message=True, quiet_errors=False)
        assert window._move_journal_recovery_thread is thread
    finally:
        release.set()
        thread.wait(5000)
    qtbot.waitUntil(lambda: window._move_journal_recovery_thread is None)
    assert len(window.presented) == 1
    assert window.presented[0][2] is window.thread()
    assert window.presented[0][1] == {"show_empty_message": False, "quiet_errors": True}


def test_recovery_participates_in_shutdown_and_suppresses_cancelled_dialog(qtbot, monkeypatch):
    window = RecoveryWindow()
    qtbot.addWidget(window)
    entered, release = threading.Event(), threading.Event()
    def slow_recovery(**kwargs):
        entered.set()
        assert release.wait(5)
        return {}
    monkeypatch.setattr(background, "recover_active_move_backups", slow_recovery)
    monkeypatch.setattr(background, "read_active_move_journal",
                        lambda: (_ for _ in ()).throw(AssertionError("cancelled")))
    background.start_move_journal_recovery(window, on_ready=window._present_move_journal,
                                         show_empty_message=False, quiet_errors=True)
    thread = window._move_journal_recovery_thread
    try:
        qtbot.waitUntil(entered.is_set)
        workers = collect_shutdown_workers(application_worker_sources(window))
        assert thread in workers
        result = shutdown_workers(workers, timeout_ms=1)
        assert not result.ok
        assert thread.isInterruptionRequested()
    finally:
        release.set()
        thread.wait(5000)
    qtbot.waitUntil(lambda: window._move_journal_recovery_thread is None)
    assert window.presented == []


def test_worker_errors_are_delivered_on_gui_thread(qtbot, monkeypatch):
    window = RecoveryWindow()
    qtbot.addWidget(window)
    def fail(**kwargs):
        raise OSError("network unavailable")
    monkeypatch.setattr(background, "recover_active_move_backups", fail)
    background.start_move_journal_recovery(window, on_ready=window._present_move_journal,
                                         show_empty_message=True, quiet_errors=False)
    qtbot.waitUntil(lambda: window._move_journal_recovery_thread is None)
    assert window.presented[0][0] == {"error": "network unavailable"}
    assert window.presented[0][2] is window.thread()


def test_prepared_dialog_does_not_repeat_filesystem_proofs(qtbot, monkeypatch):
    from dragontools.core import move_journal_resume
    def unexpected_io(*args, **kwargs):
        raise AssertionError("Resume proofs must stay outside the GUI thread")
    monkeypatch.setattr(move_journal_resume, "build_move_resume_plan", unexpected_io)
    plan = {"files": ["film.mkv"], "counts": {"ok": 1}}
    data = {"files": {"film.mkv": {"status": "running", "phase": "sidecars_pending"}}}
    dialog = MoveResumeDialog(data, prepared_plan=plan)
    qtbot.addWidget(dialog)
    assert dialog.resume_plan() == plan
    plan["files"].clear()
    returned = dialog.resume_plan()
    returned["files"].clear()
    assert dialog.resume_plan()["files"] == ["film.mkv"]
