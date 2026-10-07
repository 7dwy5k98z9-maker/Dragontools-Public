# -*- coding: utf-8 -*-
"""Erzeugt FFmpeg-Audioplaene aus einem bereits bestimmten Zeitmodell."""
from __future__ import annotations

from .audio_video_match_models import (
    AudioSyncPlan,
    AudioSyncSegment,
    CutMatchResult,
    TimeMappingResult,
    VideoInfo,
    INTERIOR_TARGET_EXTRA_TOLERANCE_S,
)
from .models import AudioStream
from .lang_codes import canonical_lang
from .strict_numbers import nonnegative_integer
from .audio_sync_validation import mapping_error, positive_tempo, cuts_error
from .audio_video_stream_timing import selected_audio_timing, source_audio_timing_filter


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
    remaining = positive_tempo(factor)
    chain: list[float] = []
    while remaining < 0.5:
        chain.append(0.5)
        remaining /= 0.5
    while remaining > 2.0:
        chain.append(2.0)
        remaining /= 2.0
    chain.append(remaining)
    return [f"atempo={value:.8f}".rstrip("0").rstrip(".") for value in chain if abs(value - 1.0) > 0.00000001]


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
            reason = (
                f"Gewählte Audiospur #{audio_stream_index} wurde in der Quelle nicht gefunden."
                if audio_stream_index is not None
                else "Keine Audiospur gefunden."
            )
            return AudioSyncPlan(
                mode=mapping.mode,
                audio_stream_index=-1,
                target_duration_s=mapping.target_info.duration_s,
                segments=[],
                filter_kind="af",
                filter_graph="",
                target_codec="aac",
                target_bitrate="256k",
                target_language="",
                blocked=True,
                block_reason=reason,
            )
        audio_offset, timing_error = selected_audio_timing(mapping.source_info, stream.index)
        invalid = mapping_error(mapping) or timing_error
        if invalid:
            return AudioSyncPlan(mode=mapping.mode, audio_stream_index=stream.index,
                target_duration_s=0.0, segments=[], filter_kind="af", filter_graph="",
                target_codec="aac", target_bitrate="256k", blocked=True, block_reason=invalid)
        codec, bitrate = self._output_audio_format(stream)
        if mapping.mode in {"A", "B"}:
            segments = self._segments_for_linear(mapping)
            blocked, reason = self._linear_block_reason(mapping, segments)
            graph = self._single_audio_filter(segments[0], mapping.target_info.duration_s, audio_offset) if segments else ""
            return AudioSyncPlan(
                mode=mapping.mode,
                audio_stream_index=stream.index,
                target_duration_s=mapping.target_info.duration_s,
                segments=segments,
                filter_kind="af",
                filter_graph=graph,
                target_codec=codec,
                target_bitrate=bitrate,
                target_language=canonical_lang(stream.language),
                warnings=list(mapping.warnings),
                blocked=blocked,
                block_reason=reason,
            )
        if mapping.mode == "C":
            cuts = list(cut_results or [])
            invalid_cuts = cuts_error(mapping, cuts)
            if invalid_cuts:
                return AudioSyncPlan(mode="C", audio_stream_index=stream.index,
                    target_duration_s=mapping.target_info.duration_s, segments=[],
                    filter_kind="filter_complex", filter_graph="", target_codec=codec,
                    target_bitrate=bitrate, blocked=True, block_reason=invalid_cuts)

            unresolved = [
                cut for cut in cuts
                if (not cut.resolved) or cut.target_extra_s > INTERIOR_TARGET_EXTRA_TOLERANCE_S
            ]
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
                    target_language=canonical_lang(stream.language),
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
                    target_language=canonical_lang(stream.language),
                    warnings=list(mapping.warnings) + [cut.warning for cut in unresolved if cut.warning],
                    blocked=True,
                    block_reason="Mindestens ein Zielbereich enthält Inhalt ohne deutsche Audioentsprechung.",
                )
            segments = self._segments_for_cuts(mapping, cuts)
            graph = self._concat_filter(stream.index, segments, mapping.target_info.duration_s, audio_offset)
            return AudioSyncPlan(
                mode="C",
                audio_stream_index=stream.index,
                target_duration_s=mapping.target_info.duration_s,
                segments=segments,
                filter_kind="filter_complex",
                filter_graph=graph,
                target_codec=codec,
                target_bitrate=bitrate,
                target_language=canonical_lang(stream.language),
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
            target_language=canonical_lang(stream.language),
            warnings=list(mapping.warnings),
            blocked=True,
            block_reason="Zeitmodell ist nicht automatisch verarbeitbar.",
        )

    @staticmethod
    def _select_audio_stream(info: VideoInfo, audio_stream_index: int | None) -> AudioStream | None:
        if audio_stream_index is not None:
            try:
                selected = nonnegative_integer(audio_stream_index)
            except (TypeError, ValueError, OverflowError):
                return None
            for stream in info.audio_streams:
                if nonnegative_integer(stream.index) == selected:
                    return stream
            return None
        return preferred_german_audio_stream(info)

    @staticmethod
    def _output_audio_format(stream: AudioStream) -> tuple[str, str]:
        if int(stream.channels or 0) <= 1:
            return "aac", "128k"
        if int(stream.channels or 0) == 2:
            return "aac", "256k"
        return "eac3", "640k"

    @staticmethod
    def _linear_block_reason(mapping: TimeMappingResult, segments: list[AudioSyncSegment]) -> tuple[bool, str]:
        # `can_process` is the authoritative classifier decision and already
        # includes the configured confidence/edge thresholds. Re-evaluating it
        # here with hard-coded defaults can accidentally reopen a blocked job.
        if not mapping.can_process:
            if mapping.target_extra_start_s > 0.0 or mapping.target_extra_end_s > 0.0:
                return True, "Zielvideo enthält zusätzlichen Inhalt ohne deutsche Audioentsprechung; automatische Verarbeitung wurde nicht freigegeben."
            if mapping.confidence_percent < 100.0:
                return True, "Zeitmodell wurde wegen unzureichender Match-Sicherheit nicht für die automatische Verarbeitung freigegeben."
            return True, "Zeitmodell wurde nicht für die automatische Verarbeitung freigegeben."
        if not segments:
            return True, "Kein gültiger Audioabschnitt vorhanden."
        return False, ""

    @staticmethod
    def _segments_for_linear(mapping: TimeMappingResult) -> list[AudioSyncSegment]:
        target_duration = float(mapping.target_info.duration_s or 0.0)
        source_duration = float(mapping.source_info.duration_s or 0.0)
        speed = max(0.01, float(mapping.speed_factor or 1.0))
        offset = float(mapping.offset_s or 0.0)

        # Mapping direction is source_time = speed * target_time + offset.
        # For a negative offset the target starts before source audio exists;
        # do not move source t=0 to target t=0. Preserve that leading gap and
        # let the render filter insert silence at the actual target position.
        target_start = max(0.0, -offset / speed)
        target_end = min(target_duration, (source_duration - offset) / speed)
        target_start = min(target_start, target_duration)
        target_end = max(target_start, target_end)

        source_start = max(0.0, speed * target_start + offset)
        source_end = min(source_duration, speed * target_end + offset)
        if source_end <= source_start or target_end <= target_start:
            return []
        return [AudioSyncSegment(
            target_start_s=target_start,
            target_end_s=target_end,
            source_start_s=source_start,
            source_end_s=source_end,
            speed_factor=speed,
            reason="linear",
        )]

    def _segments_for_cuts(self, mapping: TimeMappingResult, cuts: list[CutMatchResult]) -> list[AudioSyncSegment]:
        target_duration = float(mapping.target_info.duration_s or 0.0)
        source_duration = float(mapping.source_info.duration_s or 0.0)
        speed = max(0.01, float(mapping.speed_factor or 1.0))
        cursor_target = min(target_duration, max(0.0, -mapping.offset_s / speed))
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
    def _single_audio_filter(segment: AudioSyncSegment, target_duration_s: float, audio_offset_s=None) -> str:
        filters = source_audio_timing_filter(audio_offset_s) + [
            f"atrim=start={segment.source_start_s:.3f}:end={segment.source_end_s:.3f}",
            "asetpts=PTS-STARTPTS",
        ]
        filters.extend(atempo_chain(segment.speed_factor))
        if segment.target_start_s > 0.0005:
            delay_ms = max(1, int(round(segment.target_start_s * 1000.0)))
            filters.append(f"adelay={delay_ms}:all=1")
        filters.append("asetpts=N/SR/TB")
        filters.append(f"apad=whole_dur={target_duration_s:.3f}")
        filters.append(f"atrim=duration={target_duration_s:.3f}")
        return ",".join(filters)

    @staticmethod
    def _concat_filter(audio_index: int, segments: list[AudioSyncSegment], target_duration_s: float, audio_offset_s=None) -> str:
        if not segments:
            return ""
        split_labels = "".join(f"[src{i}]" for i in range(len(segments)))
        timing = source_audio_timing_filter(audio_offset_s)
        timing.append(f"asplit={len(segments)}{split_labels}")
        parts = [f"[0:{audio_index}]{','.join(timing)}"]
        concat_inputs: list[str] = []
        for idx, segment in enumerate(segments):
            duration = max(0.05, segment.target_duration_s)
            filters = [
                f"atrim=start={segment.source_start_s:.3f}:end={segment.source_end_s:.3f}",
                "asetpts=PTS-STARTPTS",
            ]
            filters.extend(atempo_chain(segment.speed_factor))
            filters.append("asetpts=N/SR/TB")
            # Preserve the target timeline even when anchor rounding leaves a
            # tiny local shortfall.  Larger target-only regions are blocked
            # before planning because their correct silence position is unknown.
            filters.append(f"apad=whole_dur={duration:.3f}")
            filters.append(f"atrim=duration={duration:.3f}")
            if duration > 0.10:
                filters.append("afade=t=in:st=0:d=0.015")
                filters.append(f"afade=t=out:st={max(0.0, duration - 0.015):.3f}:d=0.015")
            label = f"a{idx}"
            parts.append(f"[src{idx}]{','.join(filters)}[{label}]")
            concat_inputs.append(f"[{label}]")
        final_filters = [f"concat=n={len(segments)}:v=0:a=1"]
        if segments[0].target_start_s > 0.0005:
            delay_ms = max(1, int(round(segments[0].target_start_s * 1000.0)))
            final_filters.append(f"adelay={delay_ms}:all=1")
        final_filters.append("asetpts=N/SR/TB")
        final_filters.extend([f"apad=whole_dur={target_duration_s:.3f}",
                              f"atrim=duration={target_duration_s:.3f}"])
        parts.append(f"{''.join(concat_inputs)}{','.join(final_filters)}[aout]")
        return ";".join(parts)
