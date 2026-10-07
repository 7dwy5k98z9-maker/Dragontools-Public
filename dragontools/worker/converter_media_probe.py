# -*- coding: utf-8 -*-
"""ffprobe based duration/frame probing for converter workers."""
from __future__ import annotations

import json
import subprocess
import traceback
from pathlib import Path

from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from ..core.media_duration import source_duration


def _tools(worker):
    services = getattr(worker, "_services", None)
    tools = getattr(services, "tools", None) if services is not None else None
    return tools if tools is not None else getattr(worker, "tools")


def probe_ms(worker, path) -> int | None:
    try:
        result = subprocess.run(
            [_tools(worker).ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, **_no_window_kwargs(), timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "ffprobe fehlgeschlagen")
        duration = source_duration(json.loads(result.stdout or "{}"))
        return int(duration * 1000) if duration is not None else None
    except Exception as exc:
        worker.log(f"⚠️ ffprobe-Daueranalyse fehlgeschlagen bei {Path(path).name}: {exc}", "warn")
        worker.log(traceback.format_exc(), "error")
        return None


def probe_frames(worker, path) -> int | None:
    try:
        result = subprocess.run(
            [_tools(worker).ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=nb_frames", "-of", "default=nokey=1:noprint_wrappers=1", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, **_no_window_kwargs(), timeout=15,
        )
        if getattr(result, "returncode", 0) != 0:
            raise RuntimeError(result.stderr or "ffprobe fehlgeschlagen")
        nums = [int(value) for value in (result.stdout or "").split() if value.strip().isdigit()]
        frames = max(nums) if nums else None
        return frames if frames and frames > 100 else None
    except Exception as exc:
        worker.log(f"⚠️ ffprobe-Frameanalyse fehlgeschlagen bei {Path(path).name}: {exc}", "warn")
        worker.log(traceback.format_exc(), "error")
        return None
