"""Read-only process liveness checks, including native Windows handles."""
from __future__ import annotations


def windows_pid_is_running(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE only
    if not handle:
        # Invalid PID is absent; access denied/unknown must be treated as live.
        return ctypes.get_last_error() != 87
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0: ended
    finally:
        kernel.CloseHandle(handle)
