"""Native ownership of child process trees, established before Windows launch."""
from __future__ import annotations

import ctypes
import os
import subprocess
import signal
import threading
from ctypes import wintypes


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kernel_api():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ((ctypes.c_void_p, wintypes.LPCWSTR), wintypes.HANDLE),
        "SetInformationJobObject": ((wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD), wintypes.BOOL),
        "AssignProcessToJobObject": ((wintypes.HANDLE, wintypes.HANDLE), wintypes.BOOL),
        "TerminateJobObject": ((wintypes.HANDLE, wintypes.UINT), wintypes.BOOL),
        "CloseHandle": ((wintypes.HANDLE,), wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


def _assign_windows_job(proc):
    kernel = _kernel_api()
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        proc._dragontools_job = job
        proc._dragontools_job_lock = threading.Lock()
        native = ctypes.WinDLL("ntdll").NtResumeProcess
        native.argtypes, native.restype = (wintypes.HANDLE,), ctypes.c_long
        status = int(native(wintypes.HANDLE(proc._handle)))
        if status != 0:
            raise OSError(f"NtResumeProcess fehlgeschlagen: 0x{status & 0xFFFFFFFF:08X}")
    except BaseException:
        kernel.CloseHandle(job)
        proc._dragontools_job = None
        raise


def spawn_owned_process(command, **kwargs):
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x00000004  # CREATE_SUSPENDED
    proc = subprocess.Popen(command, **kwargs)
    proc._dragontools_process_group = os.name != "nt" and bool(kwargs.get("start_new_session"))
    if os.name == "nt" and hasattr(proc, "_handle"):
        try:
            _assign_windows_job(proc)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            raise
    return proc


def terminate_owned_job(proc):
    lock = getattr(proc, "__dict__", {}).get("_dragontools_job_lock")
    if lock is None:
        return False
    with lock:
        job = getattr(proc, "__dict__", {}).get("_dragontools_job")
        if job is None:
            return False
        if not _kernel_api().TerminateJobObject(job, 1):
            raise ctypes.WinError(ctypes.get_last_error())
    return True


def close_owned_job(proc):
    if os.name != "nt" and bool(getattr(proc, "_dragontools_process_group", False)):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc._dragontools_process_group = False
        return
    lock = getattr(proc, "__dict__", {}).get("_dragontools_job_lock")
    if lock is None:
        return
    with lock:
        job = getattr(proc, "__dict__", {}).get("_dragontools_job")
        if job is not None:
            from .owned_process_pause import close_owned_pause_handles
            kernel = _kernel_api()
            close_owned_pause_handles(proc, kernel)
            proc._dragontools_job = None
            kernel.CloseHandle(job)
