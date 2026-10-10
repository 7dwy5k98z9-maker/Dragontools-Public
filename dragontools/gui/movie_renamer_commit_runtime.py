"""Background rename transactions and their GUI/shutdown ownership."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QApplication, QMessageBox

from .qt_receiver_state import receiver_is_alive
from .utility_worker_start import owned_utility_start, start_utility_worker, utility_workers


class MovieRenameCommitThread(QThread):
    progress = pyqtSignal(str, int, int)

    def __init__(self, jobs, rename):
        # Application ownership keeps a live transaction independent of tab lifetime.
        super().__init__(QApplication.instance())
        self.setObjectName("Umbenennung: laufende Datei sicher abschließen")
        self.jobs = tuple(jobs)
        self.rename = rename
        self.results = []

    def run(self) -> None:
        for position, (source, target_name) in enumerate(self.jobs, 1):
            # Never interrupt the current commit between publication and rollback.
            if self.isInterruptionRequested():
                break
            self.progress.emit(str(source), position, len(self.jobs))
            try:
                target = self.rename(source, target_name)
            except Exception as exc:
                self.results.append((source, None, str(exc)))
            else:
                self.results.append((source, str(target), None))


class MovieRenamerCommitCoordinator(QObject):
    def __init__(self, owner, view, table_controller, resolver):
        super().__init__()
        self.owner = owner
        self.view = view
        self.table_controller = table_controller
        self.resolver = resolver
        self.thread = None
        self._dispatch = None

    @property
    def busy(self) -> bool:
        return self.thread is not None or getattr(self, "_utility_start_claimed", False)

    def iter_shutdown_workers(self) -> tuple:
        return utility_workers(self, "thread")

    def shutdown(self) -> bool:
        self._utility_start_cancelled = True
        if self.thread is not None:
            self.thread.requestInterruption()
        return not self.busy

    def set_utility_running(self, running: bool) -> None:
        if not receiver_is_alive(self.owner):
            return
        setter = getattr(self.view, "set_rename_busy", None)
        if callable(setter):
            setter(running)
        else:
            self.view.table.setEnabled(not running)

    def _append_log(self, message: str) -> None:
        if receiver_is_alive(self.owner):
            self.view.status_lbl.setText(message)
            QMessageBox.warning(self.owner, "Umbenennung konnte nicht starten", message)

    @owned_utility_start("thread")
    def execute(self, prepare, rename, dispatch) -> None:
        jobs = prepare()
        if not jobs or not receiver_is_alive(self.owner):
            return
        if self.resolver is not None:
            self.resolver.invalidate_paths([source for source, _target in jobs])
        self._dispatch = dispatch
        self.thread = MovieRenameCommitThread(jobs, rename)
        self.thread.progress.connect(self._on_progress)
        self.thread.finished.connect(self._on_finished)
        self.set_utility_running(True)
        self.view.status_lbl.setText("Umbenennung startet …")
        try:
            start_utility_worker(self, self.thread)
        except Exception:
            if not self.thread.isRunning():
                self.thread.deleteLater()
            raise

    @pyqtSlot(str, int, int)
    def _on_progress(self, source: str, position: int, total: int) -> None:
        if not receiver_is_alive(self.owner):
            return
        row = self.table_controller.find_row_by_path(source)
        if row is not None:
            self.table_controller.set_status(row, "⏳ Umbenennen")
        self.view.status_lbl.setText(
            f"{position}/{total}: {Path(source).name} – Umbenennen …"
        )

    @pyqtSlot()
    def _on_finished(self) -> None:
        thread = self.thread
        if thread is None:
            return
        if thread.isRunning():
            QTimer.singleShot(10, self._on_finished)
            return
        self.thread = None
        thread.deleteLater()
        if not receiver_is_alive(self.owner):
            return
        self.set_utility_running(False)
        self._present_results(thread.results, len(thread.jobs))

    def _present_results(self, results, total: int) -> None:
        renamed_paths = []
        failed = []
        for source, target, error in results:
            row = self.table_controller.find_row_by_path(source)
            if error is not None:
                failed.append(f"{Path(source).name}: {error}")
                if row is not None:
                    self.table_controller.set_status(row, "❌ Fehler")
            else:
                renamed_paths.append((str(source), target))
                if row is not None:
                    self.view.table.removeRow(row)
        message = f"{len(renamed_paths)} Datei(en) umbenannt und aus der Liste entfernt."
        if len(results) < total:
            message += f" {total - len(results)} Datei(en) nicht gestartet (Abbruch)."
        if failed:
            message += f" {len(failed)} Fehler blieb(en) zur Prüfung in der Liste."
            QMessageBox.warning(
                self.owner, "Umbenennung mit Fehlern", message + "\n\n" + "\n".join(failed[:8])
            )
        self.view.status_lbl.setText(message)
        if renamed_paths:
            self._dispatch(
                renamed_paths,
                lambda text, _level="info": self.view.status_lbl.setText(text),
                settings=getattr(self.owner, "settings", None),
            )
