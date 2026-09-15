# -*- coding: utf-8 -*-
"""Public façade for media timing analysis."""
from __future__ import annotations

from typing import Callable

from ..core.process_runner import tool_available
from .duration_repair_models import MediaTimingInfo
from .duration_timing_inference import (
    derive_frame_rate_from_source_duration as _derive_frame_rate,
    derived_fps_suffix as _derived_fps_suffix,
    fps_label as _fps_label,
    infer_frame_rate_mode as _infer_frame_rate_mode,
)
from .duration_timing_mapping import apply_ffprobe_timing as _apply_ffprobe, apply_mediainfo_timing as _apply_mediainfo
from .duration_timing_parsing import (
    choose_frame_rate as _choose_frame_rate,
    max_known as _max_known,
    nearest_common_rate as _nearest_common_rate,
    nearest_common_rate_loose as _nearest_common_rate_loose,
    parse_duration_tag as _parse_duration_tag,
    parse_fraction as _parse_fraction,
    parse_int as _parse_int,
    parse_mediainfo_duration as _parse_mediainfo_duration,
    parse_seconds as _parse_seconds,
    stream_duration as _stream_duration,
)
from .duration_timing_sources import TimingSourceReader


class MediaTimingAnalyzer:
    """Coordinates source reading, payload mapping and frame-rate inference."""

    def __init__(self, *, ffprobe_path: str, mediainfo_path: str = "", run_command: Callable | None = None, creationflags: int | None = None) -> None:
        self._ffprobe_path = str(ffprobe_path or "")
        self._mediainfo_path = str(mediainfo_path or "")
        self._sources = TimingSourceReader(ffprobe_path=self._ffprobe_path, mediainfo_path=self._mediainfo_path, run_command=run_command, creationflags=creationflags)
        # Legacy attributes retained for tests/extensions that inspect them.
        self._run_command = self._sources.run_command
        self._subprocess_kwargs = self._sources.subprocess_kwargs

    def get_media_timing_info(self, path: str, *, expected_duration_s: float | None = None) -> MediaTimingInfo:
        info = MediaTimingInfo(path=path)
        if tool_available(self._mediainfo_path):
            try:
                self.apply_mediainfo_timing(info, self.run_mediainfo_json(path))
            except Exception as exc:
                info.warnings.append(f"MediaInfo-Timinganalyse fehlgeschlagen: {exc}")
        try:
            needs_frames = info.video_frame_count is None or info.video_frame_count <= 0
            self.apply_ffprobe_timing(info, self.run_ffprobe_json(path, count_frames=needs_frames))
        except Exception as exc:
            info.warnings.append(f"ffprobe-Timinganalyse fehlgeschlagen: {exc}")
        self.derive_frame_rate_from_source_duration(info, expected_duration_s)
        if info.frame_rate_mode == "unknown":
            info.frame_rate_mode = self.infer_frame_rate_mode(info)
        return info

    def run_ffprobe_json(self, path: str, *, count_frames: bool = False) -> dict:
        return self._sources.run_ffprobe_json(path, count_frames=count_frames)

    def run_mediainfo_json(self, path: str) -> dict:
        return self._sources.run_mediainfo_json(path)

    @staticmethod
    def apply_ffprobe_timing(info: MediaTimingInfo, data: dict) -> None:
        _apply_ffprobe(info, data)

    @staticmethod
    def apply_mediainfo_timing(info: MediaTimingInfo, data: dict) -> None:
        _apply_mediainfo(info, data)

    @staticmethod
    def derive_frame_rate_from_source_duration(info: MediaTimingInfo, expected_duration_s: float | None) -> None:
        _derive_frame_rate(info, expected_duration_s)

    @staticmethod
    def infer_frame_rate_mode(info: MediaTimingInfo) -> str:
        return _infer_frame_rate_mode(info)


__all__ = [
    "MediaTimingAnalyzer", "_stream_duration", "_parse_seconds", "_parse_duration_tag",
    "_parse_mediainfo_duration", "_parse_int", "_parse_fraction", "_nearest_common_rate",
    "_nearest_common_rate_loose", "_derived_fps_suffix", "_fps_label", "_choose_frame_rate", "_max_known",
]
