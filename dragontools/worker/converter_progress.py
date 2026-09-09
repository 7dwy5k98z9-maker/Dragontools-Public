# -*- coding: utf-8 -*-
"""Facade for converter probing, progress parsing and subprocess execution."""
from __future__ import annotations

from ..core.timeout_settings import get_timeout
from .converter_media_probe import probe_frames as _probe_frames, probe_ms as _probe_ms
from .converter_process_executor import ConverterProcessExecutor
from .converter_progress_parser import read_progress as _read_progress

_DEFAULT_TIMEOUT = object()


class ConverterProgressHelper:
    """Stable facade used by ConverterThread and converter services."""

    def __init__(self, worker):
        self.worker = worker
        self._executor = ConverterProcessExecutor(worker)

    def _terminate_process(self, proc, *, label: str, timeout_s: float | int | None = None) -> None:
        self._executor.terminate(proc, label=label, timeout_s=timeout_s)

    def probe_ms(self, path) -> int | None:
        return _probe_ms(self.worker, path)

    def probe_frames(self, path) -> int | None:
        return _probe_frames(self.worker, path)

    def read_prog(self, proc, path, dur_ms: int | None, total_frames: int | None = None, on_activity=None) -> None:
        _read_progress(self.worker, proc, path, dur_ms, total_frames, on_activity)

    def run(self, cmd, *, timeout_s: int | None = None, label: str = "Subprozess") -> int:
        return self._executor.run(cmd, timeout_s=timeout_s, label=label)

    def run_capture(self, cmd, *, timeout_s: int | None = None, label: str = "Tool-Prozess") -> tuple[int, str, str]:
        return self._executor.run_capture(cmd, timeout_s=timeout_s, label=label)

    def run_p(self, cmd, path, dur_ms, *, timeout_s: int | None | object = _DEFAULT_TIMEOUT, label: str = "FFmpeg-Encode") -> int:
        effective_timeout = get_timeout("encoder_general") if timeout_s is _DEFAULT_TIMEOUT else timeout_s
        return self._executor.run_progress(
            cmd, path, dur_ms,
            timeout_s=effective_timeout,
            label=label,
            probe_frames=self.probe_frames,
            read_progress=self.read_prog,
        )
