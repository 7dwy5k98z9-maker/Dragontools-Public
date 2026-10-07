from __future__ import annotations

import ntpath
import os
import subprocess
from typing import Callable

from .windows_restart_policy import allow_user_initiated_shutdown, clear_user_initiated_shutdown
from .callback_dispatch import best_effort_callback


LogFn = Callable[[str, str], None]


def _log_shutdown(log, message, level):
    # An optional display/log sink cannot alter the OS command outcome.
    return best_effort_callback(log, message, level)


def _shutdown_delay(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 315360000:
        raise ValueError("Ungültiger Shutdown-Puffer; erwartet werden ganze Sekunden ab 0.")
    return value


def schedule_system_shutdown(
    *,
    delay_seconds: int = 5,
    log: LogFn | None = None,
) -> bool:
    """Schedule system shutdown and return True if the OS accepted the request."""
    try:
        delay_seconds = _shutdown_delay(delay_seconds)
    except ValueError as exc:
        _log_shutdown(log, str(exc), "error")
        return False
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        shutdown_exe = ntpath.join(system_root, "System32", "shutdown.exe")
        cmd = [shutdown_exe, "/s", "/t", str(delay_seconds)]
        kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        if delay_seconds <= 150:
            allow_user_initiated_shutdown()
        else:
            allow_user_initiated_shutdown(seconds=delay_seconds + 30)
    else:
        # Non-Windows fallback; DragonTools is primarily a Windows app.
        cmd = ["shutdown", "-h", "now"]
        kwargs = {}

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            **kwargs,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if os.name == "nt":
            clear_user_initiated_shutdown()
        if log:
            detail = _shutdown_error_detail(exc)
            _log_shutdown(log, f"❌ Herunterfahren fehlgeschlagen: {detail}", "error")
        return False

    if log:
        if delay_seconds > 0 and os.name == "nt":
            _log_shutdown(log, f"ℹ️ Herunterfahren wurde geplant ({delay_seconds} Sekunden Puffer).", "info")
        else:
            _log_shutdown(log, "ℹ️ Herunterfahren wurde gestartet.", "info")
    return True


def _shutdown_error_detail(exc: Exception) -> str:
    stdout = getattr(exc, "stdout", "") or ""
    stderr = getattr(exc, "stderr", "") or ""
    details = " ".join(str(part).strip() for part in (stderr, stdout) if str(part).strip())
    if details:
        return details
    return str(exc)
