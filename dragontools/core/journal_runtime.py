"""Keep startup recovery away from live processes and current file transactions."""
from contextlib import contextmanager
import ctypes
from functools import wraps
import os
from pathlib import Path
import threading

_lock = threading.RLock()
_live = {}
_local = threading.local()


def _key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def register_journal(path):
    scopes = getattr(_local, 'scopes', [])
    if not scopes:
        return
    key = _key(path)
    scopes[-1].append(key)
    with _lock:
        _live[key] = _live.get(key, 0) + 1


@contextmanager
def journal_activity(path=None):
    scopes = getattr(_local, 'scopes', None)
    if scopes is None:
        scopes = _local.scopes = []
    scopes.append([])
    try:
        if path is not None:
            register_journal(path)
        yield
    finally:
        keys = scopes.pop()
        with _lock:
            for key in keys:
                remaining = _live.get(key, 1) - 1
                if remaining:
                    _live[key] = remaining
                else:
                    _live.pop(key, None)


def journal_transaction(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        journal = getattr(args[0], '_journal', None) if args else None
        with journal_activity(getattr(journal, 'path', None)):
            return function(*args, **kwargs)
    return wrapped


def _process_alive(pid):
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = ctypes.c_uint32()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def recovery_may_run(data, path):
    with _lock:
        if _live.get(_key(path)):
            return False
    try:
        pid = int(data.get('pid') or 0)
    except (ValueError, TypeError, OverflowError):
        return False
    return pid <= 0 or pid == os.getpid() or not _process_alive(pid)
