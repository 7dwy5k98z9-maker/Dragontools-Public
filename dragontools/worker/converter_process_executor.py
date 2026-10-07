# -*- coding: utf-8 -*-
"""Converter subprocess adapter using one shared ProcessLifecycle."""
from __future__ import annotations

import subprocess
import queue
import threading
import time
from pathlib import Path

from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from ..core.owned_process import spawn_owned_process, close_owned_job
from .tool_runner import run_tool
from .tool_output_buffer import ToolOutputBuffer
from .tool_text_output import _start_text_drain, _dispatch_callbacks, _finish_text_drains
from .process_control import terminate_process_tree
from .tool_process_lifecycle import ProcessLifecycle, close_process_streams, current_process_attr, process_group_kwargs, worker_lock

def _cmd_for_log(cmd: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in cmd])

def _popen_kwargs() -> dict[str, object]:
    return {**_no_window_kwargs(), **process_group_kwargs()}

def _set_last_stderr(worker, value: str) -> None:
    target = getattr(worker, "_temp_state", worker)
    setattr(target, "stderr" if target is not worker else "_last_stderr", value)


def _is_x265_runtime_diagnostic(text: str) -> bool:
    """Keep only compact x265 startup diagnostics useful for CPU bottleneck analysis."""
    value = str(text or "").strip()
    lowered = value.casefold()
    if not lowered.startswith("x265 ["):
        return False
    if "[warning]" in lowered or "[error]" in lowered:
        return True
    return any(
        marker in lowered
        for marker in (
            "using cpu capabilities",
            "thread pool",
            "frame threads / pool features",
            "lookahead / bframes",
        )
    )


def _stop_owned_converter(lifecycle):
    try:
        if lifecycle.proc is not None and lifecycle.proc.poll() is None:
            lifecycle.terminate()
    finally:
        close_owned_job(lifecycle.proc)


def _wait_progress_process(lifecycle, progress_errors, callback_queue):
    minutes = max(1, int(round(float(lifecycle.timeout_s) / 60))) if lifecycle.timeout_s is not None else 0
    while True:
        _dispatch_callbacks(callback_queue, label=lifecycle.label, log=lifecycle.log)
        if progress_errors:
            raise progress_errors[0]
        polled = lifecycle.proc.poll()
        if polled is not None:
            return int(polled)
        lifecycle.handle_pause()
        rc = lifecycle.handle_abort()
        if rc is not None:
            return rc
        rc = lifecycle.handle_timeout(display="minutes", message=(
            f"❌ {lifecycle.label}: Keine ffmpeg-Rückmeldung seit {minutes} Min – Prozess wird abgebrochen."
            if lifecycle.timeout_s is not None else None))
        if rc is not None:
            return rc
        time.sleep(0.1)


