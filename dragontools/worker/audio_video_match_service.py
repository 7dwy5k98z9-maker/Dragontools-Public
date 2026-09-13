# -*- coding: utf-8 -*-
"""Operation dispatcher for Qt-independent audio/video matching services."""
from __future__ import annotations

from typing import Any, Callable

from .audio_video_match_analysis_service import AudioVideoMatchAnalysisService
from .audio_video_match_contracts import AudioVideoMatchCallbacks, AudioVideoMatchRequest
from .audio_video_match_create_service import AudioVideoMatchCreateService
from .audio_video_match_runtime import AudioVideoMatchProgress, AudioVideoMatchToolIO


class AudioVideoMatchService:
    def __init__(
        self,
        *,
        tools: Any,
        callbacks: AudioVideoMatchCallbacks,
        process_worker: Any = None,
        is_aborted: Callable[[], bool] | None = None,
    ) -> None:
        progress = AudioVideoMatchProgress(callbacks)
        tool_io = AudioVideoMatchToolIO(
            callbacks=callbacks,
            process_worker=process_worker,
            is_aborted=is_aborted,
        )
        self._analysis = AudioVideoMatchAnalysisService(
            tools=tools,
            callbacks=callbacks,
            progress=progress,
            tool_io=tool_io,
        )
        self._create = AudioVideoMatchCreateService(
            tools=tools,
            callbacks=callbacks,
            progress=progress,
            tool_io=tool_io,
        )

    def execute(self, request: AudioVideoMatchRequest) -> None:
        if request.operation == "analyze":
            self._analysis.analyze(request)
            return
        if request.operation == "refine":
            self._analysis.refine(request)
            return
        if request.operation == "create":
            self._create.create(request)
            return
        raise ValueError(f"Unbekannte Operation: {request.operation}")


__all__ = ["AudioVideoMatchService"]
