"""Typed Windows shutdown veto registration; no Qt or system policy changes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes


class WindowsRestartAPI:
    def __init__(self, *, user32=None, kernel32=None) -> None:
        self.user32 = user32 if user32 is not None else ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = kernel32 if kernel32 is not None else ctypes.WinDLL("kernel32", use_last_error=True)
        self._previous_priority = None
        self.user32.ShutdownBlockReasonCreate.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self.user32.ShutdownBlockReasonCreate.restype = wintypes.BOOL
        self.user32.ShutdownBlockReasonQuery.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                                       ctypes.POINTER(wintypes.DWORD)]
        self.user32.ShutdownBlockReasonQuery.restype = wintypes.BOOL
        self.user32.ShutdownBlockReasonDestroy.argtypes = [wintypes.HWND]
        self.user32.ShutdownBlockReasonDestroy.restype = wintypes.BOOL
        self.kernel32.GetProcessShutdownParameters.argtypes = [ctypes.POINTER(wintypes.DWORD),
                                                              ctypes.POINTER(wintypes.DWORD)]
        self.kernel32.GetProcessShutdownParameters.restype = wintypes.BOOL
        self.kernel32.SetProcessShutdownParameters.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel32.SetProcessShutdownParameters.restype = wintypes.BOOL

    @staticmethod
    def _error(operation):
        code = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
        detail = ctypes.FormatError(code).strip() if hasattr(ctypes, "FormatError") else "Windows API failure"
        return OSError(code, f"{operation}: {detail} (Windows-Fehler {code})")

    def query(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(len(buffer))
        if not self.user32.ShutdownBlockReasonQuery(hwnd, buffer, ctypes.byref(size)):
            raise self._error("Neustartschutz abfragen")
        return buffer.value

    def create(self, hwnd: int, reason: str) -> str:
        reason = str(reason)[:250]
        if not hwnd or not self.user32.ShutdownBlockReasonCreate(hwnd, reason):
            raise self._error("Neustartschutz registrieren")
        actual = self.query(hwnd)
        if actual != reason:
            raise OSError("Windows bestätigt den registrierten Neustartschutz nicht")
        return actual

    def destroy(self, hwnd: int) -> None:
        if not self.user32.ShutdownBlockReasonDestroy(hwnd):
            raise self._error("Neustartschutz freigeben")

    def prioritize(self) -> None:
        """Ask this GUI first, before default-priority encoder/tool processes."""
        if self._previous_priority is not None:
            return
        level, flags = wintypes.DWORD(), wintypes.DWORD()
        if not self.kernel32.GetProcessShutdownParameters(ctypes.byref(level), ctypes.byref(flags)):
            raise self._error("Beendigungsreihenfolge abfragen")
        # 0x300..0x3ff is the application-first range, below system components.
        # Keep the retry UI enabled; SHUTDOWN_NORETRY would weaken protection.
        if not self.kernel32.SetProcessShutdownParameters(0x3FF, 0):
            raise self._error("Frühe Neustartabfrage aktivieren")
        self._previous_priority = level.value, flags.value

    def restore_priority(self) -> None:
        if self._previous_priority is None:
            return
        if not self.kernel32.SetProcessShutdownParameters(*self._previous_priority):
            raise self._error("Beendigungsreihenfolge wiederherstellen")
        self._previous_priority = None
