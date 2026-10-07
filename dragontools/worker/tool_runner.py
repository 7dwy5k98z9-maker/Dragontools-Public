# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from ..core.owned_process import close_owned_job, spawn_owned_process
from .log_dispatch import dispatch_log
from .tool_binary_output import BinaryOutputCapture
from .tool_output_buffer import ToolOutputBuffer
from .tool_text_output import (_dispatch_callbacks, _start_text_drain, _join_threads, _finish_text_drains)
from .tool_process_lifecycle import (
    ProcessLifecycle,
    TimeoutMode,
    close_process_streams as _close_process_streams,
    process_group_kwargs as _process_group_kwargs,
    terminate_plain as _terminate_plain,
)


LogFn = Callable[[str, str], None]
LineFn = Callable[[str], None]
MAX_BINARY_OUTPUT_BYTES = 64 * 1024 * 1024


def _cmd_for_log(cmd: Iterable[object]) -> str:
    return subprocess.list2cmdline([str(part) for part in cmd])


def _normalize_command(cmd: Iterable[object], *, function_name: str) -> list[str]:
    if cmd is None or isinstance(cmd, (str, bytes)):
        raise ValueError(f"{function_name}() erwartet eine Liste von Kommandoargumenten.")
    command = [str(part) for part in cmd]
    if not command or not command[0].strip():
        raise ValueError(f"{function_name}() benötigt ein nicht-leeres Kommando.")
    return command


@dataclass
class ToolRunResult:
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    aborted: bool = False
    timeout_s: int | float | None = None
    timeout_mode: TimeoutMode = "absolute"

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in (self.stderr, self.stdout) if part).strip()

    def tail(self, lines: int = 10) -> str:
        text = self.combined_output
        if not text:
            return ""
        return "\n".join(text.splitlines()[-max(1, int(lines)):])


@dataclass
class ToolBytesResult:
    command: list[str]
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    aborted: bool = False
    timeout_s: int | float | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _finalize_text_capture(lifecycle, rc, stop, threads, callback_queue, stdout_lines, stderr_lines, label, log):
    if lifecycle.proc is not None and lifecycle.proc.poll() is None:
        lifecycle.terminate()
    close_owned_job(lifecycle.proc)
    stop.set()
    _close_process_streams(lifecycle.proc)
    _join_threads(*threads, timeout=0.5)
    _dispatch_callbacks(callback_queue, label=label, log=log)
    stdout_text, stderr_text = stdout_lines.text(), stderr_lines.text()
    if stdout_lines.read_error or stderr_lines.read_error:
        if rc == 0:
            rc = 75
        stderr_text += f"\nTool-Ausgabe unvollständig: {stdout_lines.read_error or stderr_lines.read_error}"
    if stdout_lines.truncated and rc == 0:
        rc = 75
        stderr_text += "\nStandardausgabe überschreitet Speichergrenze; Ausgabe nicht vollständig."
    if stderr_lines.truncated:
        stderr_text = "[Diagnoseausgabe gekürzt]\n" + stderr_text
    stdout_lines.release()
    stderr_lines.release()
    lifecycle.finish(rc)
    return rc, stdout_text, stderr_text


def run_tool(
    cmd: Iterable[object],
    *,
    label: str = "Tool",
    timeout_s: int | float | None = None,
    worker=None,
    log: LogFn | None = None,
    cwd: str | os.PathLike | None = None,
    abort_on_request: bool = False,
    stdout_line: LineFn | None = None,
    stderr_line: LineFn | None = None,
    timeout_mode: TimeoutMode = "absolute",
    merge_stderr: bool = False,
    activity_file: str | os.PathLike | None = None,
    stdout_file=None,
) -> ToolRunResult:
    """Run a text-producing tool with shared timeout/abort/process semantics."""
    command = _normalize_command(cmd, function_name="run_tool")
    lifecycle = ProcessLifecycle(
        command=command,
        label=label,
        timeout_s=timeout_s,
        worker=worker,
        log=log,
        abort_on_request=abort_on_request,
        timeout_mode=timeout_mode,
        file_path=activity_file,
    )
    stdout_lines = ToolOutputBuffer()
    stderr_lines = ToolOutputBuffer(limit=256 * 1024)
    callback_queue = queue.Queue(maxsize=256)
    stop = threading.Event()
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    rc: int | None = None

    lifecycle.mark_starting()
    try:
        proc = spawn_owned_process(
            command,
            stdout=stdout_file if stdout_file is not None else subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd else None,
            bufsize=1,
            **_no_window_kwargs(),
            **_process_group_kwargs(),
        )
        lifecycle.register(proc)
        if stdout_file is None:
            stdout_thread = _start_text_drain(
                proc.stdout, stdout_lines, stdout_line, callback_queue, lifecycle, stop
            )
        if not merge_stderr:
            stderr_thread = _start_text_drain(
                proc.stderr, stderr_lines, stderr_line, callback_queue, lifecycle, stop
            )

        while True:
            _dispatch_callbacks(callback_queue, label=label, log=log)
            rc = lifecycle.handle_abort()
            if rc is not None:
                break
            rc = proc.poll()
            if rc is not None:
                break
            lifecycle.handle_pause()
            rc = lifecycle.handle_timeout(display="minutes")
            if rc is not None:
                break
            time.sleep(0.25)

        if rc is None:
            try:
                rc = proc.wait(timeout=1)
            except (subprocess.TimeoutExpired, OSError):
                rc = proc.poll()
        if proc.poll() is not None:
            close_owned_job(proc)
        drained = _finish_text_drains((stdout_thread, stderr_thread), callback_queue, label=label, log=log)
        if not drained and rc == 0:
            rc = 75
            stderr_lines.append("Tool-Ausgabe konnte nicht vollständig gelesen werden.")
        _dispatch_callbacks(callback_queue, label=label, log=log)
        rc = int(rc if rc is not None else 124)
    except FileNotFoundError as exc:
        rc = 127
        stderr_lines.append(
            f"Tool oder Arbeitsverzeichnis nicht gefunden: {command[0]} ({exc})"
        )
    except PermissionError as exc:
        rc = 126
        stderr_lines.append(f"Tool konnte wegen fehlender Berechtigung nicht gestartet werden: {exc}")
    except OSError as exc:
        # Popen can fail for invalid executables, broken network paths or OS
        # resource errors before a child process exists.  Convert those start
        # failures into the same structured result contract as tool exit codes
        # instead of crashing the worker thread.
        rc = 126
        stderr_lines.append(f"Tool konnte nicht gestartet werden: {exc}")
    finally:
        rc, stdout_text, stderr_text = _finalize_text_capture(
            lifecycle, rc, stop, (stdout_thread, stderr_thread), callback_queue,
            stdout_lines, stderr_lines, label, log,
        )

    return ToolRunResult(
        command=command,
        returncode=int(rc if rc is not None else 1),
        stdout=stdout_text,
        stderr=stderr_text,
        timed_out=lifecycle.timed_out,
        aborted=lifecycle.aborted,
        timeout_s=timeout_s,
        timeout_mode=timeout_mode,
    )


