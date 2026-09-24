# -*- coding: utf-8 -*-
"""Converter subprocess adapter using one shared ProcessLifecycle."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from .process_control import terminate_process_tree
from .tool_process_lifecycle import ProcessLifecycle, close_process_streams, current_process_attr, process_group_kwargs, worker_lock

def _cmd_for_log(cmd: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in cmd])

def _popen_kwargs() -> dict[str, object]:
    return {**_no_window_kwargs(), **process_group_kwargs()}

def _set_last_stderr(worker, value: str) -> None:
    target = getattr(worker, "_temp_state", worker)
    setattr(target, "stderr" if target is not worker else "_last_stderr", value)


class ConverterProcessExecutor:
    def __init__(self, worker) -> None:
        self.worker = worker
    def terminate(self, proc, *, label: str, timeout_s=None) -> None:
        if proc is None:
            return
        worker = self.worker
        lock = worker_lock(worker)
        if lock is None:
            try:
                proc.terminate()
            except OSError:
                pass
            return
        terminate_process_tree(
            worker, lock, log=worker.log, attr_name=current_process_attr(worker), label=label
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
        timeout_s = 14_400 if timeout_s is None else timeout_s
        full = [str(part) for part in cmd]
        lifecycle = self._lifecycle(full, label=label, timeout_s=timeout_s)
        lifecycle.mark_starting()
        proc = subprocess.Popen(
            full,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        lifecycle.register(proc)
        def drain_stdout() -> None:
            try:
                if proc.stdout is None:
                    return
                for _line in proc.stdout:
                    lifecycle.note_activity()
            except (OSError, ValueError):
                return
        thread = threading.Thread(target=drain_stdout, daemon=True)
        thread.start()
        rc: int | None = None
        try:
            while True:
                polled = proc.poll()
                if polled is not None:
                    rc = int(polled)
                    break
                lifecycle.handle_pause()
                abort_rc = lifecycle.handle_abort()
                if abort_rc is not None:
                    rc = abort_rc
                    break
                timeout_rc = lifecycle.handle_timeout(display="seconds")
                if timeout_rc is not None:
                    rc = timeout_rc
                    break
                time.sleep(0.1)
        finally:
            thread.join(timeout=2)
            lifecycle.finish(rc)
            close_process_streams(proc)
            if thread.is_alive():
                thread.join(timeout=0.5)
        return int(rc if rc is not None else 1)
    def run_capture(self, cmd, *, timeout_s: int | None = None, label: str = "Tool-Prozess") -> tuple[int, str, str]:
        timeout_s = 14_400 if timeout_s is None else timeout_s
        full = [str(part) for part in cmd]
        if full and Path(full[0]).stem.lower() == "ffmpeg" and "-nostdin" not in full:
            full = [full[0], "-nostdin"] + full[1:]
        lifecycle = self._lifecycle(full, label=label, timeout_s=timeout_s)
        lifecycle.mark_starting()
        proc = subprocess.Popen(
            full,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_popen_kwargs(),
        )
        lifecycle.register(proc)
        rc: int | None = None
        stdout = stderr = ""
        try:
            while True:
                lifecycle.handle_pause()
                abort_rc = lifecycle.handle_abort()
                if abort_rc is not None:
                    rc = abort_rc
                    break
                # A completed child always wins over an absolute timeout after a pause.
                polled = proc.poll()
                if polled is not None:
                    stdout, stderr = proc.communicate()
                    rc = int(polled)
                    break

                timeout_rc = lifecycle.handle_timeout(display="seconds")
                if timeout_rc is not None:
                    rc = timeout_rc
                    break
                try:
                    stdout, stderr = proc.communicate(timeout=0.2)
                    rc = int(proc.returncode or 0)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if rc in {124, 130}:
                try:
                    out, err = proc.communicate(timeout=3)
                    stdout = stdout or out or ""
                    stderr = stderr or err or ""
                except subprocess.TimeoutExpired:
                    pass
        finally:
            lifecycle.finish(rc)
            close_process_streams(proc)
        return int(rc if rc is not None else 1), stdout or "", stderr or ""

    def run_progress(self, cmd, path, dur_ms, *, timeout_s, label: str, probe_frames, read_progress) -> int:
        worker = self.worker
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
        stderr_lines: list[str] = []
        lifecycle = self._lifecycle(
            full,
            label=label,
            timeout_s=timeout_s,
            timeout_mode="inactivity",
            path=path,
        )
        lifecycle.mark_starting()
        proc = subprocess.Popen(
            full,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_popen_kwargs(),
        )
        lifecycle.register(proc)
        def note_activity() -> None:
            lifecycle.note_activity()
        def drain_stderr() -> None:
            try:
                if proc.stderr is None:
                    return
                for line in proc.stderr:
                    note_activity()
                    text = line.rstrip()
                    if text:
                        stderr_lines.append(text)
            except (OSError, ValueError):
                return

        stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
        progress_thread = threading.Thread(
            target=read_progress,
            args=(proc, path, dur_ms, total_frames, note_activity),
            daemon=True,
        )
        stderr_thread.start()
        progress_thread.start()
        rc: int | None = None
        try:
            while True:
                polled = proc.poll()
                if polled is not None:
                    rc = int(polled)
                    break
                lifecycle.handle_pause()
                abort_rc = lifecycle.handle_abort()
                if abort_rc is not None:
                    rc = abort_rc
                    break
                minutes = max(1, int(round(float(timeout_s) / 60))) if timeout_s is not None else 0
                timeout_rc = lifecycle.handle_timeout(
                    display="minutes",
                    message=(
                        f"❌ {label}: Keine ffmpeg-Rückmeldung seit {minutes} Min – Prozess wird abgebrochen."
                        if timeout_s is not None
                        else None
                    ),
                )
                if timeout_rc is not None:
                    rc = timeout_rc
                    break
                time.sleep(0.5)
        finally:
            progress_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            _set_last_stderr(worker, "\n".join(stderr_lines[-10:]))
            lifecycle.finish(rc)
            close_process_streams(proc)
            if progress_thread.is_alive():
                progress_thread.join(timeout=0.5)
            if stderr_thread.is_alive():
                stderr_thread.join(timeout=0.5)
        return int(rc if rc is not None else 1)
