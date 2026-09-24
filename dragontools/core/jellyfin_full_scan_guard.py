# -*- coding: utf-8 -*-
"""Single-flight guard for Jellyfin full-library scan fallbacks."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from .jellyfin_api import JellyfinApiError, normalize_server_url

_RECENT_SCAN_STARTS: dict[str, float] = {}
_SCAN_LOCK = threading.Lock()
_RECENT_START_WINDOW_S = 30.0


@dataclass(frozen=True)
class FullScanDecision:
    started: bool
    reused: bool
    reason: str = ""


def _server_key(server_url: str) -> str:
    return normalize_server_url(server_url).casefold()


def start_full_scan_if_needed(
    client,
    server_url: str,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    recent_window_s: float = _RECENT_START_WINDOW_S,
) -> FullScanDecision:
    """Start at most one full scan for concurrent/near-concurrent fallbacks.

    Jellyfin's ``POST /Library/Refresh`` can restart/cancel a scan when another
    request follows quickly.  We first ask the server whether the scheduled
    library-scan task is already running and additionally keep a short local
    lease to close the race between two DragonTools worker threads.
    """
    key = _server_key(server_url)
    now = float(monotonic())
    window = max(0.0, float(recent_window_s))

    with _SCAN_LOCK:
        last_start = _RECENT_SCAN_STARTS.get(key)
        if last_start is not None and now - last_start < window:
            return FullScanDecision(False, True, "recently_started")

        checker = getattr(client, "is_library_scan_running", None)
        if callable(checker):
            try:
                if checker():
                    _RECENT_SCAN_STARTS[key] = now
                    return FullScanDecision(False, True, "server_running")
            except JellyfinApiError:
                # Detection is best-effort. The real refresh call below still
                # provides the authoritative API error when access is broken.
                pass

        client.refresh_library()
        _RECENT_SCAN_STARTS[key] = now
        return FullScanDecision(True, False, "started")


def reset_full_scan_guard_for_tests() -> None:
    with _SCAN_LOCK:
        _RECENT_SCAN_STARTS.clear()
