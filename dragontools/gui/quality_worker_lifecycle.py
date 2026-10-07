"""Native Qt receivers and start reservations for quality/matcher operations."""
from PyQt6.QtCore import QObject, pyqtSlot
from PyQt6.QtWidgets import QApplication
from .qt_receiver_state import receiver_is_alive
from .shutdown_worker_state import worker_is_running
from .utility_worker_start import UtilityStartOwner, start_utility_worker

_ACTIVE_QUALITY_WORKERS = set()
_RECEIVERS = {}


def active_quality_workers():
    return tuple(_ACTIVE_QUALITY_WORKERS)


class QualityStartOwner(UtilityStartOwner):
    def cancel(self):
        self.request_abort()


class QualityWorkerReceiver(QObject):
    def __init__(self, owner, worker, callbacks):
        super().__init__(QApplication.instance())
        self.owner, self.worker, self.callbacks = owner, worker, callbacks
        _RECEIVERS[worker] = self
        for name, callback in callbacks.items():
            if callback is not None:
                getattr(worker, name).connect(getattr(self, name))

    def _deliver(self, name, *args):
        if receiver_is_alive(self.owner) and getattr(self.owner, '_worker', None) is self.worker:
            callback = self.callbacks.get(name)
            if callback is not None:
                callback(*args)

    @pyqtSlot(str)
    def log_line(self, value):
        self._deliver('log_line', value)

    @pyqtSlot(int)
    def progress(self, value):
        self._deliver('progress', value)

    @pyqtSlot(str)
    @pyqtSlot(object)
    def result_ready(self, value):
        self._deliver('result_ready', value)

    @pyqtSlot(object)
    def analysis_ready(self, value):
        self._deliver('analysis_ready', value)

    @pyqtSlot(object)
    def cuts_ready(self, value):
        self._deliver('cuts_ready', value)

    @pyqtSlot(object)
    def summary_ready(self, value):
        self._deliver('summary_ready', value)

    @pyqtSlot(str)
    def error(self, value):
        self._deliver('error', value)

    @pyqtSlot()
    def finished(self):
        try:
            self._deliver('finished')
        finally:
            release_quality_worker(self.worker)


def connect_quality_worker(owner, worker, **callbacks):
    _ACTIVE_QUALITY_WORKERS.add(worker)
    return QualityWorkerReceiver(owner, worker, callbacks)


def release_quality_worker(worker):
    _ACTIVE_QUALITY_WORKERS.discard(worker)
    receiver = _RECEIVERS.pop(worker, None)
    if receiver is not None:
        receiver.deleteLater()
    if isinstance(worker, QObject) and receiver_is_alive(worker):
        worker.deleteLater()


def start_owned_quality_worker(owner, *, factory, wire, set_running, report_error):
    if getattr(owner, '_worker', None) is not None or not receiver_is_alive(owner):
        return
    claim = QualityStartOwner(owner)
    owner._worker = owner._utility_start_owner = claim
    owner._utility_start_cancelled = False
    _ACTIVE_QUALITY_WORKERS.add(claim)
    worker = None
    try:
        set_running(True)
        worker = factory()
        owner._worker = worker
        wire(worker)
        start_utility_worker(owner, worker)
    except Exception as exc:
        # GUI start boundary: retain a partly started worker until its native
        # finished signal; only known-stopped objects can be released here.
        if worker is None or not worker_is_running(worker):
            owner._worker = None
            if worker is not None:
                release_quality_worker(worker)
            if receiver_is_alive(owner):
                set_running(False)
        if receiver_is_alive(owner):
            report_error(str(exc))
    finally:
        _ACTIVE_QUALITY_WORKERS.discard(claim)
        owner._utility_start_owner = None
