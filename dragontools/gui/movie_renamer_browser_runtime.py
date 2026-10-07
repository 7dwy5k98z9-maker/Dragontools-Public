"""Worker start, result delivery and close ownership for the metadata browser."""
from .qt_receiver_state import receiver_is_alive
from .shutdown_worker_state import worker_is_running
from .utility_worker_start import UtilityStartOwner
from .ui_helpers import save_window_geometry
from ..core.callback_dispatch import best_effort_callback
from PyQt6.QtWidgets import QMessageBox


class RenamerBrowserRuntimeMixin:
    def _start_worker(self, fn, on_success, *, busy_text):
        if not receiver_is_alive(self) or getattr(self, '_closed_context', False):
            return
        if self._busy:
            self.status.setText('Bitte die laufende Metadaten-Abfrage abwarten.')
            return
        self._request_token += 1
        token = self._request_token
        self._latest_token = token
        self._set_busy(True, busy_text)
        self._utility_start_cancelled = False
        self._utility_start_owner = UtilityStartOwner(self)
        worker = None
        try:
            worker = self._new_browser_worker(token, fn)
            self._workers.add(worker)
            self._connect_browser_worker(worker, token, on_success)
            if not receiver_is_alive(self) or self._utility_start_cancelled:
                raise RuntimeError('Metadaten-Abfrage wurde vor dem Start abgebrochen.')
            worker.start()
        except Exception as exc:
            running = worker is not None and worker_is_running(worker)
            if worker is not None and not running:
                self._workers.discard(worker)
                best_effort_callback(worker.deleteLater)
            if receiver_is_alive(self):
                self._set_busy(running, f'Metadaten-Abfrage konnte nicht gestartet werden: {exc}')
        finally:
            self._utility_start_owner = None

    def _connect_browser_worker(self, worker, token, on_success):
        delivered = False
        def current():
            return receiver_is_alive(self) and token == self._latest_token
        def succeeded(result_token, payload):
            nonlocal delivered
            if result_token != token or not current():
                return
            delivered = True
            self._set_busy(False)
            try:
                on_success(payload)
            except Exception as exc:
                self.status.setText(f'Metadaten-Ergebnis konnte nicht übernommen werden: {exc}')
        def failed(result_token, message):
            nonlocal delivered
            if result_token != token or not current():
                return
            delivered = True
            self._set_busy(False)
            self.status.setText(f'Metadaten-Abfrage fehlgeschlagen: {message}')
            QMessageBox.warning(self, 'Metadaten-Abfrage fehlgeschlagen', message)
        def finished():
            self._workers.discard(worker)
            if not delivered and current():
                self._set_busy(False, 'Metadaten-Abfrage wurde ohne Ergebnis beendet.')
        worker.succeeded.connect(succeeded)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        worker.finished.connect(worker.deleteLater)

    def _set_busy(self, busy, text=''):
        self._busy = bool(busy)
        for widget in (self.kind_combo, self.query_edit, self.search_btn, self.results,
            self.load_hit_btn, self.season_combo, self.assign_btn, self.auto_assign_btn, self.import_btn):
            widget.setEnabled(not busy)
        if text:
            self.status.setText(text)

    def iter_shutdown_workers(self):
        claim = getattr(self, '_utility_start_owner', None)
        return tuple(self._workers) + ((claim,) if claim is not None else ())

    def _prepare_dialog_finish(self):
        if not getattr(self, '_closed_context', False):
            # Geometry storage is optional; it must not prevent callback invalidation.
            best_effort_callback(save_window_geometry, self, 'renamer_metadata_browser')
        self._closed_context = True
        self._latest_token += 1
        self._busy = False
        self._utility_start_cancelled = True
        for worker in tuple(self._workers):
            if worker_is_running(worker):
                worker.requestInterruption()

    def done(self, result):
        self._prepare_dialog_finish()
        super().done(result)

    def closeEvent(self, event):
        self._prepare_dialog_finish()
        super().closeEvent(event)
