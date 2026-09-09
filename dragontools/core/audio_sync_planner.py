# -*- coding: utf-8 -*-
"""Erzeugt FFmpeg-Audioplaene aus einem bereits bestimmten Zeitmodell."""
from __future__ import annotations

from .audio_video_match_models import (
    AudioSyncPlan,
    AudioSyncSegment,
    CutMatchResult,
    TimeMappingResult,
    VideoInfo,
)
from .models import AudioStream


def preferred_german_audio_stream(info: VideoInfo) -> AudioStream | None:
    audios = list(info.audio_streams or [])
    if not audios:
        return None
    for stream in audios:
        lang = (stream.language or "").lower()
        title = (stream.title or "").lower()
        if lang in {"de", "deu", "ger", "german", "deutsch"} or "deutsch" in title or "german" in title:
            return stream
    return audios[0]


def atempo_chain(factor: float) -> list[str]:
    remaining = max(0.01, float(factor or 1.0))
    chain: list[float] = []
    while remaining < 0.5:
        chain.append(0.5)
        remaining /= 0.5
    while remaining > 2.0:
        chain.append(2.0)
        remaining /= 2.0
    chain.append(remaining)
    return [f"atempo={value:.8f}".rstrip("0").rstrip(".") for value in chain if abs(value - 1.0) > 0.0001]


