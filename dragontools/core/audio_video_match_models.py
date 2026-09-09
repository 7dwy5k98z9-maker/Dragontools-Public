# -*- coding: utf-8 -*-
"""Datenvertraege fuer Analyse und Synchronisation zweier Videofassungen."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import AudioStream


@dataclass(slots=True)
class AudioVideoMatcherSettings:
    analysis_width: int = 256
    analysis_height: int = 144
    target_probe_radius_s: float = 1.5
    coarse_fps: float = 2.0
    refine_fps: float = 8.0
    search_window_s: float = 40.0
    min_similarity: float = 0.74
    constant_offset_tolerance_s: float = 0.45
    linear_residual_tolerance_s: float = 0.70
    cut_offset_jump_s: float = 1.20
    min_match_points: int = 3
    max_speed_deviation: float = 0.18
    confidence_block_percent: float = 85.0
    edge_extra_warn_s: float = 0.75
    target_extra_block_s: float = 2.0


@dataclass(slots=True)
class VideoInfo:
    path: str
    duration_s: float
    fps_label: str = ""
    frame_rate_mode: str = ""
    width: int = 0
    height: int = 0
    start_time_s: float = 0.0
    audio_streams: list[AudioStream] = field(default_factory=list)


@dataclass(slots=True)
class FrameSignature:
    time_s: float
    dhash: int
    mean_luma: float
    variance: float
    bits: int = 256
    edge_hash: int = 0
    edge_bits: int = 0
    edge_density: float = 0.0
    backend: str = "python"


@dataclass(slots=True)
class MatchPoint:
    reference_time_s: float
    matched_time_s: float
    similarity: float
    confidence: float


@dataclass(slots=True)
class CutRegion:
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass(slots=True)
class CutMatchResult:
    region: CutRegion
    target_start_s: float
    target_end_s: float
    source_start_s: float
    source_end_s: float
    similarity_before: float
    similarity_after: float
    source_extra_s: float = 0.0
    target_extra_s: float = 0.0
    resolved: bool = True
    warning: str = ""


@dataclass(slots=True)
class TimeMappingResult:
    mode: str
    offset_s: float
    speed_factor: float
    residual_error_s: float
    drift_s: float
    confidence_percent: float
    match_points: list[MatchPoint]
    unmatched_reference_times: list[float]
    source_info: VideoInfo
    target_info: VideoInfo
    common_start_target_s: float = 0.0
    common_end_target_s: float = 0.0
    source_extra_start_s: float = 0.0
    source_extra_end_s: float = 0.0
    target_extra_start_s: float = 0.0
    target_extra_end_s: float = 0.0
    suspect_cut_ranges: list[CutRegion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    can_process: bool = False

    @property
    def needs_cut_regions(self) -> bool:
        return self.mode == "C"


@dataclass(slots=True)
class AudioSyncSegment:
    target_start_s: float
    target_end_s: float
    source_start_s: float
    source_end_s: float
    speed_factor: float = 1.0
    reason: str = ""

    @property
    def target_duration_s(self) -> float:
        return max(0.0, self.target_end_s - self.target_start_s)

    @property
    def source_duration_s(self) -> float:
        return max(0.0, self.source_end_s - self.source_start_s)


@dataclass(slots=True)
class AudioSyncPlan:
    mode: str
    audio_stream_index: int
    target_duration_s: float
    segments: list[AudioSyncSegment]
    filter_kind: str
    filter_graph: str
    target_codec: str
    target_bitrate: str
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""
