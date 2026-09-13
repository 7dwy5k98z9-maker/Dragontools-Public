# -*- coding: utf-8 -*-
"""Request/callback contracts for audio/video matching operations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.audio_video_matcher import CutMatchResult, TimeMappingResult

LogLine = Callable[[str], None]
ProgressFn = Callable[[int], None]
ObjectFn = Callable[[object], None]
ResultFn = Callable[[str], None]


@dataclass(frozen=True)
class AudioVideoMatchRequest:
    operation: str
    source_path: str
    target_path: str
    output_path: str = ""
    audio_stream_index: int | None = None
    mapping_result: TimeMappingResult | None = None
    cut_ranges_text: str = ""
    cut_results: tuple[CutMatchResult, ...] = ()

    @classmethod
    def create(
        cls,
        operation: str,
        *,
        source_path: str,
        target_path: str,
        output_path: str = "",
        audio_stream_index: int | None = None,
        mapping_result: TimeMappingResult | None = None,
        cut_ranges_text: str = "",
        cut_results: list[CutMatchResult] | tuple[CutMatchResult, ...] | None = None,
    ) -> "AudioVideoMatchRequest":
        return cls(
            operation=str(operation or "analyze").lower(),
            source_path=str(Path(source_path).resolve()) if source_path else "",
            target_path=str(Path(target_path).resolve()) if target_path else "",
            output_path=str(Path(output_path).resolve()) if output_path else "",
            audio_stream_index=audio_stream_index,
            mapping_result=mapping_result,
            cut_ranges_text=str(cut_ranges_text or ""),
            cut_results=tuple(cut_results or ()),
        )


@dataclass(frozen=True)
class AudioVideoMatchCallbacks:
    log_line: LogLine
    progress: ProgressFn
    analysis_ready: ObjectFn
    cuts_ready: ObjectFn
    plan_ready: ObjectFn
    result_ready: ResultFn


__all__ = ["AudioVideoMatchCallbacks", "AudioVideoMatchRequest"]
