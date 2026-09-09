# -*- coding: utf-8 -*-
"""Parser for ffmpeg ``-progress`` output and ETA calculation."""
from __future__ import annotations

import time


def _parse_out_time(value: str) -> int | None:
    try:
        hours, minutes, seconds = value.strip().split(":")
        return int((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)
    except Exception:
        return None


def _parse_speed(value: str) -> float | None:
    try:
        parsed = float((value or "").strip().lower().rstrip("x"))
        return parsed if parsed > 0 else None
    except Exception:
        return None


def read_progress(worker, proc, path, dur_ms: int | None, total_frames: int | None = None, on_activity=None) -> None:
    last_pct = 0
    last_out_ms = 0
    last_speed = None
    start_ts = time.time()

    for raw in proc.stdout:
        worker.wait_if_paused()
        if proc.poll() is not None:
            break
        if worker.abort_requested and worker.abort_type == "sofort":
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
                last_out_ms = int(int(value) / 1000)
            except ValueError:
                last_out_ms = 0
            if last_out_ms and dur_ms:
                pct = int(max(0, min(100, (last_out_ms / dur_ms) * 100)))
        elif key == "out_time":
            out_time = _parse_out_time(value)
            if out_time is not None:
                last_out_ms = out_time
            if out_time and dur_ms:
                pct = int(max(0, min(100, (out_time / dur_ms) * 100)))
        elif key == "frame" and total_frames:
            try:
                pct = int(max(0, min(100, int(value) / total_frames * 100)))
            except ValueError:
                pass
        elif key == "progress" and value == "end":
            worker.emit_file_progress(path, 100, 0.0)
            break

        elapsed_s = max(0.001, time.time() - start_ts)
        if dur_ms and last_out_ms > 0:
            remaining_media_s = max(0.0, (dur_ms - last_out_ms) / 1000.0)
            if last_speed and last_speed > 0:
                eta_s = remaining_media_s / last_speed
            else:
                processed_s = max(0.001, last_out_ms / 1000.0)
                derived_speed = processed_s / elapsed_s
                if derived_speed > 0:
                    eta_s = remaining_media_s / derived_speed

        if eta_s is not None and elapsed_s >= 15 and last_out_ms >= 30_000:
            denom = elapsed_s + max(0.0, eta_s)
            if denom > 0:
                pct = int(max(0, min(99, (elapsed_s / denom) * 100)))
        if pct is not None:
            pct = max(last_pct, min(99, pct))
            last_pct = pct
            worker.emit_file_progress(path, pct, eta_s)
