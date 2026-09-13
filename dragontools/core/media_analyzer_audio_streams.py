# -*- coding: utf-8 -*-
from __future__ import annotations

from .media_metadata import _normalize_lang
from .models import AudioStream
from .media_analyzer_io import _mi_bitrate, _mi_codec_audio, _mi_forced, _mi_stream_index
from .type_utils import _safe_int


def _build_audio_streams(mi_audios: list[dict], fp_audios: list[dict]) -> list[AudioStream]:
    audio_streams: list[AudioStream] = []
    for i in range(max(len(mi_audios), len(fp_audios))):
        mi_a = mi_audios[i] if i < len(mi_audios) else {}
        fp_a = fp_audios[i] if i < len(fp_audios) else {}
        tags = fp_a.get("tags", {}) or {}
        disposition = fp_a.get("disposition", {}) or {}

        idx = _safe_int(fp_a.get("index"), None) if fp_a else _mi_stream_index(mi_a, i)
        if idx is None:
            idx = _mi_stream_index(mi_a, i)

        codec = fp_a.get("codec_name") or _mi_codec_audio(mi_a) or mi_a.get("Format") or ""
        title = tags.get("title") or mi_a.get("Title") or ""
        fp_lang = tags.get("language")
        mi_lang = mi_a.get("Language") or mi_a.get("Language_String3")
        raw_lang = fp_lang if fp_lang and fp_lang.lower() != "und" else mi_lang
        final_language = _normalize_lang(raw_lang, title)
        channels = _safe_int(fp_a.get("channels") or mi_a.get("Channels"), 0)
        bitrate = _safe_int(fp_a.get("bit_rate") or tags.get("BPS") or tags.get("bps"), 0) or (_mi_bitrate(mi_a) or 0)
        forced = bool(disposition.get("forced", 0)) if fp_a else _mi_forced(mi_a)
        channel_layout = (
            fp_a.get("channel_layout")
            or mi_a.get("ChannelLayout")
            or mi_a.get("ChannelLayout_Original")
            or None
        )

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
            )
        )
    return audio_streams
