"""Pause one owned child while preserving the global pause policy."""
from ..core.path_syntax import path_compare_key
from .parallel_queue_coordination import coordinated_change, canonical_owned_input
from .log_dispatch import dispatch_log


def worker_pause_state(worker):
    return bool(getattr(worker, "is_paused", getattr(worker, "_paused", False)))


def individually_paused_workers(queue):
    if queue is None:
        return set()
    return {queue.assigned[key] for key in queue.individually_paused if key in queue.assigned}


class ParallelFileControlMixin:
    @coordinated_change
    def file_control_token(self, path):
        if not self._running or self.abort_requested:
            return None
        child = self._queue_state.assigned.get(path_compare_key(path))
        if child is None or canonical_owned_input(self._queue_state, child, path) is None:
            return None
        try:
            if child.isRunning() and callable(getattr(child, "pause", None)) and callable(getattr(child, "resume", None)):
                return child
        except Exception as exc:
            dispatch_log(self._logger, f"Worker-Zustand konnte nicht ermittelt werden: {exc}", "warn")
        return None

    @coordinated_change
    def file_pause_state(self, path):
        child = self.file_control_token(path)
        return worker_pause_state(child) if child is not None else None

    @coordinated_change
    def set_file_paused(self, path, paused, *, expected_worker=None):
        child = self.file_control_token(path)
        if child is None or not isinstance(paused, bool):
            return False
        if expected_worker is not None and child is not expected_worker:
            return False
        if not paused and self._paused:
            return False
        key = path_compare_key(path)
        if paused:
            self._queue_state.individually_paused.add(key)
        else:
            self._queue_state.individually_paused.discard(key)
        try:
            child.pause() if paused else child.resume()
        except Exception as exc:
            dispatch_log(self._logger, f"Einzelner Worker konnte nicht gesteuert werden: {exc}", "error")
            return False
        return worker_pause_state(child) is paused
