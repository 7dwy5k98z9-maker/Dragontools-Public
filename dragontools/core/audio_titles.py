from __future__ import annotations

from .lang_codes import lang_display


def _channel_label(channels: int | None) -> str:
    try:
        ch = int(channels or 0)
    except (TypeError, ValueError):
        ch = 0
    if ch >= 8:
        return "7.1"
    if ch >= 6:
        return "5.1"
    if ch == 2:
        return "Stereo"
    if ch == 1:
        return "Mono"
    return str(ch) if ch > 0 else ""


def build_audio_title(*, language: str | None, codec: str | None,
                      channels: int | None, bitrate_bps: int | None) -> str:
    """Canonical DragonTools audio title.

    If bitrate is unknown, deliberately return language only. This avoids
    pretending that copied source audio has verified codec/channel/bitrate
    metadata when bitrate is unavailable.
    """
    lang = lang_display((language or "und").lower())
    try:
        bitrate = int(bitrate_bps or 0)
    except (TypeError, ValueError):
        bitrate = 0
    if bitrate <= 0:
        return lang

    codec_label = (codec or "").strip().lower()
    codec_map = {"eac3": "EAC3", "ec-3": "EAC3", "ac3": "AC3", "aac": "AAC", "mp3": "MP3", "truehd": "TrueHD", "dts": "DTS", "flac": "FLAC", "opus": "Opus"}
    codec_label = codec_map.get(codec_label, codec_label.upper())
    ch = _channel_label(channels)
    kbps = max(1, round(bitrate / 1000))
    return " ".join(part for part in (lang, codec_label, ch, f"{kbps}kbps") if part)
