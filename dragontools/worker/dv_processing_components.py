# -*- coding: utf-8 -*-
"""Construction of the service graph used by the Dolby-Vision pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .dv_audio_mux_service import DVAudioMuxService
from .dv_failure_recovery import DVFailureRecovery
from .dv_level5_editor import DVLevel5Editor
from .dv_mp4box_muxer import DVMP4BoxMuxer
from .dv_mkv_muxer import DVMKVMuxer
from .dv_rpu_service import DVRpuService
from .dv_subtitle_mux_service import DVSubtitleMuxService
from .hdr10plus_bitstream_service import HDR10PlusBitstreamService
from .subtitle_sidecar_service import SubtitleSidecarService


@dataclass(frozen=True)
class DVProcessingComponents:
    audio_mux_service: DVAudioMuxService
    mp4box_muxer: DVMP4BoxMuxer
    mkv_muxer: DVMKVMuxer
    rpu_service: DVRpuService
    hdr10plus_service: HDR10PlusBitstreamService
    level5_editor: DVLevel5Editor
    subtitle_service: SubtitleSidecarService
    subtitle_mux_service: DVSubtitleMuxService
    failure_recovery: DVFailureRecovery


def build_dv_processing_components(
    *,
    tools: Any,
    subtitle_rules: dict,
    log: Callable[[str, str], None],
    verbose_logger=None,
    worker=None,
) -> DVProcessingComponents:
    def detail_log(message: str, level: str = "info") -> None:
        normalized = str(level).lower()
        if normalized in {"warn", "warning", "error"}:
            log(message, "warn" if normalized == "warning" else level)
            return
        if verbose_logger is not None:
            try:
                verbose_logger.write(message)
            except (OSError, RuntimeError, ValueError, AttributeError):
                pass

    audio_mux = DVAudioMuxService(
        ffmpeg_path=tools.ffmpeg,
        ffprobe_path=tools.ffprobe,
        mp4box_muxer=None,
        log=detail_log,
    )
    mp4box_muxer = DVMP4BoxMuxer(
        mp4box_path=tools.mp4box,
        audio_track_name=lambda meta: audio_mux.audio_track_name(meta),
    )
    audio_mux._mp4box_muxer = mp4box_muxer
    return DVProcessingComponents(
        audio_mux_service=audio_mux,
        mp4box_muxer=mp4box_muxer,
        mkv_muxer=DVMKVMuxer(
            mkvmerge_path=getattr(tools, "mkvmerge", "mkvmerge"),
            audio_track_name=audio_mux.audio_track_name,
        ),
        rpu_service=DVRpuService(dovi_tool_path=tools.dovi_tool, log=detail_log),
        hdr10plus_service=HDR10PlusBitstreamService(
            hdr10plus_tool_path=tools.hdr10plus_tool,
            log=detail_log,
        ),
        level5_editor=DVLevel5Editor(dovi_tool_path=tools.dovi_tool, log=detail_log),
        subtitle_service=SubtitleSidecarService(
            ffmpeg_path=tools.ffmpeg,
            subtitle_rules=subtitle_rules,
            log=log,
            worker=worker,
        ),
        subtitle_mux_service=DVSubtitleMuxService(
            ffmpeg_path=tools.ffmpeg,
            subtitle_rules=subtitle_rules,
            log=log,
        ),
        failure_recovery=DVFailureRecovery(log=log),
    )


__all__ = ["DVProcessingComponents", "build_dv_processing_components"]
