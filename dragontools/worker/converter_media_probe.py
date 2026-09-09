# -*- coding: utf-8 -*-
"""ffprobe based duration/frame probing for converter workers."""
from __future__ import annotations

import json
import subprocess
import traceback
from pathlib import Path

from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs


def probe_ms(worker, path) -> int | None:
    try:
        result = subprocess.run(
            [worker.tools.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, **_no_window_kwargs(), timeout=30,
        )
        data = json.loads(result.stdout or "{}")
        duration = 0.0
        try:
            duration = max(duration, float(data.get("format", {}).get("duration", 0.0)))
        except Exception as exc:
            worker.log(f"⚠️ ffprobe-Formatdauer konnte nicht gelesen werden: {exc}", "warn")
            worker.log(traceback.format_exc(), "error")
        for stream in data.get("streams", []):
            try:
                duration = max(duration, float(stream.get("duration", 0.0)))
            except Exception as exc:
                worker.log(f"⚠️ ffprobe-Streamdauer konnte nicht gelesen werden: {exc}", "warn")
                worker.log(traceback.format_exc(), "error")
        return int(duration * 1000) if duration > 0.0 else None
    except Exception as exc:
        worker.log(f"⚠️ ffprobe-Daueranalyse fehlgeschlagen bei {Path(path).name}: {exc}", "warn")
        worker.log(traceback.format_exc(), "error")
        return None


def probe_frames(worker, path) -> int | None:
    try:
        result = subprocess.run(
            [worker.tools.ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=nb_frames", "-of", "default=nokey=1:noprint_wrappers=1", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, **_no_window_kwargs(), timeout=15,
        )
        nums = [int(value) for value in result.stdout.split() if value.strip().isdigit()]
        frames = max(nums) if nums else None
        return frames if frames and frames > 100 else None
    except Exception as exc:
        worker.log(f"⚠️ ffprobe-Frameanalyse fehlgeschlagen bei {Path(path).name}: {exc}", "warn")
        worker.log(traceback.format_exc(), "error")
        return None
