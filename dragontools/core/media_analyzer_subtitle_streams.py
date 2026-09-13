# -*- coding: utf-8 -*-
from __future__ import annotations

from .media_metadata import _normalize_lang, _parse_mediainfo_duration_s, _parse_seconds_value
from .models import SubtitleStream
from .media_analyzer_io import _mi_forced, _mi_stream_index
from .type_utils import _safe_int


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


def _parse_stream_duration_s(*values) -> float | None:
    for value in values:
        parsed = _parse_mediainfo_duration_s(value) or _parse_seconds_value(value)
        if parsed is not None:
            return parsed
        text = str(value or "").strip()
        if not text or ":" not in text:
            continue
        try:
            parts = [float(part.replace(",", ".")) for part in text.split(":")]
        except Exception:
            continue
        if len(parts) == 3:
            return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60.0 + parts[1]
    return None


def _subtitle_event_count(mi_track: dict, fp_stream: dict) -> int | None:
    tags = fp_stream.get("tags", {}) or {}
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


def _build_subtitle_streams(mi_texts: list[dict], fp_subs: list[dict]) -> list[SubtitleStream]:
    subtitle_streams: list[SubtitleStream] = []
    for i in range(max(len(mi_texts), len(fp_subs))):
        mi_s = mi_texts[i] if i < len(mi_texts) else {}
        fp_s = fp_subs[i] if i < len(fp_subs) else {}
        tags = fp_s.get("tags", {}) or {}
        disposition = fp_s.get("disposition", {}) or {}

        idx = _safe_int(fp_s.get("index"), None) if fp_s else _mi_stream_index(mi_s, i)
        if idx is None:
            idx = _mi_stream_index(mi_s, i)

        codec = _normalize_subtitle_codec(
            fp_s.get("codec_name")
            or mi_s.get("Format")
            or mi_s.get("CodecID")
            or mi_s.get("Format_Commercial")
            or ""
        )
        title = tags.get("title") or mi_s.get("Title") or ""
        fp_lang = tags.get("language")
        mi_lang = mi_s.get("Language") or mi_s.get("Language_String3")
        raw_lang = fp_lang if fp_lang and fp_lang.lower() != "und" else mi_lang
        final_language = _normalize_lang(raw_lang, title)
        forced = bool(disposition.get("forced", 0)) if fp_s else _mi_forced(mi_s)
        event_count = _subtitle_event_count(mi_s, fp_s)
        duration_s = _parse_stream_duration_s(mi_s.get("Duration"), fp_s.get("duration"), tags.get("DURATION"))

        subtitle_streams.append(
            SubtitleStream(
                index=idx,
                language=final_language,
                forced=forced,
                title=title,
                codec=str(codec),
                event_count=event_count,
                duration_s=duration_s,
            )
        )
    return subtitle_streams
