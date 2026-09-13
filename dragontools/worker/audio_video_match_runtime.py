# -*- coding: utf-8 -*-
"""Shared progress and external-tool lifecycle for AV matching."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .audio_video_match_contracts import AudioVideoMatchCallbacks
from .tool_runner import run_tool_bytes


class AudioVideoMatchProgress:
    def __init__(self, callbacks: AudioVideoMatchCallbacks) -> None:
        self._callbacks = callbacks
        self.value = 0

    def set(self, value: int) -> None:
        self.value = max(self.value, max(0, min(100, int(value))))
        self._callbacks.progress(self.value)

    def message(self, message: str) -> None:
        self._callbacks.log_line(f"ℹ️  {message}")
        if "Metadaten" in message:
            self.set(5)
        elif "Landmarke" in message:
            self.set(min(75, self.value + 7))
        elif "Zeitmodell" in message:
            self.set(82)
        elif "Schnittbereich" in message:
            self.set(min(85, self.value + 10))


class AudioVideoMatchToolIO:
    def __init__(
        self,
        *,
        callbacks: AudioVideoMatchCallbacks,
        process_worker: Any = None,
        is_aborted: Callable[[], bool] | None = None,
    ) -> None:
        self._callbacks = callbacks
        self.process_worker = process_worker
        self._is_aborted = is_aborted or (lambda: False)

    def run_binary_stdout(self, cmd: list[str], timeout_s: int | float | None) -> bytes:
        if self._is_aborted():
            raise RuntimeError("Abgebrochen")
        result = run_tool_bytes(
            cmd,
            label=Path(cmd[0]).name if cmd else "Matcher-Tool",
            timeout_s=timeout_s,
            worker=self.process_worker,
            log=self.log,
        )
        if result.aborted or self._is_aborted():
            raise RuntimeError("Abgebrochen")
        if result.timed_out:
            raise RuntimeError(f"{Path(cmd[0]).name}: Timeout")
        if not result.ok:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(detail or f"{Path(cmd[0]).name} fehlgeschlagen")
        return result.stdout or b""

    def log(self, message: str, severity: str = "info") -> None:
        prefix = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}.get(severity, "ℹ️")
        self._callbacks.log_line(f"{prefix} {message}")


__all__ = ["AudioVideoMatchProgress", "AudioVideoMatchToolIO"]
