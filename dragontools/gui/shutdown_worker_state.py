"""Qt-independent conservative worker discovery and stop contracts."""
from inspect import signature


class UnresolvedShutdownWorker:
    """Keep close/restart blocked until a failed provider can be inspected."""
    def __init__(self, owner):
        self.name = f"Worker-Ermittlung fehlgeschlagen: {type(owner).__name__}"

    def objectName(self):
        return self.name

    def isRunning(self):
        return True


def worker_is_running(worker):
    try:
        return bool(worker.isRunning())
    except RuntimeError as exc:
        # Qt raises this exact error for a wrapper with no native object left.
        return not ("wrapped C/C++ object" in str(exc) and "has been deleted" in str(exc))
    except Exception:
        return True


def discovered_workers(owner):
    try:
        provider = getattr(owner, "iter_shutdown_workers", None)
        if callable(provider):
            yield from provider() or ()
    except Exception:
        yield UnresolvedShutdownWorker(owner)


def invoke_abort_once(abort):
    try:
        contract = signature(abort)
    except (TypeError, ValueError):
        abort("sofort")
        return
    try:
        contract.bind("sofort")
    except TypeError:
        contract.bind()
        abort()
    else:
        abort("sofort")
