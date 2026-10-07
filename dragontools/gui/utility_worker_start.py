"""Keep utility worker ownership across reentrant and failed starts."""
from functools import wraps
from .qt_receiver_state import receiver_is_alive

from ..core.callback_dispatch import best_effort_callback
from .shutdown_worker_state import worker_is_running


class UtilityStartOwner:
    def __init__(self, owner):
        self.owner = owner

    def isRunning(self):
        return getattr(self.owner, '_utility_start_owner', None) is self

    def objectName(self):
        return 'Zusatzwerkzeug wird gestartet'

    def request_abort(self, mode='sofort'):
        if self.isRunning():
            self.owner._utility_start_cancelled = True

    def requestInterruption(self):
        self.request_abort()

    def wait(self, timeout=0):
        return not self.isRunning()


def utility_workers(owner, *attributes):
    workers = tuple(worker for attribute in attributes
                    if (worker := getattr(owner, attribute, None)) is not None)
    claimed = getattr(owner, '_utility_start_owner', None)
    return workers + ((claimed,) if claimed is not None else ())


def _owner_deleted(owner):
    return not receiver_is_alive(owner)


def start_utility_worker(owner, worker):
    if _owner_deleted(owner) or getattr(owner, '_utility_start_cancelled', False):
        raise RuntimeError('Start des Zusatzwerkzeugs wurde abgebrochen.')
    worker.start()


def restore_utility_start(owner, *attributes):
    """Release only workers known to have stopped; keep close discovery intact."""
    running = False
    for attribute in attributes:
        worker = getattr(owner, attribute, None)
        if worker is None:
            continue
        if worker_is_running(worker):
            running = True
        else:
            setattr(owner, attribute, None)
    owner.set_utility_running(running)


def owned_utility_start(*attributes):
    def decorate(method):
        @wraps(method)
        def start(owner, *args, **kwargs):
            if _owner_deleted(owner):
                return
            if getattr(owner, "_utility_start_claimed", False):
                return
            if any(getattr(owner, attribute, None) is not None for attribute in attributes):
                return
            owner._utility_start_claimed = True
            owner._utility_start_cancelled = False
            owner._utility_start_owner = UtilityStartOwner(owner)
            try:
                return method(owner, *args, **kwargs)
            except Exception as exc:
                restore_utility_start(owner, *attributes)
                report = getattr(owner, "_append_log", None)
                if callable(report):
                    best_effort_callback(report, f"❌ Start fehlgeschlagen: {exc}")
            finally:
                owner._utility_start_claimed = False
                owner._utility_start_owner = None
        return start
    return decorate


def connect_owned_signal(owner, attribute, worker, signal, callback):
    """Discard queued callbacks from a worker that no longer owns this widget."""
    if getattr(owner, '_utility_start_cancelled', False):
        raise RuntimeError('Start des Zusatzwerkzeugs wurde abgebrochen.')
    def deliver(*args):
        if not _owner_deleted(owner) and getattr(owner, attribute, None) is worker:
            callback(*args)
    signal.connect(deliver)
