# -*- coding: utf-8 -*-
"""Compatibility facade for the refactored Dolby Vision remux components.

New code lives in focused modules.  The historic imports remain stable because
existing tests and third-party extensions import these names from this module.
"""
from __future__ import annotations

from ..core.audio_titles import build_audio_title
from ..core.output_replace import commit_staged_output
from ..rules.audio_plan import audio_filter_chain, compute_audio_track_plan
from .dv_remux_output import DVOutputManager
from .dv_remux_pipeline import DVRemuxPipelineRunner
from .dv_remux_process import DVRemuxProcessRunner
from .dv_subtitle_mux_service import dv_subtitle_storage as dv_remux_subtitle_storage


class DVMP4BoxPipelineRunner(DVRemuxPipelineRunner):
    """Backward-compatible name for the MP4/MKV DV remux pipeline.

    Dependencies are resolved at construction time so monkeypatching the legacy
    module globals keeps working for tests and extensions.
    """

    def __init__(self, worker, process_runner: DVRemuxProcessRunner):
        super().__init__(
            worker,
            process_runner,
            audio_plan_builder=lambda **kwargs: compute_audio_track_plan(**kwargs),
            audio_title_builder=lambda **kwargs: build_audio_title(**kwargs),
            audio_filter_builder=lambda decision: audio_filter_chain(decision),
        )


__all__ = [
    "DVMP4BoxPipelineRunner",
    "DVOutputManager",
    "DVRemuxProcessRunner",
    "audio_filter_chain",
    "build_audio_title",
    "compute_audio_track_plan",
    "commit_staged_output",
    "dv_remux_subtitle_storage",
]
