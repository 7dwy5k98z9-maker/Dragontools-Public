# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dv_runtime_models import DVEncoderConfig
from .dv_video_filters import (
    build_dv5_libplacebo_vf,
    inject_dv_colorspace,
)
from .encoder_args import _vid_args, encoder_10bit_filter_pixel_format




from ..core.media_stream_selection import primary_ffmpeg_video_index, pin_primary_video_selector

_DV_HDR10_OUTPUT_FLAGS = [
    "-color_range", "tv",
    "-color_primaries", "bt2020",
    "-color_trc", "smpte2084",
    "-colorspace", "bt2020nc",
]


def dv_video_encode_args(encoder_config: DVEncoderConfig) -> list:
    """DV-Video-Encoding-Argumente plus HDR10-VUI ohne Pixelformat-Doppelung."""
    return _vid_args(
        encoder_config.codec,
        encoder_config.crf,
        encoder_config.preset,
        encoder_config.options,
    ) + list(_DV_HDR10_OUTPUT_FLAGS)


@dataclass(frozen=True)
class DVEncodeCommand:
    """Vollständig aufgelöster Video-Encode-Plan für eine DV-Datei."""

    command: list
    profile_major: int | None
    uses_libplacebo: bool
    video_source: str


def build_dv_encode_command(
    *,
    ffmpeg_path: str,
    encoder_config: DVEncoderConfig,
    input_path: str,
    p8_hevc: Path | None = None,
    output_hevc: Path,
    vf_args: list,
    profile_major: int | None,
    source_stream_index: int | None = None,
) -> DVEncodeCommand:
    """Build the normal DV picture encode directly from the source container.

    Dolby-Vision metadata processing is deliberately independent from picture
    decoding.  The RPU is extracted/normalized directly from Matroska before
    this step; FFmpeg therefore has no reason to decode a demuxed/rewritten
    HEVC working stream.  This removes the old ``source.hevc -> p8.hevc``
    failure surface that could lose reference pictures.

    ``p8_hevc`` remains an optional compatibility argument for callers/tests
    from older builds.  It is never used as the video source.
    """
    filter_pixel_format = encoder_10bit_filter_pixel_format(encoder_config.options)

    if profile_major == 5:
        processed_vf = build_dv5_libplacebo_vf(
            vf_args, pixel_format=filter_pixel_format, source_stream_index=source_stream_index
        )
        uses_libplacebo = True
    else:
        processed_vf = inject_dv_colorspace(
            list(vf_args),
            is_p5=False,
            pixel_format=filter_pixel_format,
            source_stream_index=source_stream_index,
        )
        uses_libplacebo = False

    processed_vf = pin_primary_video_selector(processed_vf, source_stream_index)

    command = (
        [
            ffmpeg_path, "-y", "-nostdin",
            "-loglevel", "error",
            "-i", input_path,
        ]
        + processed_vf
        + dv_video_encode_args(encoder_config)
        + ["-an", "-fps_mode", "passthrough"]
        + [
            "-progress", "pipe:1",
            "-nostats",
            "-f", "hevc",
            str(output_hevc),
        ]
    )
    return DVEncodeCommand(
        command=command,
        profile_major=profile_major,
        uses_libplacebo=uses_libplacebo,
        video_source=input_path,
    )
