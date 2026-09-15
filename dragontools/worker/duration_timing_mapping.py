# -*- coding: utf-8 -*-
"""Map ffprobe/MediaInfo payloads onto MediaTimingInfo."""
from __future__ import annotations

from .duration_repair_models import MediaTimingInfo
from .duration_timing_parsing import (
    choose_frame_rate,
    max_known,
    parse_fraction,
    parse_int,
    parse_mediainfo_duration,
    parse_seconds,
    stream_duration,
)


def apply_ffprobe_timing(info: MediaTimingInfo, data: dict) -> None:
    fmt = data.get("format") or {}
    info.container_duration_s = parse_seconds(fmt.get("duration"))
    streams = list(data.get("streams") or [])
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    subtitles = [s for s in streams if s.get("codec_type") == "subtitle"]
    attachments = [s for s in streams if s.get("codec_type") == "attachment"]
    info.video_stream_count = len(videos)
    info.audio_stream_count = len(audios)
    info.subtitle_stream_count = len(subtitles)
    info.attachment_stream_count = len(attachments)
    if videos:
        video = videos[0]
        info.codec = str(video.get("codec_name") or "")
        info.video_duration_s = stream_duration(video)
        info.video_frame_count = parse_int(video.get("nb_read_frames")) or parse_int(video.get("nb_frames")) or info.video_frame_count
        avg = parse_fraction(video.get("avg_frame_rate"))
        real = parse_fraction(video.get("r_frame_rate"))
        info.avg_frame_rate = avg
        info.real_frame_rate = real
        info.frame_rate = choose_frame_rate(avg, real)
        info.has_b_frames = parse_int(video.get("has_b_frames")) not in (None, 0)
        info.video_start_s = parse_seconds(video.get("start_time"))
    info.audio_duration_s = max_known([stream_duration(s) for s in audios])
    if audios:
        info.audio_start_s = parse_seconds(audios[0].get("start_time"))
    info.subtitle_duration_s = max_known([stream_duration(s) for s in subtitles])
    info.chapter_end_s = max_known([parse_seconds(ch.get("end_time")) for ch in list(data.get("chapters") or [])])


def apply_mediainfo_timing(info: MediaTimingInfo, data: dict) -> None:
    tracks = list(((data.get("media") or {}).get("track")) or [])
    counts = {"video": 0, "audio": 0, "subtitle": 0, "attachment": 0}
    for track in tracks:
        kind = str(track.get("@type") or track.get("track_type") or "").lower()
        if kind == "general":
            info.container_duration_s = info.container_duration_s or parse_mediainfo_duration(track.get("Duration"))
        elif kind == "video":
            counts["video"] += 1
            mode = str(track.get("FrameRate_Mode") or track.get("FrameRate_Mode/String") or "").lower()
            if "variable" in mode or mode == "vfr":
                info.frame_rate_mode = "VFR"
            elif "constant" in mode or mode == "cfr":
                info.frame_rate_mode = "CFR"
            info.video_duration_s = info.video_duration_s or parse_mediainfo_duration(track.get("Duration"))
            info.video_frame_count = info.video_frame_count or parse_int(track.get("FrameCount"))
            if info.frame_rate is None:
                info.frame_rate = parse_fraction(track.get("FrameRate"))
            if not info.codec:
                info.codec = str(track.get("Format") or track.get("CodecID") or "")
        elif kind == "audio":
            counts["audio"] += 1
            info.audio_duration_s = max_known([info.audio_duration_s, parse_mediainfo_duration(track.get("Duration"))])
        elif kind in {"text", "subtitle"}:
            counts["subtitle"] += 1
            info.subtitle_duration_s = max_known([info.subtitle_duration_s, parse_mediainfo_duration(track.get("Duration"))])
        elif kind in {"menu", "attachment"}:
            counts["attachment"] += 1
    if info.video_stream_count <= 0:
        info.video_stream_count = counts["video"]
    if info.audio_stream_count <= 0:
        info.audio_stream_count = counts["audio"]
    if info.subtitle_stream_count <= 0:
        info.subtitle_stream_count = counts["subtitle"]
    if info.attachment_stream_count <= 0:
        info.attachment_stream_count = counts["attachment"]


__all__ = ["apply_ffprobe_timing", "apply_mediainfo_timing"]
