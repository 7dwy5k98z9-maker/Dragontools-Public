"""Own queued Renamer requests through physical thread completion."""
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from ..core.online_metadata_common import OnlineMetadataAuthError
from ..core.path_syntax import path_compare_key
from .qt_receiver_state import receiver_is_alive
from .shutdown_worker_state import worker_is_running
from .utility_worker_start import UtilityStartOwner


class RenamerResolveRuntimeMixin:
    def start_jobs(self, jobs, *, automatic, priority=False):
        if not jobs or not receiver_is_alive(self.owner) or self._shutdown_requested:
            return
        versioned = self._version_jobs(jobs)
        for job in jobs:
            if 0 <= job[0] < self.view.table.rowCount():
                self.table_controller.set_status(job[0], '🔎 Suche')
        if self._utility_start_owner is not None or self.thread is not None:
            if priority and self.thread is not None and worker_is_running(self.thread):
                if self.thread.enqueue_priority(versioned):
                    self.is_automatic = False
                    self.view.set_busy(True)
                    self.view.status_lbl.setText(f'Manuelle Suche priorisiert: {len(versioned)} Datei(en).')
                    return
            for job in versioned:
                self._pending_versioned_jobs[path_compare_key(job[1])] = job
            self.view.status_lbl.setText('Weitere Metadaten-Suche wartet auf den laufenden Worker.')
            return
        self._utility_start_cancelled = False
        self._utility_start_owner = UtilityStartOwner(self)
        try:
            config = self._resolve_config()
            self._launch_resolve_thread(versioned, config, automatic)
        except OnlineMetadataAuthError as exc:
            self._start_failed(jobs, str(exc), automatic, missing_auth=True)
        except Exception as exc:
            self._start_failed(jobs, str(exc), automatic)
        finally:
            self._utility_start_owner = None

    def _launch_resolve_thread(self, jobs, config, automatic):
        self.is_automatic = automatic
        self.view.set_busy(True)
        self.view.status_lbl.setText(f'Metadaten-Vorschläge werden geladen: {len(jobs)} Datei(en).')
        thread = self._create_resolve_thread(jobs, config)
        self.thread = thread
        def proposal(path, request_id, result):
            if self.thread is thread and receiver_is_alive(self.owner) and not self._shutdown_requested:
                self.on_proposal_ready(path, request_id, result)
        thread.proposal_ready.connect(proposal)
        thread.failed.connect(lambda message: self.on_failed(message, thread))
        thread.finished.connect(lambda: self.on_finished(thread))
        thread.finished.connect(thread.deleteLater)
        if self._utility_start_cancelled or self._shutdown_requested or not receiver_is_alive(self.owner):
            raise RuntimeError('Start der Metadaten-Suche wurde abgebrochen.')
        thread.start()

    def _start_failed(self, jobs, message, automatic, *, missing_auth=False):
        running = self.thread is not None and worker_is_running(self.thread)
        if self.thread is not None and not running:
            self.thread.deleteLater()
            self.thread = None
        if not receiver_is_alive(self.owner):
            return
        self.view.set_busy(running)
        for job in jobs:
            row = self.table_controller.find_row_by_path(job[1])
            if row is not None:
                self.table_controller.set_status(row, '⚠️ Metadaten fehlen' if missing_auth else '❌ Startfehler')
        self.view.status_lbl.setText(f'Metadaten-Suche konnte nicht gestartet werden: {message}')
        if not automatic:
            QMessageBox.warning(self.owner, 'Metadaten-Suche', message)

    def on_failed(self, message, failed_thread=None):
        if (failed_thread is not None and self.thread is not failed_thread) or not receiver_is_alive(self.owner) or self._shutdown_requested:
            return
        for row in range(self.view.table.rowCount()):
            if self.table_controller.row_item(row, self.table_controller.columns.STATUS).text() == '🔎 Suche':
                self.table_controller.set_status(row, '❌ Fehler')
        self.view.status_lbl.setText(f'Metadaten-Suche fehlgeschlagen: {message}')
        if not self.is_automatic:
            QMessageBox.warning(self.owner, 'Metadaten-Suche fehlgeschlagen', message)

    def on_finished(self, finished_thread=None):
        if finished_thread is not None and self.thread is not finished_thread:
            return
        if self.thread is not None and worker_is_running(self.thread):
            held = self.thread
            QTimer.singleShot(10, lambda: self.on_finished(held))
            return
        self.thread = None
        self.is_automatic = False
        if not receiver_is_alive(self.owner) or self._shutdown_requested:
            self._pending_versioned_jobs.clear()
            return
        self.view.set_busy(False)
        jobs = self._take_pending_jobs()
        if jobs:
            QTimer.singleShot(0, lambda: self.start_jobs(jobs, automatic=False, priority=True))
        elif self.auto_resolve_pending:
            QTimer.singleShot(0, self.resolve_new)
        else:
            self.view.status_lbl.setText('Vorschlagssuche abgeschlossen.')

    def _take_pending_jobs(self):
        jobs = []
        for key, job in self._pending_versioned_jobs.items():
            if self._request_versions.get(key) != job[-1]:
                continue
            row = self.table_controller.find_row_by_path(job[1])
            if row is not None:
                jobs.append((row, *job[1:-1]))
        self._pending_versioned_jobs.clear()
        return jobs

    def iter_shutdown_workers(self):
        return ((self.thread,) if self.thread is not None else ()) + (
            (self._utility_start_owner,) if self._utility_start_owner is not None else ())

    def shutdown(self, timeout_ms=1500):
        self._shutdown_requested = True
        self._utility_start_cancelled = True
        self._pending_versioned_jobs.clear()
        self.invalidate_paths(list(self._request_versions))
        if self.thread is not None and worker_is_running(self.thread):
            self.thread.requestInterruption()
            self.thread.wait(timeout_ms)
