# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dv_runtime_models import DVEncoderConfig
from .dv_video_filters import (
    build_dv5_libplacebo_vf,
    inject_dv_colorspace,
    remap_vf_to_input1,
)
from .encoder_args import _vid_args


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
    p8_hevc: Path,
    output_hevc: Path,
    vf_args: list,
    profile_major: int | None,
) -> DVEncodeCommand:
    """Erzeugt den Encode-Befehl ohne Seiteneffekte.

    Sonderfälle sind absichtlich explizit:

    * DV Profile 5 wird direkt aus dem Originalcontainer decodiert. Die
      ICtCp-Basis wird über libplacebo nach HDR10/BT.2020nc/PQ konvertiert.
      Der alte P5-Remux-Pfad ist hier bewusst NICHT erreichbar.
    * DV Profile 7/8 (und unbekannte DV-Profile nach vorheriger dovi_tool-
      Normalisierung) encodieren aus ``p8_hevc``. Nur Audio/Subtitel-Metadaten
      stammen weiterhin aus dem Originalcontainer.
    """
    if profile_major == 5:
        command = (
            [
                ffmpeg_path, "-y", "-nostdin",
                "-loglevel", "error",
                "-i", input_path,
            ]
            + build_dv5_libplacebo_vf(vf_args)
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
            uses_libplacebo=True,
            video_source=input_path,
        )

    processed_vf = inject_dv_colorspace(
        remap_vf_to_input1(vf_args),
        is_p5=False,
    )
    has_filter_complex = "-filter_complex" in processed_vf
    command = (
        [
            ffmpeg_path, "-y", "-nostdin",
            "-loglevel", "error",
            "-i", input_path,
            "-f", "hevc", "-i", str(p8_hevc),
            *([] if has_filter_complex else ["-map", "1:v:0"]),
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
        uses_libplacebo=False,
        video_source=str(p8_hevc),
    )
