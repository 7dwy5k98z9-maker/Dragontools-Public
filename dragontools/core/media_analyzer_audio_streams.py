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
from .models import AudioStream
from .media_analyzer_io import (
    _ffmpeg_stream_index,
    _mi_bitrate,
    _mi_codec_audio,
    _mi_default,
    _mi_forced,
    _warn_untrusted_stream_index,
)
from .type_utils import _safe_bool, _safe_int


def _build_audio_streams(
    mi_audios: list[dict],
    fp_audios: list[dict],
    analysis_warnings: list[str] | None = None,
) -> list[AudioStream]:
    audio_streams: list[AudioStream] = []
    for i, (mi_a, fp_a) in enumerate(pair_media_tracks(mi_audios, fp_audios, analysis_warnings)):
        tags_raw = fp_a.get("tags", {}) or {}
        tags = tags_raw if isinstance(tags_raw, dict) else {}
        disposition_raw = fp_a.get("disposition", {}) or {}
        disposition = disposition_raw if isinstance(disposition_raw, dict) else {}

        idx = _ffmpeg_stream_index(fp_a, i)
        if idx < 0:
            _warn_untrusted_stream_index(
                analysis_warnings,
                stream_type="Audio",
                ordinal=i,
            )

        codec = first_metadata_text(fp_a.get("codec_name"), _mi_codec_audio(mi_a), mi_a.get("Format")) or ""
        title = first_metadata_text(tags.get("title"), mi_a.get("Title")) or ""
        fp_lang = tags.get("language")
        mi_lang = mi_a.get("Language") or mi_a.get("Language_String3")
        fp_lang_text = clean_metadata_text(fp_lang)
        if fp_lang_text and fp_lang_text.casefold() not in {"und", "unk", "undefined"}:
            raw_lang = fp_lang_text
        else:
            raw_lang = clean_metadata_text(mi_lang)
        final_language = _normalize_lang(raw_lang, title)
        channels = _safe_int(fp_a.get("channels"), None)
        if channels is None or channels <= 0:
            channels = _safe_int(mi_a.get("Channels"), 0)
        bitrate_candidates = (
            _safe_int(fp_a.get("bit_rate"), None),
            _safe_int(tags.get("BPS"), None),
            _safe_int(tags.get("bps"), None),
            _mi_bitrate(mi_a),
        )
        bitrate = next(
            (int(value) for value in bitrate_candidates if value is not None and value > 0),
            0,
        )
        forced = _safe_bool(disposition.get("forced", 0)) if "forced" in disposition else _mi_forced(mi_a)
        default = _safe_bool(disposition.get("default", 0)) if "default" in disposition else _mi_default(mi_a)
        channel_layout = (
            first_metadata_text(
                fp_a.get("channel_layout"),
                mi_a.get("ChannelLayout"),
                mi_a.get("ChannelLayout_Original"),
            )
        )
        duration_s = _parse_seconds_value(fp_a.get("duration"))
        if duration_s is None:
            duration_s = _parse_mediainfo_duration_s(mi_a.get("Duration"))

        audio_streams.append(
            AudioStream(
                index=idx,
                language=final_language,
                forced=forced,
                title=title,
                codec=str(codec),
                channels=channels,
                channel_layout=channel_layout,
                bitrate=bitrate,
                duration_s=duration_s,
                default=default,
            )
        )
    return audio_streams
