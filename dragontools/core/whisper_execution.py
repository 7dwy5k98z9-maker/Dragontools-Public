"""Shared, abortable admission to native Whisper model loading and inference."""
from collections import OrderedDict
from contextlib import contextmanager
from threading import Lock
import time


_EXECUTION_LOCK = Lock()
_MODELS = OrderedDict()


@contextmanager
def whisper_execution_slot(*, abort_check, log, timeout_s=180.0):
    deadline = time.monotonic() + max(0.0, timeout_s)
    acquired = False
    try:
        if abort_check():
            raise InterruptedError("Whisper-Spracherkennung abgebrochen.")
        acquired = _EXECUTION_LOCK.acquire(blocking=False)
        if not acquired:
            log("Whisper wartet auf die laufende Spracherkennung …", "info")
        while not acquired:
            if abort_check():
                raise InterruptedError("Warten auf Whisper abgebrochen.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Whisper ist weiter belegt; maximale Wartezeit überschritten.")
            acquired = _EXECUTION_LOCK.acquire(timeout=min(0.1, remaining))
        if abort_check():
            raise InterruptedError("Whisper-Spracherkennung abgebrochen.")
        yield
    finally:
        if acquired:
            _EXECUTION_LOCK.release()


def cached_model(key):
    """Call only inside whisper_execution_slot."""
    value = _MODELS.get(key)
    if value is not None:
        _MODELS.move_to_end(key)
    return value


def remember_model(key, model, backend):
    """Bound retained models across differing settings; caller owns the slot."""
    _MODELS[key] = (model, backend)
    _MODELS.move_to_end(key)
    while len(_MODELS) > 2:
        _MODELS.popitem(last=False)