def _wait_binary_tool(proc, lifecycle, capture):
    while True:
        rc = lifecycle.handle_abort()
        if rc is not None:
            return rc
        lifecycle.handle_pause()
        polled = proc.poll()
        if polled is not None:
            return int(polled)
        rc = lifecycle.handle_timeout(display="seconds")
        if rc is not None:
            return rc
        if capture.overflow(MAX_BINARY_OUTPUT_BYTES):
            lifecycle.terminate()
            return 75
        try:
            return proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            continue


def run_tool_bytes(
    cmd: Iterable[object],
    *,
    label: str = "Tool",
    timeout_s: int | float | None = None,
    worker=None,
    log: LogFn | None = None,
    cwd: str | os.PathLike | None = None,
    abort_on_request: bool = False,
    activity_file: str | os.PathLike | None = None,
) -> ToolBytesResult:
    """Run a binary-producing tool using the same process lifecycle as run_tool."""
    command = _normalize_command(cmd, function_name="run_tool_bytes")
    lifecycle = ProcessLifecycle(
        command=command,
        label=label,
        timeout_s=timeout_s,
        worker=worker,
        log=log,
        abort_on_request=abort_on_request,
        file_path=activity_file,
    )
    rc: int | None = None
    stdout = b""
    stderr = b""
    capture = None
    lifecycle.mark_starting()
    try:
        capture = BinaryOutputCapture()
        proc = spawn_owned_process(
            command, stdout=capture.stdout, stderr=capture.stderr,
            stdin=subprocess.DEVNULL, cwd=str(cwd) if cwd else None,
            **_no_window_kwargs(), **_process_group_kwargs(),
        )
        lifecycle.register(proc)
        rc = _wait_binary_tool(proc, lifecycle, capture)
    except FileNotFoundError as exc:
        rc = 127
        stderr = f"Tool oder Arbeitsverzeichnis nicht gefunden: {command[0]} ({exc})".encode("utf-8", errors="replace")
    except PermissionError as exc:
        rc = 126
        stderr = f"Tool konnte wegen fehlender Berechtigung nicht gestartet werden: {exc}".encode("utf-8", errors="replace")
    except OSError as exc:
        rc = 126
        stderr = f"Tool konnte nicht gestartet werden: {exc}".encode("utf-8", errors="replace")
    finally:
        try:
            if lifecycle.proc is not None:
                if lifecycle.proc.poll() is None:
                    lifecycle.terminate()
                close_owned_job(lifecycle.proc)
                stdout, error_output, truncated = capture.read(MAX_BINARY_OUTPUT_BYTES)
                stderr += error_output
                if truncated and rc == 0:
                    rc = 75
            lifecycle.finish(rc)
        finally:
            close_owned_job(lifecycle.proc)
            if capture is not None:
                capture.close()

    return ToolBytesResult(
        command=command,
        returncode=int(rc if rc is not None else 1),
        stdout=stdout or b"",
        stderr=stderr or b"",
        timed_out=lifecycle.timed_out,
        aborted=lifecycle.aborted,
        timeout_s=timeout_s,
    )


def log_tool_failure(
    result: ToolRunResult,
    *,
    label: str,
    log: LogFn | None,
    tool_name: str | None = None,
    lines: int = 5,
) -> None:
    if log is None:
        return
    name = tool_name or (Path(result.command[0]).name if result.command else label)
    if result.timed_out:
        dispatch_log(log, f"❌ {label}: Timeout (rc={result.returncode})", "error")
    elif result.aborted:
        dispatch_log(log, f"⏹️ {label}: durch Sofort-Abbruch beendet (rc={result.returncode})", "warn")
    else:
        dispatch_log(log, f"❌ {label} fehlgeschlagen (rc={result.returncode})", "error")
    tail = result.tail(lines)
    if tail:
        for line in tail.splitlines():
            if line.strip():
                dispatch_log(log, f"  {name}: {line}", "error")
