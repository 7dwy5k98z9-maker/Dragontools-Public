"""Serialize queue transitions, including synchronous reentrant child signals."""
from contextlib import nullcontext
from functools import wraps
from ..core.path_syntax import path_compare_key


def coordinated_change(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        state = getattr(self, "_queue_state", None)
        if state is None:
            state = getattr(self, "_queue", None)
        lock = getattr(state, "lock", None) or getattr(self, "lock", None)
        with lock if lock is not None else nullcontext():
            return method(self, *args, **kwargs)
    return call


def canonical_owned_input(queue, child, path, *, allow_terminal=False):
    key = path_compare_key(path)
    owner = queue.assigned.get(key)
    if owner is None or (child is not None and owner is not child):
        return None
    canonical = next((value for value in queue.files
        if path_compare_key(value) == key), None)
    if canonical is None or (not allow_terminal and canonical in queue.terminal_inputs):
        return None
    return canonical
