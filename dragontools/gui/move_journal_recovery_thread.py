"""Run filesystem recovery and resume proofs away from the GUI event loop."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.move_journal import (
    recover_active_move_backups, read_active_move_journal,
    build_move_resume_plan,
)
from .qt_receiver_state import receiver_is_alive

_LOG = logging.getLogger(__name__)


class MoveJournalRecoveryThread(QThread):
    prepared = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            recovery = recover_active_move_backups(should_stop=self.isInterruptionRequested)
            if self.isInterruptionRequested():
                return
            data = read_active_move_journal()
            plan = build_move_resume_plan(data) if data else None
            if not self.isInterruptionRequested():
                self.prepared.emit({"recovery": recovery, "data": data, "plan": plan})
        except Exception as exc:
            _LOG.warning("Move-Wiederaufnahme konnte nicht geprüft werden", exc_info=True)
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


def start_move_journal_recovery(window, *, on_ready, show_empty_message: bool, quiet_errors: bool) -> None:
    current = getattr(window, "_move_journal_recovery_thread", None)
    if current is not None and receiver_is_alive(current) and current.isRunning():
        window.statusBar().showMessage("Verschiebe-Wiederherstellung wird bereits geprüft …", 4000)
        return

    thread = MoveJournalRecoveryThread(window)
    thread.setObjectName("Verschiebe-Wiederherstellung")
    window._move_journal_recovery_thread = thread

    def deliver(payload):
        if (receiver_is_alive(window) and not thread.isInterruptionRequested()
                and getattr(window, "_move_journal_recovery_thread", None) is thread):
            on_ready(
                payload, show_empty_message=show_empty_message, quiet_errors=quiet_errors,
            )

    def failed(message):
        deliver({"error": message})

    def finished():
        if receiver_is_alive(window) and getattr(window, "_move_journal_recovery_thread", None) is thread:
            window._move_journal_recovery_thread = None
        thread.deleteLater()

    thread.prepared.connect(deliver)
    thread.failed.connect(failed)
    thread.finished.connect(finished)
    window.statusBar().showMessage("Verschiebe-Wiederherstellung wird geprüft …")
    thread.start()
