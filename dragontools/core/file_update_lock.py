"""Serialize persistent read-modify-write operations across threads and processes."""
from contextlib import contextmanager
import os
from pathlib import Path
import threading
import time

_GUARD = threading.Lock()
_LOCKS = {}


def _native_lock(handle, *, unlock=False):
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def file_update_lock(path, *, timeout_s=15):
    path = Path(path).resolve()
    key = os.path.normcase(str(path))
    with _GUARD:
        lock, refs = _LOCKS.get(key, (threading.Lock(), 0))
        _LOCKS[key] = lock, refs + 1
    try:
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.with_name('.' + path.name + '.dragontools.lock').open('a+b') as handle:
                if handle.seek(0, 2) == 0:
                    handle.write(b'\0'); handle.flush()
                deadline = time.monotonic() + timeout_s
                while True:
                    try:
                        _native_lock(handle)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Erinnerungsdatei ist durch einen anderen Vorgang gesperrt.')
                        time.sleep(.05)
                try:
                    yield
                finally:
                    _native_lock(handle, unlock=True)
    finally:
        with _GUARD:
            current, refs = _LOCKS[key]
            if refs == 1:
                del _LOCKS[key]
            else:
                _LOCKS[key] = current, refs - 1
