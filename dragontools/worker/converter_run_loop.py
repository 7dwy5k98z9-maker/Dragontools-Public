# -*- coding: utf-8 -*-
"""Queue- und Session-Orchestrierung für den Converter-Worker."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from ..core.crash_guard import mark_activity
from ..core.paths import path_compare_key
from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs


def quick_video_resolution(path: str, ffprobe: str) -> tuple[int, int] | None:
    """Liest nur Breite/Höhe des ersten Videostreams; Fehler bleiben nicht-fatal."""
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            **_no_window_kwargs(),
        )
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if streams:
            width = streams[0].get("width", 0)
            height = streams[0].get("height", 0)
            if width and height:
                return int(width), int(height)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        return None
    return None


class ConverterRunLoop:
    """Steuert Session-Header, Live-Queue und Fortschritt ohne Pipeline-Fachlogik."""

    def __init__(self, worker) -> None:
        self._worker = worker

    def execute(self) -> None:
        worker = self._worker
        session = getattr(worker, "_session_state", None)
        if session is not None:
            session.run_start_ts = time.time()
        else:
            worker._run_start_ts = time.time()
        total = worker._runtime_state.total_count
        mark_activity(
            "Konvertierungsworker gestartet",
            extra={
                "total_files": total,
                "log_file": worker.log_file_path or "",
                "verbose_log": str(getattr(worker._verbose_logger, "log_file", "") or ""),
            },
        )
        self._write_session_header(total)

        done_count = 0
        while True:
            worker.wait_if_paused()
            if self._should_stop(done_count):
                break

            next_item = worker._queue.next_file(done_count)
            worker.files = worker._queue.files
            if next_item is None:
                break
            path, total_now = next_item
            self._process_file(path, done_count, total_now)
            done_count += 1

    def _write_session_header(self, total: int) -> None:
        worker = self._worker
        session = getattr(worker, "_session_state", None)
        if (session.suppress_session_header if session is not None else worker._suppress_session_header):
            return
        job = getattr(worker, "_job_state", worker)
        worker._logger.header(
            gpus=worker._log_gpu_list,
            chosen_encoder=worker._log_enc_name,
            total_files=total,
            codec=job.codec,
            crf=job.crf,
            preset=job.preset,
            scale_mode=job.scale_mode,
            overwrite_original=job.overwrite_original,
            strip_only=job.strip_only,
            encoder_options=job.encoder_options,
            manual_override_count=len(job.file_overrides),
        )

    def _should_stop(self, done_count: int) -> bool:
        worker = self._worker
        control = getattr(worker, "_control_state", None)
        abort_requested = control.abort_requested if control is not None else worker.abort_requested
        abort_type = control.abort_type if control is not None else worker.abort_type
        if not abort_requested:
            return False
        if abort_type == "sofort":
            worker.log("⛔ Abbruch.", "warn")
            return True
        if abort_type == "nach_datei" and done_count > 0:
            worker.log("⛔ Abbruch nach Datei.", "warn")
            return True
        return False

    def _process_file(self, path: str, done_count: int, total_now: int) -> None:
        worker = self._worker
        display_idx, display_total = self._display_position(
            path,
            fallback_idx=done_count + 1,
            fallback_total=total_now,
        )
        worker._runtime_state.current_idx = display_idx
        worker._runtime_state.total_count = display_total

        services = getattr(worker, "_services", None)
        tools = services.tools if services is not None else worker.tools
        resolution = quick_video_resolution(path, tools.ffprobe)
        resolution_text = (
            f" ({resolution[0]} x {resolution[1]})" if resolution else ""
        )
        worker.log(
            f"▶ Datei [{display_idx}/{display_total}]: {Path(path).name}{resolution_text}",
            "info",
        )
        mark_activity(
            "Datei wird konvertiert",
            file_path=path,
            extra={
                "index": display_idx,
                "total": display_total,
                "log_file": worker.log_file_path or "",
                "verbose_log": str(getattr(worker._verbose_logger, "log_file", "") or ""),
            },
        )
        worker.progress.emit(int(done_count / max(total_now, 1) * 100))
        worker.convert_file(path)
        worker._queue.complete_current(path)
        worker.files = worker._queue.files

        completed = done_count + 1
        total_after = worker._queue.total_after_processed(completed)
        mark_activity(
            "Datei abgeschlossen",
            file_path=path,
            extra={"completed": completed, "total": total_after},
        )
        worker.progress.emit(int(completed / max(total_after, 1) * 100))

    def _display_position(
        self,
        path: str,
        fallback_idx: int,
        fallback_total: int,
    ) -> tuple[int, int]:
        worker = self._worker
        session = getattr(worker, "_session_state", None)
        display_index_by_path = (
            session.display_index_by_path if session is not None else worker._display_index_by_path
        )
        display_total = session.display_total if session is not None else worker._display_total
        try:
            idx = int(display_index_by_path.get(path_compare_key(path), fallback_idx))
        except (AttributeError, TypeError, ValueError):
            idx = fallback_idx
        try:
            total = int(display_total or fallback_total)
        except (AttributeError, TypeError, ValueError):
            total = fallback_total
        return max(1, idx), max(1, total)
