# -*- coding: utf-8 -*-
from __future__ import annotations

import logging

from .media_hdr_detection import detect_hdr_from_ffprobe_stream, detect_hdr_from_mediainfo_track, validate_hdr_flags
from .media_metadata import (
    _frame_rate_label, _frame_rate_mode_label, _normalize_lang,
    _parse_mediainfo_duration_s, _parse_seconds_value, build_pix_fmt_from_mediainfo,
    parse_bit_depth, normalize_video_codec,
)
from .models import AudioStream, SubtitleStream, VideoStream
from .media_analyzer_io import _mi_stream_index, _mi_bitrate, _mi_codec_audio, _mi_forced
from .type_utils import _safe_int, _safe_float

_log = logging.getLogger(__name__)

def _build_video_streams(
    mi_videos: list[dict],
    fp_videos: list[dict],
    mi_json: dict,            # wird NICHT für globale HDR-Suche genutzt
    analysis_warnings: list[str],
) -> list[VideoStream]:
    video_streams: list[VideoStream] = []
    video_count = max(len(mi_videos), len(fp_videos))

    for i in range(video_count):
        mi_v = mi_videos[i] if i < len(mi_videos) else {}
        fp_v = fp_videos[i] if i < len(fp_videos) else {}

        # Stream-Index: ffprobe-Wert bevorzugt, sonst MediaInfo StreamOrder
        idx = (
            _safe_int(fp_v.get("index"), None)
            if fp_v
            else _mi_stream_index(mi_v, i)
        )
        if idx is None:
            idx = _mi_stream_index(mi_v, i)

        codec = fp_v.get("codec_name") or mi_v.get("Format") or ""
        width  = _safe_int(mi_v.get("Width")  or fp_v.get("width"),  0)
        height = _safe_int(mi_v.get("Height") or fp_v.get("height"), 0)

        pix_fmt = build_pix_fmt_from_mediainfo(mi_v) or fp_v.get("pix_fmt") or None
        bit_depth = parse_bit_depth(mi_v, fp_v)

        color_space = (
            mi_v.get("colour_space") or mi_v.get("ColorSpace") or fp_v.get("color_space")
        )
        color_transfer = (
            mi_v.get("transfer_characteristics")
            or mi_v.get("TransferCharacteristics")
            or fp_v.get("color_transfer")
        )
        color_primaries = (
            mi_v.get("colour_primaries")
            or mi_v.get("colour_primaries_Source")
            or mi_v.get("ColorPrimaries")
            or fp_v.get("color_primaries")
        )

        duration_s = (
            _parse_mediainfo_duration_s(mi_v.get("Duration"))
            or _parse_seconds_value(fp_v.get("duration"))
        )
        frame_count = (
            _safe_int(mi_v.get("FrameCount"), None)
            or _safe_int(fp_v.get("nb_read_frames"), None)
            or _safe_int(fp_v.get("nb_frames"), None)
        )
        frame_rate = _frame_rate_label(
            mi_v.get("FrameRate"),
            fp_v.get("avg_frame_rate"),
            fp_v.get("r_frame_rate"),
        )
        frame_rate_mode = _frame_rate_mode_label(
            mi_v.get("FrameRate_Mode"),
            mi_v.get("FrameRate_Mode/String"),
        )
        reported_bitrate = (
            _safe_int(fp_v.get("bit_rate"), 0)
            or (_mi_bitrate(mi_v) or 0)
            or None
        )
        stream_size = _safe_int(mi_v.get("StreamSize"), 0)
        derived_bitrate = (
            int(round((stream_size * 8.0) / duration_s))
            if stream_size and stream_size > 0 and duration_s and duration_s > 0
            else None
        )
        # Manche MKV-Dateien enthalten einen defekten BPS-Tag, den MediaInfo als
        # winzigen Videowert (z. B. 651 Bit/s) übernimmt. Streamgröße/Dauer ist
        # für die durchschnittliche Bitrate in diesem Fall deutlich belastbarer.
        bitrate = reported_bitrate
        if derived_bitrate and (not bitrate or bitrate < 10_000):
            bitrate = derived_bitrate

        # HDR-Erkennung: nur strukturierte Track-Felder
        mi_is_hdr, mi_has_hdr10plus, mi_dv_profile = detect_hdr_from_mediainfo_track(mi_v)
        fp_is_hdr, fp_has_hdr10plus, fp_dv_profile = detect_hdr_from_ffprobe_stream(fp_v)

        # Quell-Priorität: verfügbare Quelle gewinnt (keine Mischung)
        if mi_v:
            is_hdr, has_hdr10plus, dv_profile = mi_is_hdr, mi_has_hdr10plus, mi_dv_profile
            # ffprobe als Ergaenzung nur wenn MI kein DV-Profil gefunden hat
            if not dv_profile and fp_dv_profile:
                dv_profile = fp_dv_profile
                is_hdr = is_hdr or fp_is_hdr
        else:
            is_hdr, has_hdr10plus, dv_profile = fp_is_hdr, fp_has_hdr10plus, fp_dv_profile

        # Harte Validierungsregeln anwenden
        is_hdr, has_hdr10plus, dv_profile = validate_hdr_flags(
            codec=codec,
            bit_depth=bit_depth,
            pix_fmt=pix_fmt,
            is_hdr=is_hdr,
            has_hdr10plus=has_hdr10plus,
            dv_profile=dv_profile,
            warnings=analysis_warnings,
        )

        if dv_profile:
            hdr_format: str | None = "dolby_vision"
        elif has_hdr10plus:
            hdr_format = "hdr10plus"
        elif is_hdr:
            hdr_format = "hdr10"
        else:
            hdr_format = None

        _log.debug(
            "[MediaAnalyzer] Video-Stream #%d: "
            "codec=%s pix_fmt=%s bit_depth=%s "
            "color_transfer=%s color_primaries=%s "
            "hdr_format=%s has_hdr=%s has_hdr10plus=%s has_dv=%s",
            i,
            normalize_video_codec(codec), pix_fmt, bit_depth,
            color_transfer, color_primaries,
            hdr_format, is_hdr, has_hdr10plus, dv_profile is not None,
        )

        video_streams.append(VideoStream(
            index=idx,
            codec=str(codec),
            width=width,
            height=height,
            hdr_format=hdr_format,
            has_hdr10plus=has_hdr10plus,
            has_dolby_vision=dv_profile is not None,
            profile=fp_v.get("profile") or mi_v.get("Format_Profile"),
            pix_fmt=pix_fmt,
            bit_depth=bit_depth,
            color_space=color_space,
            color_transfer=color_transfer,
            color_primaries=color_primaries,
            duration_s=duration_s,
            frame_count=frame_count,
            frame_rate=frame_rate,
            frame_rate_mode=frame_rate_mode,
            bitrate=bitrate,
        ))
    return video_streams

