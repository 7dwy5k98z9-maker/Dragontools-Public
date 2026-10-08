# -*- coding: utf-8 -*-
from __future__ import annotations

from .media_metadata import (
    _normalize_lang,
    _parse_mediainfo_duration_s,
    _parse_seconds_value,
    clean_metadata_text,
    first_metadata_text,
)
from .media_track_pairing import pair_media_tracks
from .models import SubtitleStream
from .media_analyzer_io import _ffmpeg_stream_index, _mi_default, _mi_forced, _warn_untrusted_stream_index
from .type_utils import _safe_bool, _safe_int


def _normalize_subtitle_codec(value: str | None) -> str:
    """Normalize ffprobe/MediaInfo subtitle codec names to stable short names."""
    text = (value or "").strip().lower()
    if not text:
        return ""

    exact = {
        "subrip": "subrip",
        "srt": "subrip",
        "ass": "ass",
        "ssa": "ssa",
        "subt": "subt",
        "mov_text": "mov_text",
        "tx3g": "mov_text",
        "webvtt": "webvtt",
        "vtt": "webvtt",
        "d_webvtt/subtitles": "webvtt",
        "hdmv_pgs_subtitle": "hdmv_pgs_subtitle",
        "dvd_subtitle": "dvd_subtitle",
        "vobsub": "dvd_subtitle",
    }
    if text in exact:
        return exact[text]

    if "subt" in text:
        return "subt"
    if "mov_text" in text or "tx3g" in text or "timed text" in text:
        return "mov_text"
    if "subrip" in text:
        return "subrip"
    if "utf" in text or "s_text" in text:
        return "subrip"
    if "advanced substation" in text:
        return "ass"
    if "substation alpha" in text:
        return "ssa"
    if "pgs" in text or "hdmv" in text:
        return "hdmv_pgs_subtitle"
    if "dvd" in text or "vobsub" in text:
        return "dvd_subtitle"
    if "webvtt" in text or "vtt" in text:
        return "webvtt"
    return text


def _parse_clock_duration_s(value) -> float | None:
    text = str(value or "").strip()
    if not text or ":" not in text:
        return None
    try:
        parts = [float(part.replace(",", ".")) for part in text.split(":")]
    except (TypeError, ValueError):
        return None
    if len(parts) == 3:
        return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60.0 + parts[1]
    return None


def _parse_stream_duration_s(mi_value, fp_value, tag_value) -> float | None:
    """Parse duration without mixing MediaInfo milliseconds with ffprobe seconds."""
    parsed = _parse_mediainfo_duration_s(mi_value)
    if parsed is not None:
        return parsed
    parsed = _parse_seconds_value(fp_value)
    if parsed is not None:
        return parsed
    return _parse_clock_duration_s(tag_value)


def _subtitle_event_count(mi_track: dict, fp_stream: dict) -> int | None:
    tags_raw = fp_stream.get("tags", {}) or {}
    tags = tags_raw if isinstance(tags_raw, dict) else {}
    candidates = (
        fp_stream.get("nb_read_packets"),
        fp_stream.get("nb_read_frames"),
        fp_stream.get("nb_frames"),
        tags.get("NUMBER_OF_FRAMES"),
        tags.get("NUMBER_OF_PACKETS"),
        tags.get("NUMBER_OF_EVENTS"),
        mi_track.get("ElementCount"),
        mi_track.get("Count"),
        mi_track.get("FrameCount"),
        mi_track.get("Events"),
    )
    for value in candidates:
        count = _safe_int(value, None)
        if count is not None and count > 0:
            return count
    return None


def _build_subtitle_streams(
    mi_texts: list[dict],
    fp_subs: list[dict],
    analysis_warnings: list[str] | None = None,
) -> list[SubtitleStream]:
    subtitle_streams: list[SubtitleStream] = []
    for i, (mi_s, fp_s) in enumerate(pair_media_tracks(mi_texts, fp_subs, analysis_warnings)):
        tags_raw = fp_s.get("tags", {}) or {}
        tags = tags_raw if isinstance(tags_raw, dict) else {}
        disposition_raw = fp_s.get("disposition", {}) or {}
        disposition = disposition_raw if isinstance(disposition_raw, dict) else {}

        idx = _ffmpeg_stream_index(fp_s, i)
        if idx < 0:
            _warn_untrusted_stream_index(
                analysis_warnings,
                stream_type="Untertitel",
                ordinal=i,
            )

        codec = _normalize_subtitle_codec(
            first_metadata_text(
                fp_s.get("codec_name"),
                mi_s.get("Format"),
                mi_s.get("CodecID"),
                mi_s.get("Format_Commercial"),
            )
            or ""
        )
        title = first_metadata_text(tags.get("title"), mi_s.get("Title")) or ""
        fp_lang = tags.get("language")
        mi_lang = mi_s.get("Language") or mi_s.get("Language_String3")
        fp_lang_text = clean_metadata_text(fp_lang)
        if fp_lang_text and fp_lang_text.casefold() not in {"und", "unk", "undefined"}:
            raw_lang = fp_lang_text
        else:
            raw_lang = clean_metadata_text(mi_lang)
        final_language = _normalize_lang(raw_lang, title)
        forced = _safe_bool(disposition.get("forced", 0)) if "forced" in disposition else _mi_forced(mi_s)
        default = _safe_bool(disposition.get("default", 0)) if "default" in disposition else _mi_default(mi_s)
        event_count = _subtitle_event_count(mi_s, fp_s)
        duration_s = _parse_stream_duration_s(
            mi_s.get("Duration"),
            fp_s.get("duration"),
            tags.get("DURATION"),
        )

        subtitle_streams.append(
            SubtitleStream(
                index=idx,
                language=final_language,
                forced=forced,
                title=title,
                codec=str(codec),
                event_count=event_count,
                duration_s=duration_s,
                default=default,
            )
        )
    return subtitle_streams
