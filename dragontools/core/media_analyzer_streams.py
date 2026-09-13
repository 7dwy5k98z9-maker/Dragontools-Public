# -*- coding: utf-8 -*-
"""Compatibility facade for MediaAnalyzer stream model builders."""
from __future__ import annotations

from .media_analyzer_audio_streams import _build_audio_streams
from .media_analyzer_subtitle_streams import (
    _build_subtitle_streams,
    _normalize_subtitle_codec,
    _parse_stream_duration_s,
    _subtitle_event_count,
)
from .media_analyzer_video_streams import _build_video_streams

__all__ = [
    "_build_video_streams",
    "_build_audio_streams",
    "_build_subtitle_streams",
    "_normalize_subtitle_codec",
    "_parse_stream_duration_s",
    "_subtitle_event_count",
]
