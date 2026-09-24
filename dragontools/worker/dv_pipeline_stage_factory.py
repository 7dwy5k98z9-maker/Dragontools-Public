# -*- coding: utf-8 -*-
"""Factory for the service-bound Dolby-Vision stage coordinator."""
from __future__ import annotations

from typing import Any, Callable

from .dv_pipeline_stages import DVPipelineStages


def build_pipeline_stages(
    *,
    tools: Any,
    encoder_config,
    progress_runner,
    temp_state,
    audio_mux_service,
    mp4box_muxer,
    mkv_muxer,
    rpu_service,
    hdr10plus_service,
    generator_client,
    level5_editor,
    subtitle_service,
    subtitle_mux_service,
    subtitle_rules: dict,
    failure_recovery,
    log: Callable,
    verbose_log: Callable,
    assert_nonempty_file: Callable,
    clear_burn_sub_tmp: Callable,
    crop_decision: Callable | None,
) -> DVPipelineStages:
    return DVPipelineStages(
        tools=tools,
        encoder_config=encoder_config,
        progress_runner=progress_runner,
        temp_state=temp_state,
        audio_mux_service=audio_mux_service,
        mp4box_muxer=mp4box_muxer,
        mkv_muxer=mkv_muxer,
        rpu_service=rpu_service,
        hdr10plus_service=hdr10plus_service,
        generator_client=generator_client,
        level5_editor=level5_editor,
        subtitle_service=subtitle_service,
        subtitle_mux_service=subtitle_mux_service,
        subtitle_rules=subtitle_rules,
        failure_recovery=failure_recovery,
        log=log,
        verbose_log=verbose_log,
        assert_nonempty_file=assert_nonempty_file,
        clear_burn_sub_tmp=clear_burn_sub_tmp,
        crop_decision=crop_decision,
    )


__all__ = ["build_pipeline_stages"]
