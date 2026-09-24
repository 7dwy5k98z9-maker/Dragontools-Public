# -*- coding: utf-8 -*-
"""Safe canonical titles for media tracks."""
from __future__ import annotations

from .audio_titles import build_audio_title
from .lang_codes import lang_display

_GENERIC_TRACK_TITLES = {
    "", "audio", "subtitle", "subtitles", "track", "unknown", "undefined", "und",
}


def track_title_is_generic(title: str | None) -> bool:
    text = str(title or "").strip().casefold()
    if text in _GENERIC_TRACK_TITLES:
        return True
    if text.startswith("track ") and text[6:].isdigit():
        return True
    return False


def build_track_title(
    *,
    stream_type: str,
    language: str,
    codec: str = "",
    channels: int | None = None,
    bitrate: int | None = None,
    forced: bool = False,
) -> str:
    kind = str(stream_type or "").strip().casefold()
    if kind == "audio":
        return build_audio_title(
            language=language,
            codec=codec,
            channels=channels,
            bitrate_bps=bitrate,
        )
    title = lang_display(language or "und")
    if kind == "subtitle" and forced:
        title += " Forced"
    return title


__all__ = ["build_track_title", "track_title_is_generic"]
