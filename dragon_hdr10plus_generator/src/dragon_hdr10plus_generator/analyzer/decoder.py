from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VideoProbe:
    transfer: str
    primaries: str
    pixel_format: str
    bit_depth: int | None
    frames: int | None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str = ""
    profile: str = ""
    color_space: str = ""
    color_range: str = ""
    duration_s: float | None = None
    frame_count_source: str = "unknown"
    frame_count_reliability: str = "unknown"


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value)) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _float_rate(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return None
    try:
        return float(Fraction(text))
    except (ValueError, ZeroDivisionError):
        return None


class ProbeToolNotFoundError(FileNotFoundError):
    """ffprobe executable is missing while the media input itself exists."""


class ProbeTimeoutError(RuntimeError):
    """ffprobe did not complete within the configured deadline."""


def probe_video(
    path: str | Path,
    *,
    ffprobe: str = "ffprobe",
    timeout_s: int | float | None = 30,
) -> VideoProbe:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,profile,width,height,color_transfer,color_primaries,color_space,color_range,pix_fmt,bits_per_raw_sample,nb_frames,avg_frame_rate,r_frame_rate:format=duration",
        "-of", "json", str(source),
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=None if timeout_s is None else max(0.1, float(timeout_s)),
        )
    except FileNotFoundError as exc:
        raise ProbeToolNotFoundError(ffprobe) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeTimeoutError(
            f"ffprobe timeout after {timeout_s}s for {source}"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"ffprobe rc={completed.returncode}")
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError("NO_VIDEO_STREAM")
    stream = streams[0]
    raw_depth = _int_or_none(stream.get("bits_per_raw_sample"))
    fps = _float_rate(stream.get("avg_frame_rate")) or _float_rate(stream.get("r_frame_rate"))
    duration_s = None
    try:
        raw_duration = (payload.get("format") or {}).get("duration")
        if raw_duration not in (None, "", "N/A"):
            duration_s = float(raw_duration)
    except (TypeError, ValueError):
        duration_s = None
    frames = _int_or_none(stream.get("nb_frames"))
    frame_count_source = "stream_nb_frames" if frames is not None and frames > 0 else "unknown"
    frame_count_reliability = "reported" if frames is not None and frames > 0 else "unknown"
    if frames is None and duration_s is not None and duration_s > 0 and fps is not None and fps > 0:
        frames = max(1, int(round(duration_s * fps)))
        frame_count_source = "duration_x_fps"
        frame_count_reliability = "estimated"
    return VideoProbe(
        transfer=str(stream.get("color_transfer") or ""),
        primaries=str(stream.get("color_primaries") or ""),
        pixel_format=str(stream.get("pix_fmt") or ""),
        bit_depth=raw_depth,
        frames=frames,
        width=_int_or_none(stream.get("width")),
        height=_int_or_none(stream.get("height")),
        fps=fps,
        codec=str(stream.get("codec_name") or ""),
        profile=str(stream.get("profile") or ""),
        color_space=str(stream.get("color_space") or ""),
        color_range=str(stream.get("color_range") or ""),
        duration_s=duration_s,
        frame_count_source=frame_count_source,
        frame_count_reliability=frame_count_reliability,
    )


__all__ = ["ProbeTimeoutError", "ProbeToolNotFoundError", "VideoProbe", "probe_video"]
