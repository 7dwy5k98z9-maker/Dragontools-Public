# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.timeout_settings import get_timeout
from .tool_runner import ToolRunResult

LogFn = Callable[[str, str], None]
RunToolFn = Callable[..., ToolRunResult]
ReplaceFn = Callable[[str, str], None]


@dataclass(slots=True)
class DurationRepairRuntime:
    """Runtime dependencies shared by the duration-repair stages.

    The object deliberately contains only externally supplied dependencies and
    tool paths. Stateful repair decisions remain owned by the specialised
    services.
    """

    mkvmerge_path: str
    mp4box_path: str
    ffmpeg_path: str
    ffprobe_path: str
    mediainfo_path: str
    output_verifier: object
    log: LogFn
    worker: object | None
    run_tool_fn: RunToolFn
    replace_fn: ReplaceFn = os.replace

    def run_tool(self, cmd: list[str], *, label: str) -> ToolRunResult:
        return self.run_tool_fn(
            cmd,
            label=label,
            timeout_s=get_timeout("duration_repair"),
            worker=self.worker,
            log=self.log,
        )

    def replace_file(self, source: Path, destination: Path) -> None:
        self.replace_fn(str(source), str(destination))

    def safe_unlink(self, path: Path) -> None:
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError as exc:
            self.log(
                f"⚠️ Temporäre Reparaturdatei konnte nicht entfernt werden: {path.name} – {exc}",
                "warn",
            )
