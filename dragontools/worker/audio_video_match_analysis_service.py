# -*- coding: utf-8 -*-
"""Analysis/refinement operations for audio/video matching."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.audio_video_matcher import AudioVideoMatcher, format_seconds, image_analysis_backend_label
from .audio_video_match_contracts import AudioVideoMatchCallbacks, AudioVideoMatchRequest
from .audio_video_match_reporting import log_analysis_result
from .audio_video_match_runtime import AudioVideoMatchProgress, AudioVideoMatchToolIO


class AudioVideoMatchAnalysisService:
    def __init__(
        self,
        *,
        tools: Any,
        callbacks: AudioVideoMatchCallbacks,
        progress: AudioVideoMatchProgress,
        tool_io: AudioVideoMatchToolIO,
    ) -> None:
        self._tools = tools
        self._callbacks = callbacks
        self._progress = progress
        self._tool_io = tool_io

    @staticmethod
    def require_inputs(request: AudioVideoMatchRequest) -> None:
        if not request.source_path or not Path(request.source_path).exists():
            raise RuntimeError("Deutsche Quellvideodatei fehlt.")
        if not request.target_path or not Path(request.target_path).exists():
            raise RuntimeError("Zielvideodatei fehlt.")

    def _matcher(self) -> AudioVideoMatcher:
        return AudioVideoMatcher(
            self._tools,
            run_bytes=self._tool_io.run_binary_stdout,
            progress=self._progress.message,
        )

    def analyze(self, request: AudioVideoMatchRequest) -> None:
        self.require_inputs(request)
        self._callbacks.log_line("▶ Audio-Video-Matcher: Analyse startet.")
        self._callbacks.log_line(f"ℹ️  Bildanalyse: {image_analysis_backend_label()}")
        result = self._matcher().analyze(request.source_path, request.target_path)
        log_analysis_result(result, self._callbacks.log_line)
        self._callbacks.analysis_ready(result)
        self._progress.set(100)

    def refine(self, request: AudioVideoMatchRequest) -> None:
        self.require_inputs(request)
        if request.mapping_result is None:
            raise RuntimeError("Es liegt noch keine A/B/C-Analyse vor.")
        self._callbacks.log_line("▶ Schnittbereich-Feinanalyse startet.")
        cuts = self._matcher().refine_cut_regions(request.mapping_result, request.cut_ranges_text)
        for cut in cuts:
            label = f"{format_seconds(cut.target_start_s)}-{format_seconds(cut.target_end_s)}"
            status = "OK" if cut.resolved else "nicht lösbar"
            self._callbacks.log_line(
                f"ℹ️  Schnitt {label}: Quelle {format_seconds(cut.source_start_s)}-"
                f"{format_seconds(cut.source_end_s)} | {status}"
            )
            if cut.warning:
                self._callbacks.log_line(f"⚠️  {cut.warning}")
        self._callbacks.cuts_ready(cuts)
        self._progress.set(100)


__all__ = ["AudioVideoMatchAnalysisService"]
