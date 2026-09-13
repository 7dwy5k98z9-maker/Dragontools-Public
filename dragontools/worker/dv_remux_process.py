# -*- coding: utf-8 -*-
"""Process execution helpers for the Dolby Vision remux worker."""
from __future__ import annotations

import time
from pathlib import Path

from ..core.timeout_settings import get_timeout
from .tool_runner import run_tool


class DVRemuxProcessRunner:
    """Execute ffmpeg/ffprobe/muxer processes for a DV-remux worker."""

    def __init__(self, worker):
        self.worker = worker

    def run_cmd(
        self,
        cmd: list[str],
        input_path: str | None = None,
        dur_ms: int | None = None,
        pct_range: tuple[int, int] = (0, 95),
    ) -> int:
        w = self.worker
        full = [*cmd, "-progress", "pipe:1", "-nostats"]
        w._last_stderr = ""
        start = time.time()
        last_out_ms = 0
        last_speed: float | None = None

        def _progress_line(raw_line: str) -> None:
            nonlocal last_out_ms, last_speed
            line = raw_line.strip()
            if not line or "=" not in line:
                return
            key, value = line.split("=", 1)
            if key == "speed":
                try:
                    parsed = float(value.strip().lower().rstrip("x"))
                    if parsed > 0:
                        last_speed = parsed
                except (TypeError, ValueError):
                    pass
                return
            if key != "out_time_ms" or not dur_ms:
                return
            try:
                last_out_ms = max(0, int(int(value) / 1000))
                raw_pct = min(100, int(last_out_ms / dur_ms * 100))
                start_pct, end_pct = pct_range
                pct = start_pct + int(raw_pct * (end_pct - start_pct) / 100)
                pct = max(start_pct, min(end_pct, pct))
                eta_s = self._estimate_eta(
                    start=start,
                    last_out_ms=last_out_ms,
                    last_speed=last_speed,
                    dur_ms=dur_ms,
                    pct_range=pct_range,
                )
                if input_path:
                    w.file_progress.emit(input_path, pct, eta_s)
            except (TypeError, ValueError, ZeroDivisionError):
                return

        result = run_tool(
            full,
            label="DV-Remux ffmpeg",
            timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity",
            worker=w,
            log=w._log,
            stdout_line=_progress_line,
        )
        stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
        w._last_stderr = "\n".join(stderr_lines[-10:])
        if not result.ok:
            self._log_process_failure(cmd, result, stderr_lines)
        return result.returncode

    @staticmethod
    def _estimate_eta(
        *,
        start: float,
        last_out_ms: int,
        last_speed: float | None,
        dur_ms: int,
        pct_range: tuple[int, int],
    ) -> float | None:
        if last_out_ms <= 0:
            return None
        phase_fraction = (pct_range[1] - pct_range[0]) / 100.0
        remaining_ms = max(0.0, dur_ms * phase_fraction - last_out_ms)
        if last_speed and last_speed > 0:
            return (remaining_ms / 1000.0) / last_speed
        elapsed = max(0.001, time.time() - start)
        derived_speed = (last_out_ms / 1000.0) / elapsed
        if derived_speed <= 0:
            return None
        return (remaining_ms / 1000.0) / derived_speed

    def _log_process_failure(self, cmd, result, stderr_lines: list[str]) -> None:
        w = self.worker
        tool = Path(cmd[0]).name if cmd else "Tool"
        if result.timed_out:
            w.log(f"❌ {tool}: Inaktivitäts-Timeout", "error")
        elif result.aborted:
            w.log(f"⏹️ {tool}: abgebrochen", "warn")
        else:
            w.log(f"❌ {tool} fehlgeschlagen (rc={result.returncode})", "error")
        for line in stderr_lines[-5:]:
            if line.strip():
                w.log(f"  {tool}: {line}", "error")

    def probe_ms(self, path: str) -> int | None:
        w = self.worker
        try:
            result = run_tool(
                [
                    w.tools.ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                label="DV-Remux ffprobe",
                timeout_s=get_timeout("media_analysis"),
                worker=w,
                log=w._log,
            )
            if not result.ok:
                return None
            value = result.stdout.strip()
            return int(float(value) * 1000) if value else None
        except (TypeError, ValueError, OSError):
            return None

    def run_abortable_capture(
        self,
        cmd: list[str],
        *,
        timeout_s: int | None = None,
    ) -> tuple[int, str, str]:
        w = self.worker
        effective_timeout = get_timeout("dv_mp4box") if timeout_s is None else timeout_s
        result = run_tool(
            cmd,
            label="DV-Remux-Prozess",
            timeout_s=effective_timeout,
            worker=w,
            log=w._log,
        )
        return result.returncode, result.stdout, result.stderr
