# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Literal

from ..core.crash_guard import mark_activity
from .log_dispatch import dispatch_log
from .process_control import terminate_process_tree, wait_while_paused


LogFn = Callable[[str, str], None]
TimeoutMode = Literal["absolute", "inactivity"]


def process_group_kwargs() -> dict[str, object]:
    """Return Popen kwargs that isolate POSIX child process trees."""
    return {"start_new_session": True} if os.name != "nt" else {}


def worker_lock(worker):
    if worker is None:
        return None
    return getattr(worker, "_lock", None) or getattr(worker, "_process_lock", None)


def current_process_attr(worker) -> str:
    if worker is not None and hasattr(worker, "_current_process"):
        return "_current_process"
    return "current_process"


def set_current_process(worker, lock, proc) -> None:
    if worker is None or lock is None:
        return
    attr = current_process_attr(worker)
    with lock:
        if attr == "current_process":
            try:
                worker.current_process = proc
            except Exception:
                setattr(worker, "_current_process", proc)
        else:
            setattr(worker, attr, proc)


def clear_current_process(worker, lock, proc) -> None:
    if worker is None or lock is None:
        return
    attr = current_process_attr(worker)
    with lock:
        try:
            current = worker.current_process if attr == "current_process" else getattr(worker, attr, None)
        except Exception:
            current = getattr(worker, "_current_process", None)
        if current is not proc:
            return
        if attr == "current_process":
            try:
                worker.current_process = None
            except Exception:
                setattr(worker, "_current_process", None)
        else:
            setattr(worker, attr, None)


def terminate_plain(
    proc,
    *,
    timeout: float = 3.0,
    log: LogFn | None = None,
    label: str = "Tool",
) -> None:
    """Terminate one process, including its isolated POSIX process group."""
    if proc is None or proc.poll() is not None:
        return

    if os.name != "nt" and bool(getattr(proc, "_dragontools_process_group", False)):
        import signal

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=timeout)
            return
        except (subprocess.TimeoutExpired, OSError) as exc:
            dispatch_log(
                log,
                f"{label}: SIGTERM-Prozessgruppe fehlgeschlagen/Timeout ({exc}); SIGKILL wird versucht.",
                "warn",
            )
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            try:
                proc.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, OSError):
                pass
        except OSError as exc:
            dispatch_log(log, f"{label}: SIGKILL-Prozessgruppe fehlgeschlagen: {exc}", "error")
        return

    try:
        proc.terminate()
        proc.wait(timeout=timeout)
        return
    except (subprocess.TimeoutExpired, OSError) as exc:
        dispatch_log(log, f"{label}: terminate() fehlgeschlagen/Timeout ({exc}); kill() wird versucht.", "warn")

    try:
        proc.kill()
        try:
            proc.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            pass
    except OSError as exc:
        dispatch_log(log, f"{label}: kill() fehlgeschlagen: {exc}", "error")


def close_process_streams(proc) -> None:
    """Close stdout/stderr pipe handles deterministically, best-effort."""
    if proc is None:
        return
    for name in ("stdout", "stderr"):
        stream = getattr(proc, name, None)
        if stream is None:
            continue
        try:
            if not stream.closed:
                stream.close()
        except (OSError, ValueError):
            pass


@dataclass
class ProcessLifecycle:
    """Shared worker/timeout/abort lifecycle for external tool processes."""

    command: list[str]
    label: str
    timeout_s: int | float | None
    worker: object | None = None
    log: LogFn | None = None
    abort_on_request: bool = False
    timeout_mode: TimeoutMode = "absolute"
    file_path: str | os.PathLike | None = None

    def __post_init__(self) -> None:
        if self.timeout_mode not in {"absolute", "inactivity"}:
            raise ValueError(f"Unbekannter timeout_mode: {self.timeout_mode!r}")
        self.lock = worker_lock(self.worker)
        self.proc = None
        self.started = time.monotonic()
        self.last_activity = self.started
        self.timed_out = False
        self.aborted = False

    def mark_starting(self) -> None:
        mark_activity(f"{self.label} wird gestartet", file_path=self.file_path, command=self.command)

    def register(self, proc) -> None:
        self.proc = proc
        setattr(proc, "_dragontools_process_group", os.name != "nt")
        set_current_process(self.worker, self.lock, proc)
        mark_activity(f"{self.label} läuft", file_path=self.file_path, command=self.command, extra={"pid": proc.pid})

    def note_activity(self) -> None:
        self.last_activity = time.monotonic()

    def _abort_requested(self) -> bool:
        if self.worker is None or not getattr(self.worker, "abort_requested", False):
            return False
        return self.abort_on_request or getattr(self.worker, "abort_type", None) == "sofort"

    def _terminate(self) -> None:
        if self.proc is None:
            return
        if self.worker is not None and self.lock is not None:
            terminate_process_tree(
                self.worker,
                self.lock,
                log=self.log,
                attr_name=current_process_attr(self.worker),
                label=self.label,
            )
        else:
            terminate_plain(self.proc, log=self.log, label=self.label)

    def handle_abort(self) -> int | None:
        if not self._abort_requested():
            return None
        self.aborted = True
        mode_text = "Abbruchanforderung" if self.abort_on_request else "Sofort-Abbruch"
        dispatch_log(self.log, f"{self.label}: {mode_text} - Prozess wird beendet.", "warn")
        self._terminate()
        return 130

    def handle_pause(self) -> None:
        if self.worker is None or self.lock is None or not getattr(self.worker, "_paused", False):
            return
        pause_started = time.monotonic()
        wait_while_paused(self.worker, self.lock)
        pause_duration = time.monotonic() - pause_started
        self.started += pause_duration
        self.last_activity += pause_duration

    def handle_timeout(self, *, display: Literal["minutes", "seconds"] = "minutes") -> int | None:
        if self.timeout_s is None:
            return None
        origin = self.last_activity if self.timeout_mode == "inactivity" else self.started
        if (time.monotonic() - origin) < float(self.timeout_s):
            return None

        self.timed_out = True
        if display == "seconds":
            message = f"❌ {self.label}: Timeout nach {self.timeout_s}s - Prozess wird abgebrochen."
        else:
            minutes = max(1, int(round(float(self.timeout_s) / 60)))
            kind = "Inaktivitäts-Timeout" if self.timeout_mode == "inactivity" else "Timeout"
            message = f"❌ {self.label}: {kind} nach {minutes} Min - Prozess wird abgebrochen."
        dispatch_log(self.log, message, "error")
        self._terminate()
        return 124

    def finish(self, returncode: int | None) -> None:
        if self.proc is not None:
            clear_current_process(self.worker, self.lock, self.proc)
        mark_activity(
            f"{self.label} beendet",
            file_path=self.file_path,
            command=self.command,
            extra={
                "returncode": returncode,
                "timeout": self.timed_out,
                "aborted": self.aborted,
            },
        )
