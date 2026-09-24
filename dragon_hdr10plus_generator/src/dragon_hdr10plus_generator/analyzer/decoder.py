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
    color_space: str = ""
    color_range: str = ""


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


def probe_video(path: str | Path, *, ffprobe: str = "ffprobe") -> VideoProbe:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-count_frames", "-show_entries",
        "stream=codec_name,width,height,color_transfer,color_primaries,color_space,color_range,pix_fmt,bits_per_raw_sample,nb_read_frames,nb_frames,avg_frame_rate,r_frame_rate",
        "-of", "json", str(source),
    ]
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"ffprobe rc={completed.returncode}")
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError("NO_VIDEO_STREAM")
    stream = streams[0]
    raw_depth = _int_or_none(stream.get("bits_per_raw_sample"))
    frames = _int_or_none(stream.get("nb_read_frames")) or _int_or_none(stream.get("nb_frames"))
    fps = _float_rate(stream.get("avg_frame_rate")) or _float_rate(stream.get("r_frame_rate"))
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
        color_space=str(stream.get("color_space") or ""),
        color_range=str(stream.get("color_range") or ""),
    )


__all__ = ["VideoProbe", "probe_video"]
