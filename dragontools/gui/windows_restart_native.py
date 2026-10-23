"""Veto session queries before Qt's default window-close/session handling."""
import ctypes
import logging
from ctypes import wintypes
import weakref

from PyQt6.QtCore import QAbstractNativeEventFilter

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
ENDSESSION_CRITICAL = 0x40000000


class WindowsRestartEventFilter(QAbstractNativeEventFilter):
    def __init__(self, guard):
        super().__init__()
        self._guard = weakref.ref(guard)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        guard = self._guard()
        if guard is None or getattr(guard, "_disposed", False):
            return False, 0
        try:
            address = int(message)
            if not address:
                return False, 0
            native = wintypes.MSG.from_address(address)
            return guard.handle_native_message(native.message, native.wParam, native.lParam)
        except Exception as exc:
            # An exception must never escape a native Qt callback. If we cannot
            # safely inspect a session query, reject that query conservatively.
            try:
                guard.native_filter_error(exc)
            except Exception:
                logging.getLogger(__name__).warning("Neustartschutz-Diagnose fehlgeschlagen", exc_info=True)
            try:
                if wintypes.MSG.from_address(int(message)).message == WM_QUERYENDSESSION:
                    return True, 0
            except Exception:
                return False, 0
            return False, 0
