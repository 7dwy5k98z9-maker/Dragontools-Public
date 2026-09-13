# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .dv_runtime_models import DVTempState
from .dv_subtitle_mux_service import DVSubtitleMuxService
from .hdr10plus_bitstream_service import HDR10PlusBitstreamService
from .hdrplus_encode_service import HDRPlusEncodeService
from .hdrplus_mux_service import HDRPlusMuxService
from .hdrplus_pipeline_coordinator import HDRPlusPipelineCoordinator
from .hdrplus_stream_service import HDRPlusStreamService
from .hdrplus_tool_runner import HDRPlusToolRunner
from .subtitle_sidecar_service import SubtitleSidecarService


@dataclass(frozen=True)
class HDRPlusHelperServices:
    """Langlebige Services einer ``HDRPlusConversionHelper``-Instanz."""

    subtitle_service: SubtitleSidecarService
    subtitle_mux_service: DVSubtitleMuxService
    hdr10plus_service: HDR10PlusBitstreamService
    tool_runner: HDRPlusToolRunner
    mux_service: HDRPlusMuxService
    encode_service: HDRPlusEncodeService
    stream_service: HDRPlusStreamService
    pipeline: HDRPlusPipelineCoordinator


def build_hdrplus_helper_services(
    *,
    tools,
    log: Callable[[str, str], None],
    progress_runner,
    temp_state: DVTempState,
    subtitle_rules: dict,
    run_tool_fn: Callable,
    log_tool_failure_fn: Callable,
    run_mux_tool: Callable[..., bool],
) -> HDRPlusHelperServices:
    """Verdrahtet die HDR10+-Services an genau einer Stelle.

    Die Callbacks werden injiziert, damit ``hdrplus_conversion`` seine bisherige
    Monkeypatch-/Kompatibilitätsgrenze für Tool-Aufrufe behält.
    """

    worker = getattr(progress_runner, "worker", None)
    rules = dict(subtitle_rules or {})
    subtitle_service = SubtitleSidecarService(
        ffmpeg_path=tools.ffmpeg,
        subtitle_rules=rules,
        log=log,
        worker=worker,
    )
    subtitle_mux_service = DVSubtitleMuxService(
        ffmpeg_path=tools.ffmpeg,
        subtitle_rules=rules,
        log=log,
    )
    hdr10plus_service = HDR10PlusBitstreamService(
        hdr10plus_tool_path=tools.hdr10plus_tool,
        log=log,
    )
    tool_runner = HDRPlusToolRunner(
        run_tool_fn=run_tool_fn,
        log_tool_failure_fn=log_tool_failure_fn,
        log=log,
        temp_state=temp_state,
        worker=worker,
    )
    mux_service = HDRPlusMuxService(
        tools=tools,
        log=log,
        run_mux_tool=run_mux_tool,
        capture_tool=tool_runner.capture,
    )
    encode_service = HDRPlusEncodeService(
        ffmpeg_path=tools.ffmpeg,
        progress_runner=progress_runner,
        temp_state=temp_state,
        log=log,
    )
    stream_service = HDRPlusStreamService(ffmpeg_path=tools.ffmpeg, log=log)
    pipeline = HDRPlusPipelineCoordinator(
        encode_service=encode_service,
        subtitle_service=subtitle_service,
        subtitle_mux_service=subtitle_mux_service,
        subtitle_rules=rules,
        log=log,
    )
    return HDRPlusHelperServices(
        subtitle_service=subtitle_service,
        subtitle_mux_service=subtitle_mux_service,
        hdr10plus_service=hdr10plus_service,
        tool_runner=tool_runner,
        mux_service=mux_service,
        encode_service=encode_service,
        stream_service=stream_service,
        pipeline=pipeline,
    )
