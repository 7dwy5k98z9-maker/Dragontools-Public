# -*- coding: utf-8 -*-
"""Parser for ffmpeg ``-progress`` output and ETA calculation."""
from __future__ import annotations

import time
from math import isfinite
from .converter_progress_eta import estimate_eta, progress_percent, progress_from_eta


def _parse_out_time(value: str) -> int | None:
    try:
        hours, minutes, seconds = value.strip().split(":")
        return int((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)
    except Exception:
        return None


def _parse_speed(value: str) -> float | None:
    try:
        parsed = float((value or "").strip().lower().rstrip("x"))
        return parsed if isfinite(parsed) and parsed > 0 else None
    except Exception:
        return None


def _record_output_frame_count(worker, path, value: str) -> int | None:
    try:
        frame_count = int(value)
    except (TypeError, ValueError):
        return None
    if frame_count <= 0:
        return None
    counts = getattr(worker, "_progress_frame_counts", None)
    if not isinstance(counts, dict):
        counts = {}
        setattr(worker, "_progress_frame_counts", counts)
    counts[str(path)] = frame_count
    return frame_count


def _mark_progress_end(worker, path) -> None:
    completed = getattr(worker, "_progress_end_seen", None)
    if not isinstance(completed, dict):
        completed = {}
        setattr(worker, "_progress_end_seen", completed)
    completed[str(path)] = True


def read_progress(worker, proc, path, dur_ms: int | None, total_frames: int | None = None, on_activity=None) -> None:
    last_pct = 0
    last_out_ms = 0
    last_speed = None
    start_ts = time.time()

    for raw in proc.stdout:
        worker.wait_if_paused()
        control = getattr(worker, "_control_state", None)
        abort_requested = control.abort_requested if control is not None else getattr(worker, "abort_requested", False)
        abort_type = control.abort_type if control is not None else getattr(worker, "abort_type", None)
        if abort_requested and abort_type == "sofort":
            break
        if on_activity:
            on_activity()
        line = raw.strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        pct = None
        eta_s = None

        if key == "speed":
            last_speed = _parse_speed(value)
            continue
        if key == "out_time_ms":
            try:
                last_out_ms = int(value) // 1000
            except ValueError:
                last_out_ms = 0
            if last_out_ms and dur_ms:
                pct = progress_percent(last_out_ms, dur_ms)
        elif key == "out_time":
            out_time = _parse_out_time(value)
            if out_time is not None:
                last_out_ms = out_time
            if out_time and dur_ms:
                pct = progress_percent(out_time, dur_ms)
        elif key == "frame":
            frame_count = _record_output_frame_count(worker, path, value)
            if frame_count is not None and total_frames:
                pct = progress_percent(frame_count, total_frames)
        elif key == "progress" and value == "end":
            _mark_progress_end(worker, path)
            worker.emit_file_progress(path, 100, 0.0)
            break

        elapsed_s = max(0.001, time.time() - start_ts)
        eta_s = estimate_eta(dur_ms, last_out_ms, last_speed, elapsed_s)
        pct = progress_from_eta(pct, eta_s=eta_s, elapsed_s=elapsed_s, output_ms=last_out_ms)
        if pct is not None:
            pct = max(last_pct, min(99, pct))
            last_pct = pct
            worker.emit_file_progress(path, pct, eta_s)
