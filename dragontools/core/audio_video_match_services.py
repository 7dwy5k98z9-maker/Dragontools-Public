# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .audio_video_frame_analysis import FrameExtractor, FrameMatcher, RunBytesFn
from .audio_video_match_models import (
    AudioVideoMatcherSettings,
    CutMatchResult,
    CutRegion,
    MatchPoint,
    TimeMappingResult,
    VideoInfo,
)
from .audio_video_match_utils import format_seconds, parse_cut_regions
from .audio_video_time_mapping import _linear_regression, classify_time_mapping, select_landmark_times
from .media_analyzer import analyze_media
from .paths import ToolPaths, get_tool_paths

class VideoAnalyzer:
    def __init__(self, tools: ToolPaths | None = None) -> None:
        self.tools = tools or get_tool_paths()

    def analyze(self, path: str) -> VideoInfo:
        mi = analyze_media(path, self.tools)
        video = mi.primary_video
        return VideoInfo(
            path=str(Path(path).resolve()),
            duration_s=float(mi.duration_s or getattr(video, "duration_s", 0.0) or 0.0),
            fps_label=str(getattr(video, "frame_rate", "") or ""),
            frame_rate_mode=str(getattr(video, "frame_rate_mode", "") or ""),
            width=int(getattr(video, "width", 0) or 0),
            height=int(getattr(video, "height", 0) or 0),
            audio_streams=list(mi.audio_streams or []),
        )


