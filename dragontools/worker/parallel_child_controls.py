"""Fan out cancellation controls without dropping the remaining children."""
from .log_dispatch import dispatch_log


def apply_child_control(workers, method, *args, log=None):
    for worker in tuple(workers):
        try:
            running = bool(worker.isRunning())
        except Exception:
            running = True
        if not running:
            continue
        try:
            getattr(worker, method)(*args)
        except Exception as exc:
            dispatch_log(log, f"Worker-Steuerung {method} fehlgeschlagen: {exc}", "error")
