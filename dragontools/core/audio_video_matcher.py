# -*- coding: utf-8 -*-
"""Compatibility facade for the audio/video matching subsystem.

Implementation details live in focused modules:
- :mod:`audio_video_match_utils` for time/range parsing
- :mod:`audio_video_frame_analysis` for frame extraction and image matching
- :mod:`audio_video_time_mapping` for mapping classification
- :mod:`audio_video_match_services` for orchestration/services

Existing imports from ``dragontools.core.audio_video_matcher`` remain stable.
"""
from __future__ import annotations

from .audio_sync_planner import AudioSyncPlanner, atempo_chain, preferred_german_audio_stream
from .audio_video_match_models import (
    AudioSyncPlan,
    AudioSyncSegment,
    AudioVideoMatcherSettings,
    CutMatchResult,
    CutRegion,
    FrameSignature,
    MatchPoint,
    TimeMappingResult,
    VideoInfo,
)
from .audio_video_match_utils import format_seconds, parse_cut_regions, parse_timecode
from .audio_video_frame_analysis import (
    FrameExtractor,
    FrameMatcher,
    RunBytesFn,
    _signature_from_gray_frame,
    frame_similarity,
    image_analysis_backend_label,
    opencv_available,
)
from .audio_video_time_mapping import classify_time_mapping, select_landmark_times
from .audio_video_match_services import AudioVideoMatcher, CutRegionAnalyzer, VideoAnalyzer

__all__ = [
    "AudioSyncPlan",
    "AudioSyncPlanner",
    "AudioSyncSegment",
    "AudioVideoMatcher",
    "AudioVideoMatcherSettings",
    "CutMatchResult",
    "CutRegion",
    "CutRegionAnalyzer",
    "FrameExtractor",
    "FrameMatcher",
    "FrameSignature",
    "MatchPoint",
    "RunBytesFn",
    "TimeMappingResult",
    "VideoAnalyzer",
    "VideoInfo",
    "atempo_chain",
    "classify_time_mapping",
    "format_seconds",
    "frame_similarity",
    "image_analysis_backend_label",
    "opencv_available",
    "parse_cut_regions",
    "parse_timecode",
    "preferred_german_audio_stream",
    "select_landmark_times",
]