def _build_audio_streams(mi_audios: list[dict], fp_audios: list[dict]) -> list[AudioStream]:
    audio_streams: list[AudioStream] = []
    audio_count = max(len(mi_audios), len(fp_audios))
    for i in range(audio_count):
        mi_a = mi_audios[i] if i < len(mi_audios) else {}
        fp_a = fp_audios[i] if i < len(fp_audios) else {}

        tags        = fp_a.get("tags", {}) or {}
        disposition = fp_a.get("disposition", {}) or {}

        # Stream-Index: ffprobe bevorzugt, sonst MI StreamOrder
        idx = (
            _safe_int(fp_a.get("index"), None)
            if fp_a
            else _mi_stream_index(mi_a, i)
        )
        if idx is None:
            idx = _mi_stream_index(mi_a, i)

        codec = fp_a.get("codec_name") or _mi_codec_audio(mi_a) or mi_a.get("Format") or ""
        title = tags.get("title") or mi_a.get("Title") or ""

        fp_lang  = tags.get("language")
        mi_lang  = mi_a.get("Language") or mi_a.get("Language_String3")
        raw_lang = fp_lang if fp_lang and fp_lang.lower() != "und" else mi_lang
        final_language = _normalize_lang(raw_lang, title)

        channels = _safe_int(fp_a.get("channels") or mi_a.get("Channels"), 0)
        bitrate  = (
            _safe_int(fp_a.get("bit_rate") or tags.get("BPS") or tags.get("bps"), 0)
            or (_mi_bitrate(mi_a) or 0)
        )

        # Forced: ffprobe disposition bevorzugt, sonst MI-Feld
        if fp_a:
            forced = bool(disposition.get("forced", 0))
        else:
            forced = _mi_forced(mi_a)

        # Channel-Layout: ffprobe bevorzugt, sonst MI
        channel_layout = (
            fp_a.get("channel_layout")
            or mi_a.get("ChannelLayout")
            or mi_a.get("ChannelLayout_Original")
            or None
        )

        audio_streams.append(AudioStream(
            index=idx,
            language=final_language,
            forced=forced,
            title=title,
            codec=str(codec),
            channels=channels,
            channel_layout=channel_layout,
            bitrate=bitrate,
        ))
    return audio_streams

