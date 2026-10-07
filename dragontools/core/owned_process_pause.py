"""Suspend only validated members of the exact Windows Job owned by a tool."""
import ctypes
from ctypes import wintypes


def windows_pause_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    contracts = {
        "QueryInformationJobObject": ((wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p), wintypes.BOOL),
        "OpenProcess": ((wintypes.DWORD, wintypes.BOOL, wintypes.DWORD), wintypes.HANDLE),
        "IsProcessInJob": ((wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)), wintypes.BOOL),
        "WaitForSingleObject": ((wintypes.HANDLE, wintypes.DWORD), wintypes.DWORD),
        "CloseHandle": ((wintypes.HANDLE,), wintypes.BOOL),
        "TerminateJobObject": ((wintypes.HANDLE, wintypes.UINT), wintypes.BOOL),
    }
    for name, (args, result) in contracts.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    native = ctypes.WinDLL("ntdll")
    for name in ("NtSuspendProcess", "NtResumeProcess"):
        function = getattr(native, name)
        function.argtypes, function.restype = (wintypes.HANDLE,), ctypes.c_long
    return kernel, native


def job_process_ids(kernel, job):
    capacity = 32
    while capacity <= 4096:
        buffer = ctypes.create_string_buffer(8 + capacity * ctypes.sizeof(ctypes.c_size_t))
        ok = kernel.QueryInformationJobObject(job, 3, buffer, ctypes.sizeof(buffer), None)
        assigned = wintypes.DWORD.from_buffer(buffer, 0).value
        count = wintypes.DWORD.from_buffer(buffer, 4).value
        if ok and count == assigned and count <= capacity:
            return tuple(ctypes.c_size_t.from_buffer(buffer, 8 + i * ctypes.sizeof(ctypes.c_size_t)).value
                         for i in range(count))
        error = ctypes.get_last_error()
        if not ok and error != 234:  # ERROR_MORE_DATA
            raise ctypes.WinError(error)
        capacity = max(capacity * 2, assigned)
    raise OSError("Worker-Prozessbaum überschreitet die sichere Pause-Grenze.")


def open_owned_member(kernel, job, pid):
    handle = kernel.OpenProcess(0x100000 | 0x1000 | 0x0800, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # Already exited; never substitute another PID.
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    owned = wintypes.BOOL()
    try:
        if not kernel.IsProcessInJob(handle, job, ctypes.byref(owned)):
            raise ctypes.WinError(ctypes.get_last_error())
        state = kernel.WaitForSingleObject(handle, 0)
        if state == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if not owned.value or state == 0:
            kernel.CloseHandle(handle)
            return None
        return handle
    except BaseException:
        kernel.CloseHandle(handle)
        raise


def resume_handles(kernel, native, handles):
    ok = True
    for handle in handles:
        try:
            state = kernel.WaitForSingleObject(handle, 0)
            if state == 0xFFFFFFFF:
                ok = False
            elif state != 0:
                ok = int(native.NtResumeProcess(handle)) == 0 and ok
        except Exception:
            ok = False
        finally:
            try:
                ok = bool(kernel.CloseHandle(handle)) and ok
            except Exception:
                ok = False
    return ok


def suspend_job_members(kernel, native, job):
    handles = {}
    try:
        for _ in range(32):
            new_ids = [pid for pid in job_process_ids(kernel, job) if pid not in handles]
            if not new_ids:
                return list(handles.values())
            for pid in new_ids:
                handle = open_owned_member(kernel, job, pid)
                if handle is None:
                    continue
                try:
                    status = int(native.NtSuspendProcess(handle))
                    if status != 0:
                        raise OSError(f"Worker-Prozess konnte nicht pausiert werden: 0x{status & 0xFFFFFFFF:08X}")
                except BaseException:
                    kernel.CloseHandle(handle)
                    raise
                handles[pid] = handle
        raise OSError("Worker-Prozessbaum wurde während des Pausierens nicht stabil.")
    except BaseException:
        if not resume_handles(kernel, native, handles.values()):
            # Never strand a partially suspended tree. Termination stays bound
            # to this job handle, and the tool cannot later report exit code 0.
            if not kernel.TerminateJobObject(job, 1):
                raise ctypes.WinError(ctypes.get_last_error())
        raise


def suspend_owned_process_tree(proc):
    data = getattr(proc, "__dict__", {})
    lock = data.get("_dragontools_job_lock")
    if lock is None:
        return None
    with lock:
        job = data.get("_dragontools_job")
        if job is None:
            return None
        if data.get("_dragontools_pause_handles"):
            return True
        kernel, native = windows_pause_api()
        data["_dragontools_pause_handles"] = suspend_job_members(kernel, native, job)
        return True


def resume_owned_process_tree(proc):
    data = getattr(proc, "__dict__", {})
    lock = data.get("_dragontools_job_lock")
    if lock is None:
        return None
    with lock:
        if data.get("_dragontools_job") is None and not data.get("_dragontools_pause_handles"):
            return None
        handles = data.get("_dragontools_pause_handles", [])
        if not handles:
            return True
        kernel, native = windows_pause_api()
        data.pop("_dragontools_pause_handles", None)
        ok = resume_handles(kernel, native, handles)
        if not ok and data.get("_dragontools_job") is not None:
            if not kernel.TerminateJobObject(data["_dragontools_job"], 1):
                raise ctypes.WinError(ctypes.get_last_error())
        return ok


def close_owned_pause_handles(proc, kernel):
    """Caller holds the job lock and immediately closes the KILL_ON_CLOSE job."""
    for handle in getattr(proc, "__dict__", {}).pop("_dragontools_pause_handles", []):
        kernel.CloseHandle(handle)
