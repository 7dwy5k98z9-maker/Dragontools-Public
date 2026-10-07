from __future__ import annotations

from .media_analyzer_io import _run_ffprobe_dynamic_hdr_frames
from .media_hdr_detection import detect_hdr10plus_from_ffprobe_frames
from .media_metadata import normalize_video_codec
from .models import VideoStream
from .tool_paths import ToolPaths


def needs_hdr10plus_frame_probe(video_streams: list[VideoStream]) -> bool:
    if not video_streams:
        return False
    primary = video_streams[0]
    # Only the stream actually converted/remuxed by the pipeline may suppress
    # the fallback. HDR10+ on a secondary video track is irrelevant to v:0.
    if primary.has_hdr10plus or primary.hdr_format == "hdr10plus":
        return False
    if normalize_video_codec(primary.codec) not in {"hevc", "av1"}:
        return False
    transfer = str(primary.color_transfer or "").lower()
    return bool(
        primary.hdr_format in {"hdr10", "dolby_vision"}
        or transfer in {"pq", "smpte2084"}
        or "2084" in transfer
    )


def apply_hdr10plus_frame_fallback(
    path: str,
    tools: ToolPaths,
    video_streams: list[VideoStream],
    warnings: list[str],
    *, run_process=None,
) -> bool:
    """Supplement stream metadata with a short frame-level ST-2094-40 probe."""
    if not needs_hdr10plus_frame_probe(video_streams):
        return False

    primary = video_streams[0]
    if primary.index < 0:
        warnings.append(
            "[HDR10+-Erkennung] Frame-Fallback übersprungen: kein verlässlicher "
            "ffprobe-Streamindex für die primäre Videospur."
        )
        return False

    payload, probe_warnings = _run_ffprobe_dynamic_hdr_frames(
        path,
        tools,
        stream_index=primary.index,
        **({"run_process": run_process} if run_process is not None else {}),
    )
    warnings.extend(probe_warnings)
    if not detect_hdr10plus_from_ffprobe_frames(payload):
        return False

    primary.has_hdr10plus = True
    if primary.hdr_format != "dolby_vision":
        primary.hdr_format = "hdr10plus"
    warnings.append(
        "[HDR10+-Erkennung] SMPTE ST 2094-40 wurde per kurzem ffprobe-Frame-Fallback erkannt."
    )
    return True


__all__ = ["apply_hdr10plus_frame_fallback", "needs_hdr10plus_frame_probe"]