def _normalize_subtitle_codec(value: str | None) -> str:
    """Normalisiert einen Subtitle-Codec-String auf einen kanonischen kurzen Namen.

    Verarbeitet sowohl saubere ffprobe-codec_name-Werte ('subrip', 'ass') als
    auch lange MediaInfo-Format-Strings ('Text subtitles with various tags (subt)',
    'UTF-8') und gibt immer einen der bekannten Kurznamen zurück.
    """
    text = (value or "").strip().lower()
    if not text:
        return ""

    # Exakte Treffer zuerst (ffprobe-Standardwerte)
    if text == "subrip" or text == "srt":
        return "subrip"
    if text == "ass" or text == "ssa":
        return text
    if text == "subt":
        return "subt"
    if text == "mov_text" or text == "tx3g":
        return "mov_text"
    if text == "webvtt" or text == "vtt":
        return "webvtt"
    if text == "hdmv_pgs_subtitle":
        return "hdmv_pgs_subtitle"
    if text in {"dvd_subtitle", "vobsub"}:
        return "dvd_subtitle"

    # Substring-Matches für lange MediaInfo-Strings
    if "subt" in text:
        return "subt"
    if "mov_text" in text or "tx3g" in text or "timed text" in text:
        return "mov_text"
    if "subrip" in text:
        return "subrip"
    if "utf" in text or "s_text" in text:
        # MediaInfo: Format='UTF-8', CodecID='S_TEXT/UTF8' → subrip in MKV
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
    sub_count = max(len(mi_texts), len(fp_subs))
    for i in range(sub_count):
        mi_s = mi_texts[i] if i < len(mi_texts) else {}
        fp_s = fp_subs[i] if i < len(fp_subs) else {}

        tags        = fp_s.get("tags", {}) or {}
        disposition = fp_s.get("disposition", {}) or {}

        # Stream-Index: ffprobe bevorzugt, sonst MI StreamOrder
        idx = (
            _safe_int(fp_s.get("index"), None)
            if fp_s
            else _mi_stream_index(mi_s, i)
        )
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

        fp_lang  = tags.get("language")
        mi_lang  = mi_s.get("Language") or mi_s.get("Language_String3")
        raw_lang = fp_lang if fp_lang and fp_lang.lower() != "und" else mi_lang
        final_language = _normalize_lang(raw_lang, title)

        # Forced: ffprobe disposition bevorzugt, sonst MI-Feld
        if fp_s:
            forced = bool(disposition.get("forced", 0))
        else:
            forced = _mi_forced(mi_s)

        event_count = _subtitle_event_count(mi_s, fp_s)
        duration_s = _parse_stream_duration_s(
            mi_s.get("Duration"),
            fp_s.get("duration"),
            tags.get("DURATION"),
        )

        subtitle_streams.append(SubtitleStream(
            index=idx,
            language=final_language,
            forced=forced,
            title=title,
            codec=str(codec),
            event_count=event_count,
            duration_s=duration_s,
        ))
    return subtitle_streams
