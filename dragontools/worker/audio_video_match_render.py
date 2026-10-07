# -*- coding: utf-8 -*-
"""FFmpeg command construction and fail-closed output verification for AV matching."""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from ..core.audio_video_matcher import AudioSyncPlan
from ..core.lang_codes import mkv_language_tags
from ..core.media_analyzer import analyze_media
from ..core.output_timestamps import build_output_timestamp_args
from ..core.process_runner import subprocess_no_window_kwargs
from .output_probe import probe_output
from .owned_probe import owned_probe_runner
from .utility_media_analysis import analyze_owned_media
from .quality_output_validation import finite_duration, require_av_streams
from .audio_video_output_contract import require_preserved_target


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
    *,
    plan: AudioSyncPlan | None = None,
) -> list[str]:
    language = "deu"
    if plan is not None:
        language = mkv_language_tags(plan.target_language)[0] if plan.target_language else "und"
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
        "0:V:0",
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
        f"language={language}",
        "-disposition:a",
        "-default",
        "-disposition:a:0",
        "default",
        *build_output_timestamp_args(temp_output),
        str(temp_output),
    ]


def validate_output(
    output: str | Path,
    tools: Any,
    *,
    target_duration_s: float | int | None,
    tolerance_s: float = 2.0,
    process_worker=None,
    plan: AudioSyncPlan | None = None,
    target_path: str | None = None,
    audio_channels: int | None = None,
) -> float:
    """Validate a generated AV-match output and return its measured duration.

    Validation is deliberately fail-closed.  If MediaInfo/ffprobe cannot inspect
    the output, the temporary file must not be committed as the final result.
    """
    path = Path(output)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("Ausgabedatei fehlt oder ist leer.")
    try:
        output_media = analyze_owned_media(str(path), tools, worker=process_worker, analyzer=analyze_media)
        # Source-reference selection deliberately ignores long auxiliary tracks.
        # Validation must still inspect the real output container, including wraps.
        info = probe_output(path, ffprobe_path=str(tools.ffprobe), run_process=owned_probe_runner(process_worker),
                            no_window_kwargs=subprocess_no_window_kwargs())
    except Exception as exc:
        raise RuntimeError(f"Ausgabe konnte nicht validiert werden: {exc}") from exc

    try:
        output_duration = finite_duration(info.duration_s)
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
    require_av_streams(info)
    if plan is not None and target_path:
        target = probe_output(Path(target_path), ffprobe_path=str(tools.ffprobe),
                              run_process=owned_probe_runner(process_worker), no_window_kwargs=subprocess_no_window_kwargs())
        if not target.video_streams:
            raise RuntimeError("Zielvideo enthält keine lesbare Videospur.")
        target_media = analyze_owned_media(target_path, tools, worker=process_worker, analyzer=analyze_media)
        require_preserved_target(info, target, plan, audio_channels, output_media=output_media, target_media=target_media)
    return output_duration


__all__ = ["build_audio_command", "build_mux_command", "validate_output"]
