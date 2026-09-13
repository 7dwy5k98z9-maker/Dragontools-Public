# -*- coding: utf-8 -*-
from __future__ import annotations

from fractions import Fraction
from pathlib import Path


def build_timestamp_repair_command(
    source: Path,
    target: Path,
    fps: Fraction,
    *,
    container: str | None,
    mp4box_path: str,
    ffmpeg_path: str,
) -> list[str]:
    """Build the lossless timestamp-repair command for MKV or MP4."""
    container_name = str(container or source.suffix.lstrip(".")).strip().lower().lstrip(".")
    if container_name == "mp4":
        # MP4Box forces the CFR rate while rebuilding MP4 sample timestamps.
        # The HEVC bitstream remains untouched, including DV-RPU/HDR10+ SEI.
        fps_value = f"{fps.numerator}/{fps.denominator}"
        return [
            mp4box_path,
            "-new",
            str(target),
            "-add",
            f"{source}:fps={fps_value}",
        ]

    bsf = setts_filter_for_fps(fps)
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
        "-bsf:v:0",
        bsf,
        "-copy_unknown",
        str(target),
    ]


def build_genpts_repair_command(
    source: Path,
    target: Path,
    *,
    ffmpeg_path: str,
) -> list[str]:
    """Lossless MKV fallback: rebuild presentation timestamps without CFR forcing."""
    return [
        ffmpeg_path,
        "-hide_banner",
        "-y",
        "-fflags",
        "+genpts+igndts",
        "-i",
        str(source),
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-copy_unknown",
        str(target),
    ]


def setts_filter_for_fps(fps: Fraction) -> str:
    num = int(fps.numerator)
    den = int(fps.denominator)
    frame_ticks = f"{den}/{num}/TB" if den != 1 else f"1/{num}/TB"
    return f"setts=pts=N*{frame_ticks}:dts=N*{frame_ticks}:duration={frame_ticks}"


def command_arg_after(command: list[str], option: str) -> str:
    try:
        return str(command[command.index(option) + 1])
    except (ValueError, IndexError):
        return "-"


# Compatibility names historically imported from duration_repair_service.
_setts_filter_for_fps = setts_filter_for_fps
_command_arg_after = command_arg_after
