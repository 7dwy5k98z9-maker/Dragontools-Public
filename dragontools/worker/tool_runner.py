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
from .tool_process_lifecycle import (
    ProcessLifecycle,
    TimeoutMode,
    close_process_streams as _close_process_streams,
    process_group_kwargs as _process_group_kwargs,
    terminate_plain as _terminate_plain,
)


LogFn = Callable[[str, str], None]
LineFn = Callable[[str], None]


def _cmd_for_log(cmd: Iterable[object]) -> str:
    return subprocess.list2cmdline([str(part) for part in cmd])


def _normalize_command(cmd: Iterable[object], *, function_name: str) -> list[str]:
    command = [str(part) for part in cmd]
    if not command:
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


def _dispatch_callbacks(
    callback_queue: "queue.SimpleQueue[tuple[LineFn, str]]",
    *,
    label: str,
    log: LogFn | None,
) -> None:
    while True:
        try:
            callback, text = callback_queue.get_nowait()
        except queue.Empty:
            return
        try:
            callback(text)
        except Exception as exc:
            if callable(log):
                log(f"{label}: Ausgabe-Callback fehlgeschlagen: {exc}", "warn")


def _start_text_drain(
    stream,
    target: list[str],
    callback: LineFn | None,
    callback_queue: "queue.SimpleQueue[tuple[LineFn, str]]",
    lifecycle: ProcessLifecycle,
) -> threading.Thread:
    def _drain() -> None:
        if stream is None:
            return
        try:
            for line in stream:
                text = line.rstrip()
                target.append(text)
                lifecycle.note_activity()
                if callable(callback):
                    callback_queue.put((callback, text))
        except (OSError, ValueError):
            return

    thread = threading.Thread(target=_drain, daemon=True)
    thread.start()
    return thread


def _join_threads(*threads: threading.Thread | None, timeout: float) -> None:
    for thread in threads:
        if thread is not None:
            thread.join(timeout=timeout)


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
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    callback_queue: "queue.SimpleQueue[tuple[LineFn, str]]" = queue.SimpleQueue()
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    rc: int | None = None

    lifecycle.mark_starting()
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
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
        stdout_thread = _start_text_drain(
            proc.stdout, stdout_lines, stdout_line, callback_queue, lifecycle
        )
        if not merge_stderr:
            stderr_thread = _start_text_drain(
                proc.stderr, stderr_lines, stderr_line, callback_queue, lifecycle
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
        _join_threads(stdout_thread, stderr_thread, timeout=2)
        _dispatch_callbacks(callback_queue, label=label, log=log)
        rc = int(rc if rc is not None else 124)
    except FileNotFoundError:
        rc = 127
        stderr_lines.append(f"Tool nicht gefunden: {command[0]}")
    finally:
        _close_process_streams(lifecycle.proc)
        _join_threads(
            stdout_thread if stdout_thread is not None and stdout_thread.is_alive() else None,
            stderr_thread if stderr_thread is not None and stderr_thread.is_alive() else None,
            timeout=0.5,
        )
        _dispatch_callbacks(callback_queue, label=label, log=log)
        lifecycle.finish(rc)

    return ToolRunResult(
        command=command,
        returncode=int(rc if rc is not None else 1),
        stdout="\n".join(stdout_lines),
        stderr="\n".join(stderr_lines),
        timed_out=lifecycle.timed_out,
        aborted=lifecycle.aborted,
        timeout_s=timeout_s,
        timeout_mode=timeout_mode,
    )


def run_tool_bytes(
    cmd: Iterable[object],
    *,
    label: str = "Tool",
    timeout_s: int | float | None = None,
    worker=None,
    log: LogFn | None = None,
    cwd: str | os.PathLike | None = None,
    abort_on_request: bool = False,
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
    )
    rc: int | None = None
    stdout = b""
    stderr = b""

    lifecycle.mark_starting()
    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=str(cwd) if cwd else None,
            **_no_window_kwargs(),
            **_process_group_kwargs(),
        )
        lifecycle.register(proc)
        while True:
            rc = lifecycle.handle_abort()
            if rc is not None:
                break
            rc = lifecycle.handle_timeout(display="seconds")
            if rc is not None:
                break
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                rc = proc.returncode
                break
            except subprocess.TimeoutExpired:
                continue

        if rc in {124, 130}:
            try:
                tail_out, tail_err = proc.communicate(timeout=2)
                stdout = stdout or tail_out or b""
                stderr = stderr or tail_err or b""
            except (subprocess.TimeoutExpired, OSError, ValueError):
                pass
    except FileNotFoundError:
        rc = 127
        stderr = f"Tool nicht gefunden: {command[0]}".encode("utf-8", errors="replace")
    finally:
        _close_process_streams(lifecycle.proc)
        lifecycle.finish(rc)

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
    if not callable(log):
        return
    name = tool_name or (Path(result.command[0]).name if result.command else label)
    if result.timed_out:
        log(f"❌ {label}: Timeout (rc={result.returncode})", "error")
    elif result.aborted:
        log(f"⏹️ {label}: durch Sofort-Abbruch beendet (rc={result.returncode})", "warn")
    else:
        log(f"❌ {label} fehlgeschlagen (rc={result.returncode})", "error")
    tail = result.tail(lines)
    if tail:
        for line in tail.splitlines():
            if line.strip():
                log(f"  {name}: {line}", "error")