class AudioSyncPlanner:
    """Plant lineare oder segmentierte Audioanpassungen ohne Videoanalyse."""

    def build_plan(
        self,
        mapping: TimeMappingResult,
        *,
        audio_stream_index: int | None = None,
        cut_results: list[CutMatchResult] | None = None,
    ) -> AudioSyncPlan:
        stream = self._select_audio_stream(mapping.source_info, audio_stream_index)
        if stream is None:
            return AudioSyncPlan(
                mode=mapping.mode,
                audio_stream_index=-1,
                target_duration_s=mapping.target_info.duration_s,
                segments=[],
                filter_kind="af",
                filter_graph="",
                target_codec="aac",
                target_bitrate="256k",
                blocked=True,
                block_reason="Keine deutsche Audiospur gefunden.",
            )
        codec, bitrate = self._output_audio_format(stream)
        if mapping.mode in {"A", "B"}:
            segments = self._segments_for_linear(mapping)
            blocked, reason = self._linear_block_reason(mapping, segments)
            graph = self._single_audio_filter(segments[0], mapping.target_info.duration_s) if segments else ""
            return AudioSyncPlan(
                mode=mapping.mode,
                audio_stream_index=stream.index,
                target_duration_s=mapping.target_info.duration_s,
                segments=segments,
                filter_kind="af",
                filter_graph=graph,
                target_codec=codec,
                target_bitrate=bitrate,
                warnings=list(mapping.warnings),
                blocked=blocked,
                block_reason=reason,
            )
        if mapping.mode == "C":
            cuts = list(cut_results or [])
            unresolved = [cut for cut in cuts if not cut.resolved]
            if not cuts:
                return AudioSyncPlan(
                    mode="C",
                    audio_stream_index=stream.index,
                    target_duration_s=mapping.target_info.duration_s,
                    segments=[],
                    filter_kind="filter_complex",
                    filter_graph="",
                    target_codec=codec,
                    target_bitrate=bitrate,
                    warnings=list(mapping.warnings),
                    blocked=True,
                    block_reason="Fall C benötigt zuerst analysierte Schnittbereiche.",
                )
            if unresolved:
                return AudioSyncPlan(
                    mode="C",
                    audio_stream_index=stream.index,
                    target_duration_s=mapping.target_info.duration_s,
                    segments=[],
                    filter_kind="filter_complex",
                    filter_graph="",
                    target_codec=codec,
                    target_bitrate=bitrate,
                    warnings=list(mapping.warnings) + [cut.warning for cut in unresolved if cut.warning],
                    blocked=True,
                    block_reason="Mindestens ein Zielbereich enthält Inhalt ohne deutsche Audioentsprechung.",
                )
            segments = self._segments_for_cuts(mapping, cuts)
            graph = self._concat_filter(stream.index, segments, mapping.target_info.duration_s)
            return AudioSyncPlan(
                mode="C",
                audio_stream_index=stream.index,
                target_duration_s=mapping.target_info.duration_s,
                segments=segments,
                filter_kind="filter_complex",
                filter_graph=graph,
                target_codec=codec,
                target_bitrate=bitrate,
                warnings=list(mapping.warnings) + [cut.warning for cut in cuts if cut.warning],
                blocked=not bool(segments),
                block_reason="" if segments else "Kein gültiger Audio-Segmentplan erzeugt.",
            )
        return AudioSyncPlan(
            mode=mapping.mode,
            audio_stream_index=stream.index,
            target_duration_s=mapping.target_info.duration_s,
            segments=[],
            filter_kind="af",
            filter_graph="",
            target_codec=codec,
            target_bitrate=bitrate,
            warnings=list(mapping.warnings),
            blocked=True,
            block_reason="Zeitmodell ist nicht automatisch verarbeitbar.",
        )

    @staticmethod
    def _select_audio_stream(info: VideoInfo, audio_stream_index: int | None) -> AudioStream | None:
        if audio_stream_index is not None:
            for stream in info.audio_streams:
                if int(stream.index) == int(audio_stream_index):
                    return stream
        return preferred_german_audio_stream(info)

    @staticmethod
    def _output_audio_format(stream: AudioStream) -> tuple[str, str]:
        if int(stream.channels or 0) <= 2:
            return "aac", "256k"
        return "eac3", "640k"

    @staticmethod
    def _linear_block_reason(mapping: TimeMappingResult, segments: list[AudioSyncSegment]) -> tuple[bool, str]:
        if not mapping.can_process:
            if mapping.target_extra_start_s > 2.0 or mapping.target_extra_end_s > 2.0:
                return True, "Zielvideo enthält zusätzlichen Inhalt ohne deutsche Audioentsprechung."
            if mapping.confidence_percent < 85.0:
                return True, "Match-Sicherheit zu niedrig."
        if not segments:
            return True, "Kein gültiger Audioabschnitt vorhanden."
        return False, ""

    @staticmethod
    def _segments_for_linear(mapping: TimeMappingResult) -> list[AudioSyncSegment]:
        target_duration = float(mapping.target_info.duration_s or 0.0)
        source_duration = float(mapping.source_info.duration_s or 0.0)
        speed = max(0.01, float(mapping.speed_factor or 1.0))
        source_start = max(0.0, mapping.offset_s)
        source_end = min(source_duration, source_start + target_duration * speed)
        if source_end <= source_start:
            return []
        return [AudioSyncSegment(
            target_start_s=0.0,
            target_end_s=target_duration,
            source_start_s=source_start,
            source_end_s=source_end,
            speed_factor=speed,
            reason="linear",
        )]

    def _segments_for_cuts(self, mapping: TimeMappingResult, cuts: list[CutMatchResult]) -> list[AudioSyncSegment]:
        target_duration = float(mapping.target_info.duration_s or 0.0)
        source_duration = float(mapping.source_info.duration_s or 0.0)
        speed = max(0.01, float(mapping.speed_factor or 1.0))
        cursor_target = 0.0
        cursor_source = max(0.0, mapping.offset_s)
        segments: list[AudioSyncSegment] = []
        for cut in sorted(cuts, key=lambda item: item.target_start_s):
            if cut.target_start_s > cursor_target + 0.02:
                self._append_segment(
                    segments, cursor_target, cut.target_start_s,
                    cursor_source, max(cursor_source, cut.source_start_s),
                    speed, "vor Schnitt",
                )
            cut_target_len = max(0.0, cut.target_end_s - cut.target_start_s)
            source_cut_end = min(cut.source_end_s, cut.source_start_s + cut_target_len * speed)
            self._append_segment(
                segments, cut.target_start_s, cut.target_end_s,
                cut.source_start_s, source_cut_end, speed, "Schnittbereich",
            )
            cursor_target = cut.target_end_s
            cursor_source = max(cut.source_end_s, source_cut_end)
        if cursor_target < target_duration - 0.02:
            predicted_end = min(source_duration, cursor_source + (target_duration - cursor_target) * speed)
            self._append_segment(
                segments, cursor_target, target_duration,
                cursor_source, predicted_end, speed, "nach Schnitt",
            )
        return segments

    @staticmethod
    def _append_segment(
        segments: list[AudioSyncSegment],
        target_start: float,
        target_end: float,
        source_start: float,
        source_end: float,
        speed: float,
        reason: str,
    ) -> None:
        target_len = max(0.0, target_end - target_start)
        source_len = max(0.0, source_end - source_start)
        if target_len < 0.05 or source_len < 0.05:
            return
        segments.append(AudioSyncSegment(
            target_start_s=target_start,
            target_end_s=target_end,
            source_start_s=max(0.0, source_start),
            source_end_s=max(0.0, source_end),
            speed_factor=speed,
            reason=reason,
        ))

    @staticmethod
    def _single_audio_filter(segment: AudioSyncSegment, target_duration_s: float) -> str:
        filters = [
            f"atrim=start={segment.source_start_s:.3f}:end={segment.source_end_s:.3f}",
            "asetpts=PTS-STARTPTS",
        ]
        filters.extend(atempo_chain(segment.speed_factor))
        filters.append(f"apad=whole_dur={target_duration_s:.3f}")
        filters.append(f"atrim=duration={target_duration_s:.3f}")
        return ",".join(filters)

    @staticmethod
    def _concat_filter(audio_index: int, segments: list[AudioSyncSegment], target_duration_s: float) -> str:
        if not segments:
            return ""
        split_labels = "".join(f"[src{i}]" for i in range(len(segments)))
        parts = [f"[0:{audio_index}]asplit={len(segments)}{split_labels}"]
        concat_inputs: list[str] = []
        for idx, segment in enumerate(segments):
            duration = max(0.05, segment.target_duration_s)
            filters = [
                f"atrim=start={segment.source_start_s:.3f}:end={segment.source_end_s:.3f}",
                "asetpts=PTS-STARTPTS",
            ]
            filters.extend(atempo_chain(segment.speed_factor))
            filters.append(f"atrim=duration={duration:.3f}")
            if duration > 0.10:
                filters.append("afade=t=in:st=0:d=0.015")
                filters.append(f"afade=t=out:st={max(0.0, duration - 0.015):.3f}:d=0.015")
            label = f"a{idx}"
            parts.append(f"[src{idx}]{','.join(filters)}[{label}]")
            concat_inputs.append(f"[{label}]")
        parts.append(
            f"{''.join(concat_inputs)}concat=n={len(segments)}:v=0:a=1,"
            f"apad=whole_dur={target_duration_s:.3f},"
            f"atrim=duration={target_duration_s:.3f}[aout]"
        )
        return ";".join(parts)