class ConverterProcessExecutor:
    def __init__(self, worker) -> None:
        self.worker = worker
    def terminate(self, proc, *, label: str, timeout_s=None) -> None:
        if proc is None:
            return
        worker = self.worker
        lock = worker_lock(worker) or threading.Lock()
        terminate_process_tree(
            worker, lock, log=worker.log, attr_name=current_process_attr(worker), label=label,
            process=proc, terminate_timeout=3 if timeout_s is None else timeout_s,
        )

    def _lifecycle(
        self,
        command: list[str],
        *,
        label: str,
        timeout_s: int | float | None,
        timeout_mode: str = "absolute",
        path=None,
    ) -> ProcessLifecycle:
        return ProcessLifecycle(
            command=command, label=label, timeout_s=timeout_s, worker=self.worker,
            log=self.worker.log, timeout_mode=timeout_mode, file_path=path,
        )
    def run(self, cmd, *, timeout_s: int | None = None, label: str = "Subprozess") -> int:
        result = run_tool(cmd, label=label, timeout_s=14_400 if timeout_s is None else timeout_s,
                          worker=self.worker, log=self.worker.log,
                          stdout_file=subprocess.DEVNULL, merge_stderr=True)
        return result.returncode

    def run_capture(self, cmd, *, timeout_s: int | None = None, label: str = "Tool-Prozess") -> tuple[int, str, str]:
        full = [str(part) for part in cmd]
        if full and Path(full[0]).stem.lower() == "ffmpeg" and "-nostdin" not in full:
            full = [full[0], "-nostdin"] + full[1:]
        result = run_tool(full, label=label, timeout_s=14_400 if timeout_s is None else timeout_s,
                          worker=self.worker, log=self.worker.log)
        return result.returncode, result.stdout, result.stderr

    def run_progress(self, cmd, path, dur_ms, *, timeout_s, label: str, probe_frames, read_progress) -> int:
        worker = self.worker
        counts = getattr(worker, "_progress_frame_counts", None)
        if not isinstance(counts, dict):
            counts = {}
            setattr(worker, "_progress_frame_counts", counts)
        counts.pop(str(path), None)
        completed = getattr(worker, "_progress_end_seen", None)
        if not isinstance(completed, dict):
            completed = {}
            setattr(worker, "_progress_end_seen", completed)
        completed.pop(str(path), None)
        total_frames = None if dur_ms else probe_frames(path)
        full = [str(part) for part in cmd]
        if full and Path(full[0]).stem.lower() == "ffmpeg":
            progress_args: list[str] = []
            if "-nostdin" not in full:
                full = [full[0], "-nostdin"] + full[1:]
            if "-progress" not in full:
                progress_args += ["-progress", "pipe:1"]
            if "-nostats" not in full:
                progress_args.append("-nostats")
            if progress_args:
                insert_at = max(1, len(full) - 1)
                full = full[:insert_at] + progress_args + full[insert_at:]
            verbose = getattr(worker, "_verbose_logger", None)
            if verbose:
                verbose.write(f"[FFMPEG FINAL CMD] {_cmd_for_log(full)}")
        _set_last_stderr(worker, "")
        stderr_lines = ToolOutputBuffer(limit=256 * 1024)
        lifecycle = self._lifecycle(
            full,
            label=label,
            timeout_s=timeout_s,
            timeout_mode="inactivity",
            path=path,
        )
        lifecycle.mark_starting()
        proc = spawn_owned_process(
            full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **_popen_kwargs(),
        )
        callback_queue = queue.Queue(maxsize=256)
        stop = threading.Event()
        progress_errors = []
        stderr_thread = progress_thread = None
        rc = None
        verbose = getattr(worker, "_verbose_logger", None)

        def log_runtime_line(text):
            if verbose is not None and _is_x265_runtime_diagnostic(text):
                verbose.write(f"[X265 RUNTIME] {text}")

        def consume_progress():
            try:
                read_progress(proc, path, dur_ms, total_frames, lifecycle.note_activity)
            except BaseException as exc:
                progress_errors.append(exc)

        try:
            lifecycle.register(proc)
            stderr_thread = _start_text_drain(proc.stderr, stderr_lines,
                log_runtime_line if verbose is not None else None, callback_queue, lifecycle, stop)
            progress_thread = threading.Thread(target=consume_progress, daemon=True)
            progress_thread.start()
            rc = _wait_progress_process(lifecycle, progress_errors, callback_queue)
        finally:
            try:
                _stop_owned_converter(lifecycle)
                drained = _finish_text_drains((progress_thread, stderr_thread), callback_queue,
                                              label=label, log=worker.log)
                if rc == 0 and (not drained or stderr_lines.read_error):
                    rc = 75
                    stderr_lines.append(f"\nTool-Ausgabe unvollständig: {stderr_lines.read_error}")
                if progress_errors and rc in {None, 0}:
                    rc = 1
                diagnostic = "\n".join(stderr_lines.text().splitlines()[-10:])
                if stderr_lines.truncated:
                    diagnostic = "[Diagnoseausgabe gekürzt]\n" + diagnostic
                _set_last_stderr(worker, diagnostic)
                lifecycle.finish(rc)
            finally:
                stop.set()
                close_owned_job(proc)
                close_process_streams(proc)
                stderr_lines.release()
        if progress_errors:
            raise progress_errors[0]
        return int(rc if rc is not None else 1)
