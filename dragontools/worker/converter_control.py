# -*- coding: utf-8 -*-
"""Pause-/Abort-/Prozess- und Diagnosekontrolle für ConverterThread."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.paths import path_compare_key
from .process_control import terminate_process_tree, wait_while_paused


class ConverterControlService:
    """Kapselt Thread-Kontrolle, ohne die öffentliche Worker-API zu verändern."""

    def __init__(self, worker, state=None) -> None:
        self._worker = worker
        self._state = state

    def diagnostic_snapshot(self) -> dict:
        worker = self._worker
        with worker._files_lock:
            current_file = worker._queue.current_file
            waiting = [
                path for path in list(worker._queue.files) if path != current_file
            ]
            done_files = list(worker._queue.done_files)
            pending_remove = list(worker._queue.pending_remove_files)
        state = self._state
        process_lock = state.process_lock if state is not None else worker._lock
        with process_lock:
            proc = state.current_process if state is not None else worker._current_process
            proc_args = getattr(proc, "args", None) if proc is not None else None
            proc_pid = getattr(proc, "pid", None) if proc is not None else None

        try:
            command = (
                subprocess.list2cmdline([str(part) for part in proc_args])
                if proc_args
                else ""
            )
        except Exception:
            command = str(proc_args or "")
        if len(command) > 500:
            command = command[:497] + "..."

        return {
            "type": "converter",
            "running": bool(worker.isRunning()),
            "paused": bool(state.paused if state is not None else worker._paused),
            "abort_requested": bool(state.abort_requested if state is not None else worker.abort_requested),
            "abort_type": (state.abort_type if state is not None else worker.abort_type) or "",
            "current_file": current_file or "",
            "waiting_files": waiting,
            "done_files": done_files,
            "pending_remove_files": pending_remove,
            "total_count": int(getattr(worker._runtime_state, "total_count", 0) or 0),
            "current_idx": int(getattr(worker._runtime_state, "current_idx", 0) or 0),
            "success_count": int(getattr(worker._runtime_state, "erfolgreich", 0) or 0),
            "error_count": int(getattr(worker._runtime_state, "fehlgeschlagen", 0) or 0),
            "log_file": getattr(worker, "log_file_path", "") or "",
            "process_pid": proc_pid,
            "process_command": command,
        }

    def pause(self) -> None:
        worker = self._worker
        if self._state is not None:
            self._state.paused = True
            self._state.pause_event.clear()
        else:
            worker._paused = True
            worker._pause_ev.clear()
        worker._logger.info("⏸️ Pausiert.")

    def resume(self) -> None:
        worker = self._worker
        if self._state is not None:
            self._state.paused = False
            self._state.pause_event.set()
        else:
            worker._paused = False
            worker._pause_ev.set()
        worker._logger.info("▶ Fortgesetzt.")

    def request_abort(self, mode: str = "sofort") -> None:
        worker = self._worker
        if self._state is not None:
            self._state.abort_requested = True
            self._state.abort_type = mode
            paused = self._state.paused
        else:
            worker.abort_requested = True
            worker.abort_type = mode
            paused = worker._paused
        if paused:
            worker.resume()
        if mode == "sofort":
            terminate_process_tree(
                worker,
                self._state.process_lock if self._state is not None else worker._lock,
                log=worker.log,
                attr_name="_current_process",
                label="Converter-Prozess",
            )

    def terminate_current_ffmpeg(self, path: str | None = None) -> bool:
        worker = self._worker
        with worker._files_lock:
            current_file = worker._queue.current_file
        if not current_file:
            return False
        if path and path_compare_key(path) != path_compare_key(current_file):
            return False

        state = self._state
        process_lock = state.process_lock if state is not None else worker._lock
        with process_lock:
            proc = state.current_process if state is not None else worker._current_process
            proc_args = getattr(proc, "args", None) if proc is not None else None
        if proc is None or proc.poll() is not None:
            return False

        if isinstance(proc_args, (list, tuple)) and proc_args:
            executable = str(proc_args[0])
        else:
            executable = str(proc_args or "")
        executable_name = executable.replace("\\", "/").rsplit("/", 1)[-1]
        if Path(executable_name).stem.lower() != "ffmpeg":
            worker.log(
                f"⏹️ {Path(current_file).name}: aktueller Teilprozess ist kein FFmpeg-Prozess.",
                "info",
            )
            return False

        worker.log(
            f"⏹️ FFmpeg für aktuelle Datei wird beendet: {Path(current_file).name}. "
            "Die restliche Queue läuft weiter.",
            "warn",
        )
        return terminate_process_tree(
            worker,
            self._state.process_lock if self._state is not None else worker._lock,
            log=worker.log,
            attr_name="_current_process",
            label=f"FFmpeg ({Path(current_file).name})",
        )

    def clear_abort_request(self) -> bool:
        worker = self._worker
        state = self._state
        abort_requested = state.abort_requested if state is not None else worker.abort_requested
        abort_type = state.abort_type if state is not None else worker.abort_type
        if not abort_requested or abort_type != "nach_datei":
            return False
        if state is not None:
            state.abort_requested = False
            state.abort_type = None
        else:
            worker.abort_requested = False
            worker.abort_type = None
        worker.log("↩️ Abbruch nach Datei zurückgenommen.", "info")
        return True

    def wait(self) -> None:
        worker = self._worker
        wait_while_paused(
            worker,
            self._state.process_lock if self._state is not None else worker._lock,
        )
