# -*- coding: utf-8 -*-
"""FFmpeg command construction and fail-closed output verification for AV matching."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.audio_video_matcher import AudioSyncPlan
from ..core.media_analyzer import analyze_media


def build_audio_command(
    tools: Any,
    source_path: str,
    plan: AudioSyncPlan,
    temp_audio: Path,
) -> list[str]:
    base = [
        str(tools.ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source_path,
    ]
    if plan.filter_kind == "filter_complex":
        return [
            *base,
            "-filter_complex",
            plan.filter_graph,
            "-map",
            "[aout]",
            "-vn",
            "-sn",
            "-dn",
            "-c:a",
            plan.target_codec,
            "-b:a",
            plan.target_bitrate,
            str(temp_audio),
        ]
    return [
        *base,
        "-map",
        f"0:{plan.audio_stream_index}",
        "-vn",
        "-sn",
        "-dn",
        "-af",
        plan.filter_graph,
        "-c:a",
        plan.target_codec,
        "-b:a",
        plan.target_bitrate,
        str(temp_audio),
    ]


def build_mux_command(
    tools: Any,
    target_path: str,
    temp_audio: Path,
    temp_output: Path,
) -> list[str]:
    return [
        str(tools.ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        target_path,
        "-i",
        str(temp_audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        "-map",
        "0:t?",
        "-map",
        "0:d?",
        "-c",
        "copy",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-metadata:s:a:0",
        "language=deu",
        "-disposition:a:0",
        "default",
        str(temp_output),
    ]


def validate_output(
    output: str | Path,
    tools: Any,
    *,
    target_duration_s: float | int | None,
    tolerance_s: float = 2.0,
) -> float:
    """Validate a generated AV-match output and return its measured duration.

    Validation is deliberately fail-closed.  If MediaInfo/ffprobe cannot inspect
    the output, the temporary file must not be committed as the final result.
    """
    path = Path(output)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("Ausgabedatei fehlt oder ist leer.")
    try:
        info = analyze_media(str(path), tools)
    except Exception as exc:
        raise RuntimeError(f"Ausgabe konnte nicht validiert werden: {exc}") from exc

    try:
        output_duration = float(info.duration_s or 0.0)
        target_duration = float(target_duration_s or 0.0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ausgabedauer konnte nicht zuverlässig bestimmt werden.") from exc

    if output_duration <= 0:
        raise RuntimeError("Ausgabedauer konnte nicht zuverlässig bestimmt werden.")
    if target_duration > 0 and abs(output_duration - target_duration) > float(tolerance_s):
        raise RuntimeError(
            f"Ausgabedauer unplausibel: Ziel {target_duration:.1f}s, "
            f"Ausgabe {output_duration:.1f}s"
        )
    return output_duration


__all__ = ["build_audio_command", "build_mux_command", "validate_output"]
