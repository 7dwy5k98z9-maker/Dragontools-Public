# -*- coding: utf-8 -*-
"""Subprocess lifecycle for converter helper operations."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from ..core.crash_guard import mark_activity
from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from .process_control import terminate_process_tree


def _cmd_for_log(cmd: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in cmd])


def _close_process_streams(proc) -> None:
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


class ConverterProcessExecutor:
    def __init__(self, worker) -> None:
        self.worker = worker

    def terminate(self, proc, *, label: str, timeout_s=None) -> None:
        if proc is None:
            return
        worker = self.worker
        terminate_process_tree(worker, worker._lock, log=worker.log, attr_name="_current_process", label=label)

    def _register(self, proc, label: str, command, *, path=None) -> None:
        worker = self.worker
        with worker._lock:
            worker._current_process = proc
        mark_activity(f"{label} laeuft", file_path=path, command=command, extra={"pid": proc.pid})

    def _clear(self, proc, label: str, command, rc, *, path=None) -> None:
        _close_process_streams(proc)
        worker = self.worker
        with worker._lock:
            if worker._current_process is proc:
                worker._current_process = None
        mark_activity(f"{label} beendet", file_path=path, command=command, extra={"returncode": rc})

    def run(self, cmd, *, timeout_s: int | None = None, label: str = "Subprozess") -> int:
        worker = self.worker
        timeout_s = 14_400 if timeout_s is None else timeout_s
        mark_activity(f"{label} wird gestartet", command=cmd)
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", **_no_window_kwargs(),
        )
        self._register(proc, label, cmd)

        def drain_stdout():
            try:
                for _line in proc.stdout:
                    worker.wait_if_paused()
            except (OSError, ValueError):
                return

        thread = threading.Thread(target=drain_stdout, daemon=True)
        thread.start()
        rc = None
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            worker.log(f"❌ {label}: Timeout nach {timeout_s}s – Prozess wird abgebrochen.", "error")
            self.terminate(proc, label=label, timeout_s=timeout_s)
            rc = 124
        finally:
            thread.join(timeout=2)
            self._clear(proc, label, cmd, rc)
            if thread.is_alive():
                thread.join(timeout=0.5)
        return rc

    def run_capture(self, cmd, *, timeout_s: int | None = None, label: str = "Tool-Prozess") -> tuple[int, str, str]:
        worker = self.worker
        timeout_s = 14_400 if timeout_s is None else timeout_s
        full = list(cmd)
        if full and Path(full[0]).stem.lower() == "ffmpeg" and "-nostdin" not in full:
            full = [full[0], "-nostdin"] + full[1:]
        mark_activity(f"{label} wird gestartet", command=full)
        proc = subprocess.Popen(
            full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", **_no_window_kwargs(),
        )
        self._register(proc, label, full)
        start = time.monotonic()
        rc = None
        stdout = stderr = ""
        try:
            while True:
                if getattr(worker, "abort_requested", False) and getattr(worker, "abort_type", "") == "sofort":
                    self.terminate(proc, label=label, timeout_s=timeout_s)
                    rc = 130
                    break
                if timeout_s is not None and time.monotonic() - start >= timeout_s:
                    worker.log(f"❌ {label}: Timeout nach {timeout_s}s – Prozess wird abgebrochen.", "error")
                    self.terminate(proc, label=label, timeout_s=timeout_s)
                    rc = 124
                    break
                try:
                    stdout, stderr = proc.communicate(timeout=0.2)
                    rc = int(proc.returncode or 0)
                    break
                except subprocess.TimeoutExpired:
                    if getattr(worker, "_paused", False):
                        worker.wait_if_paused()
            if rc in {124, 130}:
                try:
                    out, err = proc.communicate(timeout=3)
                    stdout = stdout or out or ""
                    stderr = stderr or err or ""
                except subprocess.TimeoutExpired:
                    pass
        finally:
            self._clear(proc, label, full, rc)
        return int(rc if rc is not None else 1), stdout or "", stderr or ""

    def run_progress(self, cmd, path, dur_ms, *, timeout_s, label: str, probe_frames, read_progress) -> int:
        worker = self.worker
        total_frames = None if dur_ms else probe_frames(path)
        full = list(cmd)
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
        worker._last_stderr = ""
        stderr_lines: list[str] = []
        mark_activity(f"{label} wird gestartet", file_path=path, command=full)
        proc = subprocess.Popen(
            full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", **_no_window_kwargs(), bufsize=1,
        )
        self._register(proc, label, full, path=path)
        last_activity = [time.monotonic()]

        def note_activity():
            last_activity[0] = time.monotonic()

        def drain_stderr():
            try:
                for line in proc.stderr:
                    note_activity()
                    text = line.rstrip()
                    if text:
                        stderr_lines.append(text)
            except (OSError, ValueError):
                return

        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        progress_thread = threading.Thread(
            target=read_progress, args=(proc, path, dur_ms, total_frames, note_activity), daemon=True
        )
        stderr_thread.start()
        progress_thread.start()
        rc = None
        try:
            while True:
                rc = proc.poll()
                if rc is not None:
                    break
                if getattr(worker, "_paused", False):
                    worker.wait_if_paused()
                    note_activity()
                    continue
                if worker.abort_requested and worker.abort_type == "sofort":
                    self.terminate(proc, label=label, timeout_s=timeout_s)
                    rc = 130
                    break
                if timeout_s is not None and time.monotonic() - last_activity[0] >= timeout_s:
                    mins = max(1, int(round(timeout_s / 60)))
                    worker.log(f"❌ {label}: Keine ffmpeg-Rückmeldung seit {mins} Min – Prozess wird abgebrochen.", "error")
                    self.terminate(proc, label=label, timeout_s=timeout_s)
                    rc = 124
                    break
                time.sleep(0.5)
        finally:
            progress_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            worker._last_stderr = "\n".join(stderr_lines[-10:])
            self._clear(proc, label, full, rc, path=path)
            if progress_thread.is_alive():
                progress_thread.join(timeout=0.5)
            if stderr_thread.is_alive():
                stderr_thread.join(timeout=0.5)
        return rc
