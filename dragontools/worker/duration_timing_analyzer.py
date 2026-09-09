# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from typing import Callable

from .duration_repair_models import (
    _COMMON_FRAME_RATES,
    MediaTimingInfo,
    calculate_expected_duration,
    duration_close as _duration_close,
    is_extreme_mismatch as _is_extreme_mismatch,
)
from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs, tool_available


class MediaTimingAnalyzer:
    """Liest und normalisiert Container-, Stream-, Frame- und FPS-Zeitdaten."""

    def __init__(
        self,
        *,
        ffprobe_path: str,
        mediainfo_path: str = "",
        run_command: Callable | None = None,
        creationflags: int | None = None,
    ) -> None:
        self._ffprobe_path = str(ffprobe_path or "")
        self._mediainfo_path = str(mediainfo_path or "")
        self._run_command = run_command or subprocess.run
        self._subprocess_kwargs = _no_window_kwargs()
        if creationflags is not None:
            self._subprocess_kwargs["creationflags"] = int(creationflags)

    def get_media_timing_info(
        self,
        path: str,
        *,
        expected_duration_s: float | None = None,
    ) -> MediaTimingInfo:
        info = MediaTimingInfo(path=path)

        if tool_available(self._mediainfo_path):
            try:
                data = self.run_mediainfo_json(path)
                self.apply_mediainfo_timing(info, data)
            except Exception as exc:
                info.warnings.append(f"MediaInfo-Timinganalyse fehlgeschlagen: {exc}")

        needs_frame_count = info.video_frame_count is None or info.video_frame_count <= 0
        try:
            data = self.run_ffprobe_json(path, count_frames=needs_frame_count)
            self.apply_ffprobe_timing(info, data)
        except Exception as exc:
            info.warnings.append(f"ffprobe-Timinganalyse fehlgeschlagen: {exc}")

        self.derive_frame_rate_from_source_duration(info, expected_duration_s)
        if info.frame_rate_mode == "unknown":
            info.frame_rate_mode = self.infer_frame_rate_mode(info)
        return info

    def run_ffprobe_json(self, path: str, *, count_frames: bool = False) -> dict:
        cmd = [
            self._ffprobe_path,
            "-v",
            "error",
        ]
        if count_frames:
            cmd.append("-count_frames")
        cmd.extend(
            [
                "-show_format",
                "-show_streams",
                "-show_chapters",
                "-of",
                "json",
                str(path),
            ]
        )
        run = self._run_command(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=90,
            **self._subprocess_kwargs,
        )
        if run.returncode != 0:
            raise RuntimeError((run.stderr or "ffprobe fehlgeschlagen.").strip())
        return json.loads(run.stdout or "{}")

    def run_mediainfo_json(self, path: str) -> dict:
        run = self._run_command(
            [self._mediainfo_path, "--Output=JSON", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=60,
            **self._subprocess_kwargs,
        )
        if run.returncode != 0:
            raise RuntimeError((run.stderr or "MediaInfo fehlgeschlagen.").strip())
        return json.loads(run.stdout or "{}")

    def apply_ffprobe_timing(self, info: MediaTimingInfo, data: dict) -> None:
        fmt = data.get("format") or {}
        info.container_duration_s = _parse_seconds(fmt.get("duration"))

        streams = list(data.get("streams") or [])
        videos = [stream for stream in streams if stream.get("codec_type") == "video"]
        audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
        subtitles = [stream for stream in streams if stream.get("codec_type") == "subtitle"]
        attachments = [stream for stream in streams if stream.get("codec_type") == "attachment"]
        info.video_stream_count = len(videos)
        info.audio_stream_count = len(audios)
        info.subtitle_stream_count = len(subtitles)
        info.attachment_stream_count = len(attachments)

        if videos:
            video = videos[0]
            info.codec = str(video.get("codec_name") or "")
            info.video_duration_s = _stream_duration(video)
            info.video_frame_count = (
                _parse_int(video.get("nb_read_frames"))
                or _parse_int(video.get("nb_frames"))
                or info.video_frame_count
            )
            avg = _parse_fraction(video.get("avg_frame_rate"))
            real = _parse_fraction(video.get("r_frame_rate"))
            info.avg_frame_rate = avg
            info.real_frame_rate = real
            info.frame_rate = _choose_frame_rate(avg, real)
            info.has_b_frames = _parse_int(video.get("has_b_frames")) not in (None, 0)
            info.video_start_s = _parse_seconds(video.get("start_time"))

        audio_durations = [_stream_duration(stream) for stream in audios]
        info.audio_duration_s = _max_known(audio_durations)
        if audios:
            info.audio_start_s = _parse_seconds(audios[0].get("start_time"))

        subtitle_durations = [_stream_duration(stream) for stream in subtitles]
        info.subtitle_duration_s = _max_known(subtitle_durations)

        chapters = list(data.get("chapters") or [])
        chapter_ends = [_parse_seconds(chapter.get("end_time")) for chapter in chapters]
        info.chapter_end_s = _max_known(chapter_ends)

    def apply_mediainfo_timing(self, info: MediaTimingInfo, data: dict) -> None:
        tracks = list(((data.get("media") or {}).get("track")) or [])
        mi_video_count = 0
        mi_audio_count = 0
        mi_subtitle_count = 0
        mi_attachment_count = 0
        for track in tracks:
            kind = str(track.get("@type") or track.get("track_type") or "").lower()
            if kind == "general":
                info.container_duration_s = info.container_duration_s or _parse_mediainfo_duration(track.get("Duration"))
            elif kind == "video":
                mi_video_count += 1
                mode = str(track.get("FrameRate_Mode") or track.get("FrameRate_Mode/String") or "").lower()
                if "variable" in mode or mode == "vfr":
                    info.frame_rate_mode = "VFR"
                elif "constant" in mode or mode == "cfr":
                    info.frame_rate_mode = "CFR"
                info.video_duration_s = info.video_duration_s or _parse_mediainfo_duration(track.get("Duration"))
                info.video_frame_count = info.video_frame_count or _parse_int(track.get("FrameCount"))
                if info.frame_rate is None:
                    info.frame_rate = _parse_fraction(track.get("FrameRate"))
                if not info.codec:
                    info.codec = str(track.get("Format") or track.get("CodecID") or "")
            elif kind == "audio":
                mi_audio_count += 1
                duration = _parse_mediainfo_duration(track.get("Duration"))
                info.audio_duration_s = _max_known([info.audio_duration_s, duration])
            elif kind in {"text", "subtitle"}:
                mi_subtitle_count += 1
                duration = _parse_mediainfo_duration(track.get("Duration"))
                info.subtitle_duration_s = _max_known([info.subtitle_duration_s, duration])
            elif kind in {"menu", "attachment"}:
                mi_attachment_count += 1
        if info.video_stream_count <= 0:
            info.video_stream_count = mi_video_count
        if info.audio_stream_count <= 0:
            info.audio_stream_count = mi_audio_count
        if info.subtitle_stream_count <= 0:
            info.subtitle_stream_count = mi_subtitle_count
        if info.attachment_stream_count <= 0:
            info.attachment_stream_count = mi_attachment_count

    def derive_frame_rate_from_source_duration(
        self,
        info: MediaTimingInfo,
        expected_duration_s: float | None,
    ) -> None:
        if not expected_duration_s or expected_duration_s <= 0:
            return
        if not info.video_frame_count or info.video_frame_count <= 0:
            return
        raw_fps = float(info.video_frame_count) / float(expected_duration_s)
        derived = _nearest_common_rate_loose(raw_fps)
        if derived is None:
            return
        derived_duration = float(Fraction(info.video_frame_count, 1) / derived)
        if not _duration_close(derived_duration, expected_duration_s, min_tolerance_s=3.0, relative_tolerance=0.003):
            return
        if info.audio_duration_s is not None and not _duration_close(
            info.audio_duration_s,
            expected_duration_s,
            min_tolerance_s=5.0,
            relative_tolerance=0.02,
        ):
            return
        if not any(_is_extreme_mismatch(value, derived_duration) for value in (info.video_duration_s, info.container_duration_s)):
            return

        reported_expected = calculate_expected_duration(info)
        reported_rate_implausible = (
            info.frame_rate is None
            or float(info.frame_rate) < 1.0
            or (reported_expected is not None and not _duration_close(reported_expected, expected_duration_s))
            or (info.frame_rate_mode or "").upper() == "VFR"
        )
        if not reported_rate_implausible:
            return

        info.frame_rate = derived
        info.frame_rate_derived_from_source = True
        info.frame_rate_mode = "CFR"
        info.warnings.append(
            "Framerate wurde wegen defekter Timeline aus Quelldauer und Frameanzahl abgeleitet."
        )

    def infer_frame_rate_mode(self, info: MediaTimingInfo) -> str:
        if info.frame_rate is None:
            return "unknown"
        if info.avg_frame_rate is not None and info.real_frame_rate is not None:
            if info.avg_frame_rate == info.real_frame_rate:
                return "CFR"
            return "unknown"
        if info.expected_video_duration_s is not None and _duration_close(
            info.video_duration_s,
            info.expected_video_duration_s,
            min_tolerance_s=2.0,
            relative_tolerance=0.01,
        ):
            return "CFR"
        return "unknown"



def _stream_duration(stream: dict) -> float | None:
    duration = _parse_seconds(stream.get("duration"))
    if duration is not None:
        return duration
    tags = stream.get("tags") or {}
    return _parse_duration_tag(tags.get("DURATION") or tags.get("duration"))


def _parse_seconds(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return _parse_duration_tag(value)


def _parse_duration_tag(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    text = str(value).strip()
    if ":" not in text:
        try:
            return float(text.replace(",", "."))
        except (TypeError, ValueError):
            return None
    try:
        parts = text.split(":")
        if len(parts) != 3:
            return None
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2].replace(",", "."))
        return hours * 3600.0 + minutes * 60.0 + seconds
    except (TypeError, ValueError):
        return None


def _parse_mediainfo_duration(value) -> float | None:
    seconds = _parse_seconds(value)
    if seconds is None:
        return None
    # MediaInfo JSON usually exposes raw Duration in milliseconds.
    if seconds > 10000:
        return seconds / 1000.0
    return seconds


def _parse_int(value) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _parse_fraction(value) -> Fraction | None:
    if value in (None, "", "N/A", "0/0"):
        return None
    text = str(value).strip().replace(",", ".")
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            fraction = Fraction(int(num), int(den))
        else:
            numeric = float(text)
            fraction = _nearest_common_rate(numeric) or Fraction(text).limit_denominator(1001)
        if fraction <= 0:
            return None
        return _nearest_common_rate(float(fraction)) or fraction
    except Exception:
        return None


def _nearest_common_rate(value: float) -> Fraction | None:
    for rate in _COMMON_FRAME_RATES:
        if abs(float(rate) - value) <= 0.001:
            return rate
    return None


def _nearest_common_rate_loose(value: float) -> Fraction | None:
    for rate in _COMMON_FRAME_RATES:
        if abs(float(rate) - value) <= max(0.005, float(rate) * 0.001):
            return rate
    return None


def _derived_fps_suffix(info: MediaTimingInfo) -> str:
    return " (aus Quelle/Frames abgeleitet)" if info.frame_rate_derived_from_source else ""


def _fps_label(fps: Fraction | None) -> str:
    if fps is None:
        return "unbekannt"
    return f"{fps.numerator}/{fps.denominator}"


def _choose_frame_rate(avg: Fraction | None, real: Fraction | None) -> Fraction | None:
    if avg is not None and avg > 0:
        return avg
    if real is not None and real > 0:
        return real
    return None


def _max_known(values: list[float | None]) -> float | None:
    known = [float(value) for value in values if value is not None and value > 0]
    return max(known) if known else None
