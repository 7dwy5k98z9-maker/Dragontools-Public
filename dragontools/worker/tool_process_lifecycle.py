# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import time
import threading
from dataclasses import dataclass
from typing import Callable, Literal

from ..core.crash_guard import mark_activity
from ..core.owned_process import terminate_owned_job
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
    state = getattr(worker, "_control_state", None)
    if state is not None:
        return getattr(state, "process_lock", None)
    return getattr(worker, "_lock", None) or getattr(worker, "_process_lock", None)


def current_process_attr(worker) -> str:
    # ConverterThread hält den Prozess im Control-State. Der öffentliche
    # current_process-Propertyzugriff ist selbst lock-gesichert und darf daher
    # niemals unter demselben Lock verwendet werden. Für process_control bleibt
    # bei Control-State-Workern der historische Attributname nur als Fallback.
    if worker is not None and getattr(worker, "_control_state", None) is not None:
        return "_current_process"
    if worker is not None and hasattr(worker, "_current_process"):
        return "_current_process"
    return "current_process"


def set_current_process(worker, lock, proc) -> None:
    if worker is None or lock is None:
        return
    state = getattr(worker, "_control_state", None)
    with lock:
        if state is not None:
            state.current_process = proc
        elif hasattr(worker, "_current_process"):
            worker._current_process = proc
        else:
            worker.current_process = proc


def clear_current_process(worker, lock, proc) -> None:
    if worker is None or lock is None:
        return
    state = getattr(worker, "_control_state", None)
    with lock:
        if state is not None:
            if state.current_process is proc:
                state.current_process = None
            return
        if hasattr(worker, "_current_process"):
            if getattr(worker, "_current_process", None) is proc:
                worker._current_process = None
            return
        if getattr(worker, "current_process", None) is proc:
            worker.current_process = None


def terminate_plain(
    proc,
    *,
    timeout: float = 3.0,
    log: LogFn | None = None,
    label: str = "Tool",
) -> None:
    """Terminate a tool process and, where supported, its owned process tree."""
    if proc is None or proc.poll() is not None:
        return

    try:
        if terminate_owned_job(proc):
            proc.wait(timeout=timeout)
            return
    except (OSError, subprocess.SubprocessError) as exc:
        dispatch_log(log, f"{label}: Job-Abbruch fehlgeschlagen: {exc}", "warn")

    if os.name == "nt":
        # run_tool() is also used without a Worker object.  In that case the
        # normal lifecycle reaches terminate_plain(); killing only the parent
        # could leave ffmpeg/helper children alive after timeout/abort.  The
        # root PID is the process created by this job, so taskkill /T remains
        # scoped to the owned tree.
        from .process_control import _taskkill_tree

        tree_killed = _taskkill_tree(proc.pid, log=log, label=label, timeout=timeout)
        if tree_killed:
            try:
                proc.wait(timeout=timeout)
                return
            except (subprocess.TimeoutExpired, OSError) as exc:
                dispatch_log(
                    log,
                    f"{label}: taskkill meldete Erfolg, Prozessende aber nicht bestätigt ({exc}); "
                    "Python-Kill-Fallback wird versucht.",
                    "warn",
                )

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
        def close_owned_stream(owned=stream):
            try:
                owned.close()
            except (OSError, ValueError):
                pass
        # TextIO.close can wait on a reader's lock while a surviving process
        # holds its pipe open. Keep ownership, but never block the caller forever.
        closer = threading.Thread(target=close_owned_stream, daemon=True)
        closer.start()
        closer.join(timeout=0.1)


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
        # Timeouts describe the lifetime of the running child, not Python's
        # Popen/startup overhead.  Reset both clocks only once the process has
        # actually been created and registered.
        registered_at = time.monotonic()
        self.started = registered_at
        self.last_activity = registered_at
        setattr(proc, "_dragontools_process_group", os.name != "nt")
        set_current_process(self.worker, self.lock, proc)
        mark_activity(f"{self.label} läuft", file_path=self.file_path, command=self.command, extra={"pid": proc.pid})

    def note_activity(self) -> None:
        self.last_activity = time.monotonic()

    def _abort_requested(self) -> bool:
        if self.worker is None:
            return False
        state = getattr(self.worker, "_control_state", None)
        requested = bool(state.abort_requested) if state is not None else bool(getattr(self.worker, "abort_requested", False))
        abort_type = state.abort_type if state is not None else getattr(self.worker, "abort_type", None)
        if not requested:
            return False
        return self.abort_on_request or abort_type == "sofort"

    def terminate(self) -> None:
        """Stop the registered process using the shared ownership policy."""
        self._terminate()

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
                process=self.proc,
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
        if self.worker is None or self.lock is None:
            return
        state = getattr(self.worker, "_control_state", None)
        paused = bool(state.paused) if state is not None else bool(getattr(self.worker, "_paused", False))
        if not paused:
            return
        pause_started = time.monotonic()
        wait_while_paused(self.worker, self.lock, process=self.proc)
        pause_duration = time.monotonic() - pause_started
        self.started += pause_duration
        self.last_activity += pause_duration

    def handle_timeout(
        self,
        *,
        display: Literal["minutes", "seconds"] = "minutes",
        message: str | None = None,
    ) -> int | None:
        if self.timeout_s is None:
            return None
        origin = self.last_activity if self.timeout_mode == "inactivity" else self.started
        if (time.monotonic() - origin) < float(self.timeout_s):
            return None

        self.timed_out = True
        if message is None:
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
        if self.proc is not None and self.proc.poll() is None:
            dispatch_log(self.log, f"{self.label}: Abschluss ohne bestätigtes Prozessende; Prozess bleibt registriert.", "error")
            mark_activity(f"{self.label}: Prozessende unbestätigt", file_path=self.file_path,
                          command=self.command, extra={"returncode": returncode, "pid": self.proc.pid})
            return
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
