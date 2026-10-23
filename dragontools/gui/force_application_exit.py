"""Explicit emergency exit when cooperative worker shutdown has failed."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def force_application_exit() -> None:
    """Kill this application's process tree, with an unconditional exit fallback.

    Do not destroy Qt objects, join threads, acquire worker locks or clear the
    crash/recovery markers: the user explicitly chose an unclean shutdown.
    """
    try:
        if sys.platform == "win32":
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
            subprocess.run(
                [str(taskkill), "/PID", str(os.getpid()), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=3,
                check=False,
            )
    finally:
        # This fallback also runs when process creation fails. Python/Qt
        # finalizers must not keep the application alive.
        os._exit(1)