class AudioVideoMatcher:
    def __init__(
        self,
        tools: ToolPaths | None = None,
        *,
        settings: AudioVideoMatcherSettings | None = None,
        run_bytes: RunBytesFn | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.tools = tools or get_tool_paths()
        self.settings = settings or AudioVideoMatcherSettings()
        extractor = FrameExtractor(self.tools.ffmpeg, settings=self.settings, run_bytes=run_bytes)
        self.frame_matcher = FrameMatcher(extractor, settings=self.settings)
        self.video_analyzer = VideoAnalyzer(self.tools)
        self._progress = progress

    def _log_progress(self, message: str) -> None:
        if callable(self._progress):
            self._progress(message)

    def analyze(self, source_path: str, target_path: str) -> TimeMappingResult:
        self._log_progress("Metadaten analysieren")
        source_info = self.video_analyzer.analyze(source_path)
        target_info = self.video_analyzer.analyze(target_path)
        if not source_info.audio_streams:
            return TimeMappingResult(
                mode="D",
                offset_s=0.0,
                speed_factor=1.0,
                residual_error_s=999.0,
                drift_s=0.0,
                confidence_percent=0.0,
                match_points=[],
                unmatched_reference_times=[],
                source_info=source_info,
                target_info=target_info,
                warnings=["Deutsche Quelle enthält keine Audiospur."],
                can_process=False,
            )

        landmarks = select_landmark_times(target_info.duration_s)
        points: list[MatchPoint] = []
        unmatched: list[float] = []
        duration_ratio = (
            source_info.duration_s / target_info.duration_s
            if target_info.duration_s > 0 and source_info.duration_s > 0
            else 1.0
        )
        dynamic_window = min(
            180.0,
            max(self.settings.search_window_s, abs(source_info.duration_s - target_info.duration_s) * 0.12 + 12.0),
        )

        for idx, landmark in enumerate(landmarks, start=1):
            self._log_progress(f"Landmarke {idx}/{len(landmarks)}")
            try:
                reference = self.frame_matcher.characteristic_signature(
                    target_info.path,
                    landmark,
                    target_info.duration_s,
                )
                if reference is None:
                    unmatched.append(landmark)
                    continue
                if len(points) >= 2:
                    a, b, _rmse, _max_abs = _linear_regression(points)
                    expected = a * reference.time_s + b
                else:
                    expected = reference.time_s * duration_ratio
                match = self.frame_matcher.find_match(
                    source_info.path,
                    reference,
                    expected_time_s=expected,
                    source_duration_s=source_info.duration_s,
                    search_window_s=dynamic_window,
                )
                if match is None:
                    unmatched.append(reference.time_s)
                else:
                    points.append(match)
            except Exception:
                unmatched.append(landmark)

        self._log_progress("Zeitmodell berechnen")
        return classify_time_mapping(
            points,
            source_info=source_info,
            target_info=target_info,
            unmatched_reference_times=unmatched,
            expected_count=len(landmarks),
            settings=self.settings,
        )

    def refine_cut_regions(self, mapping: TimeMappingResult, ranges_text: str) -> list[CutMatchResult]:
        regions = parse_cut_regions(ranges_text, duration_s=mapping.target_info.duration_s)
        analyzer = CutRegionAnalyzer(self.frame_matcher, settings=self.settings, progress=self._progress)
        return analyzer.refine(mapping, regions)


class CutRegionAnalyzer:
    def __init__(
        self,
        matcher: FrameMatcher,
        *,
        settings: AudioVideoMatcherSettings | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.matcher = matcher
        self.settings = settings or matcher.settings
        self._progress = progress

    def _progress_msg(self, message: str) -> None:
        if callable(self._progress):
            self._progress(message)

    def refine(self, mapping: TimeMappingResult, regions: list[CutRegion]) -> list[CutMatchResult]:
        results: list[CutMatchResult] = []
        cumulative_delta = 0.0
        for idx, region in enumerate(regions, start=1):
            self._progress_msg(f"Schnittbereich {idx}/{len(regions)} fein analysieren")
            before_target = max(0.0, region.start_s - 0.75)
            after_target = min(mapping.target_info.duration_s, region.end_s + 0.75)
            source_before_expected = mapping.speed_factor * before_target + mapping.offset_s + cumulative_delta
            source_after_expected = mapping.speed_factor * after_target + mapping.offset_s + cumulative_delta
            before = self._match_anchor(mapping, before_target, source_before_expected, region.duration_s + 4.0)
            after = self._match_anchor(mapping, after_target, source_after_expected, region.duration_s + 4.0)
            if before is None or after is None:
                results.append(CutMatchResult(
                    region=region,
                    target_start_s=region.start_s,
                    target_end_s=region.end_s,
                    source_start_s=max(0.0, mapping.speed_factor * region.start_s + mapping.offset_s + cumulative_delta),
                    source_end_s=max(0.0, mapping.speed_factor * region.end_s + mapping.offset_s + cumulative_delta),
                    similarity_before=0.0 if before is None else before.similarity,
                    similarity_after=0.0 if after is None else after.similarity,
                    resolved=False,
                    warning="Schnittbereich konnte nicht sicher genug verfeinert werden.",
                ))
                continue

            source_start = before.matched_time_s + max(0.0, region.start_s - before.reference_time_s) * mapping.speed_factor
            source_end = after.matched_time_s - max(0.0, after.reference_time_s - region.end_s) * mapping.speed_factor
            source_len = max(0.0, source_end - source_start)
            target_len = region.duration_s
            source_extra = max(0.0, source_len - target_len)
            target_extra = max(0.0, target_len - source_len)
            resolved = target_extra <= self.settings.target_extra_block_s
            warning = ""
            if target_extra > self.settings.edge_extra_warn_s:
                warning = (
                    f"Zielbereich {format_seconds(region.start_s)}-{format_seconds(region.end_s)} "
                    f"enthält ca. {target_extra:.1f}s mehr Inhalt als die deutsche Quelle."
                )
            elif source_extra > self.settings.edge_extra_warn_s:
                warning = (
                    f"Deutsche Quelle enthält im Bereich {format_seconds(region.start_s)}-"
                    f"{format_seconds(region.end_s)} ca. {source_extra:.1f}s zusätzliches Material; "
                    "dieser Teil wird aus der deutschen Audiospur entfernt."
                )
            results.append(CutMatchResult(
                region=region,
                target_start_s=region.start_s,
                target_end_s=region.end_s,
                source_start_s=source_start,
                source_end_s=source_end,
                similarity_before=before.similarity,
                similarity_after=after.similarity,
                source_extra_s=source_extra,
                target_extra_s=target_extra,
                resolved=resolved,
                warning=warning,
            ))
            cumulative_delta += source_extra - target_extra
        return results

    def _match_anchor(
        self,
        mapping: TimeMappingResult,
        target_time_s: float,
        source_expected_s: float,
        search_window_s: float,
    ) -> MatchPoint | None:
        reference = self.matcher.characteristic_signature(
            mapping.target_info.path,
            target_time_s,
            mapping.target_info.duration_s,
        )
        if reference is None:
            return None
        return self.matcher.find_match(
            mapping.source_info.path,
            reference,
            expected_time_s=source_expected_s,
            source_duration_s=mapping.source_info.duration_s,
            search_window_s=max(3.0, search_window_s),
        )
