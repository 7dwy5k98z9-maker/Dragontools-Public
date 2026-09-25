# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core.process_runner import tool_available
from .duration_repair_models import MediaTimingInfo
from .duration_repair_stream_guard import StreamInventory


def allow_one_frame_wrap_cfr_repair(
    before: MediaTimingInfo,
    *,
    expected_duration_s: float | None,
    fallback_reason: str,
) -> bool:
    """Allow CFR reconstruction only for the narrow ±1-frame 2^32-ms-wrap case.

    Patch BA permits up to 1.0 s between container/source and frame-derived
    duration; payload preservation is still verified packet-by-packet.
    """
    if (before.frame_rate_mode or "").upper() != "VFR":
        return False
    match = re.search(r"Original=(\d+), Ausgabe=(\d+)", str(fallback_reason or ""))
    if not match or abs(int(match.group(1)) - int(match.group(2))) > 1:
        return False
    if before.frame_rate is None or before.frame_rate <= 0 or before.video_frame_count is None:
        return False
    frame_duration = 1.0 / float(before.frame_rate)
    frame_expected = float(before.video_frame_count) * frame_duration
    if expected_duration_s is None or abs(frame_expected - float(expected_duration_s)) > max(1.0, frame_duration):
        return False
    reported = (before.video_duration_s, before.container_duration_s)
    return any(value is not None and float(value) >= 1_000_000.0 for value in reported)


def timestamp_tool_availability_error(runtime, container_name: str) -> str:
    if container_name == "mp4":
        if not tool_available(runtime.mp4box_path):
            return "MP4Box wurde nicht gefunden - MP4-Timestamp-Reparatur nicht möglich."
        return ""
    if not tool_available(runtime.mkvmerge_path) and not tool_available(runtime.ffmpeg_path):
        return "Weder mkvmerge noch ffmpeg wurde gefunden - MKV-Timestamp-Reparatur nicht möglich."
    return ""


def log_reference_inventories(runtime, *inventories: StreamInventory) -> None:
    def label(inv: StreamInventory) -> str:
        if not inv.available:
            return f"{inv.source}=nicht verfügbar"
        return f"{inv.source}: V={inv.video}, A={inv.audio}, S={inv.subtitle}"

    runtime.log("   Stream-Referenz: " + " | ".join(label(inv) for inv in inventories), "info")


def mkv_video_track_id(runtime, path: Path) -> int:
    """Resolve the Matroska track ID; never assume ffprobe stream index 0."""
    run = runtime.run_tool(
        [runtime.mkvmerge_path, "-J", str(path)],
        label="MKVToolNix-Videotrack-ID",
    )
    if run.returncode != 0:
        raise RuntimeError((run.stderr or run.stdout or "mkvmerge -J fehlgeschlagen.").strip())
    payload = json.loads(run.stdout or "{}")
    video_tracks = [track for track in (payload.get("tracks") or []) if track.get("type") == "video"]
    if len(video_tracks) != 1:
        raise ValueError(f"erwartet genau 1 Videotrack, gefunden {len(video_tracks)}")
    return int(video_tracks[0]["id"])
