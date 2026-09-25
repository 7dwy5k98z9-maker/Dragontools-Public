# -*- coding: utf-8 -*-
"""External tool readers for duration/timing analysis."""
from __future__ import annotations

import json
import subprocess
from typing import Callable

from ..core.process_runner import subprocess_no_window_kwargs as no_window_kwargs


class TimingSourceReader:
    def __init__(self, *, ffprobe_path: str, mediainfo_path: str = "", run_command: Callable | None = None, creationflags: int | None = None) -> None:
        self.ffprobe_path = str(ffprobe_path or "")
        self.mediainfo_path = str(mediainfo_path or "")
        self.run_command = run_command or subprocess.run
        self.subprocess_kwargs = no_window_kwargs()
        if creationflags is not None:
            self.subprocess_kwargs["creationflags"] = int(creationflags)

    def run_ffprobe_json(self, path: str, *, count_frames: bool = False) -> dict:
        cmd = [self.ffprobe_path, "-v", "error"]
        if count_frames:
            cmd.append("-count_frames")
        cmd.extend(["-show_format", "-show_streams", "-show_chapters", "-of", "json", str(path)])
        run = self.run_command(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=(180 if count_frames else 90), **self.subprocess_kwargs)
        if run.returncode != 0:
            raise RuntimeError((run.stderr or "ffprobe fehlgeschlagen.").strip())
        return json.loads(run.stdout or "{}")

    def run_mediainfo_json(self, path: str) -> dict:
        run = self.run_command([self.mediainfo_path, "--Output=JSON", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=60, **self.subprocess_kwargs)
        if run.returncode != 0:
            raise RuntimeError((run.stderr or "MediaInfo fehlgeschlagen.").strip())
        return json.loads(run.stdout or "{}")


__all__ = ["TimingSourceReader"]
